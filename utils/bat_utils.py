from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple

from ..blender_asset_tracer import trace, bpathlib
from ..blender_asset_tracer.pack import Packer
from ..blender_asset_tracer.pack import zipped

# Import cloud file utilities for handling OneDrive/Google Drive/iCloud placeholders
from . import cloud_files

import logging

_log = logging.getLogger(__name__)


# ─── Drive detection helpers (OS-agnostic) ───────────────────────────────────

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]+")


def _is_win_drive_path(p: str) -> bool:
    """Check if path looks like a Windows drive path (C:/ or C:\\)."""
    return bool(_WIN_DRIVE_RE.match(str(p)))


def _drive(path: str) -> str:
    """
    Return a drive token representing the path's root device for cross-drive checks.

    - Windows letters: "C:", "D:", ...
    - UNC: "UNC"
    - macOS volumes: "/Volumes/NAME"
    - Linux removable/media: "/media/USER/NAME" or "/mnt/NAME"
    - Otherwise POSIX root "/"

    Works correctly even when running on POSIX with Windows-style paths (for testing).
    """
    p = str(path).replace("\\", "/")
    if _is_win_drive_path(p):
        return (p[:2]).upper()  # "C:"
    if p.startswith("//") or p.startswith("\\\\"):
        return "UNC"
    if os.name == "nt":
        return os.path.splitdrive(p)[0].upper()

    # macOS volumes
    if p.startswith("/Volumes/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return "/Volumes/" + parts[2]
        return "/Volumes"

    # Linux common mounts
    if p.startswith("/media/"):
        parts = p.split("/")
        if len(parts) >= 4:
            return f"/media/{parts[2]}/{parts[3]}"
        return "/media"

    if p.startswith("/mnt/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return f"/mnt/{parts[2]}"
        return "/mnt"

    # Fallback: POSIX root
    return "/"


def _norm_path(path: str) -> str:
    """Normalize path for comparison, preserving Windows-style paths on POSIX."""
    p = str(path).replace("\\", "/")
    if _is_win_drive_path(p) or p.startswith("//") or p.startswith("\\\\"):
        return p
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/")


# ─── Lightweight dependency tracing ──────────────────────────────────────────


def _get_block_type(usage: Any) -> str:
    """Get the DNA type name from a BlockUsage."""
    try:
        return getattr(usage.block, "dna_type_name", "Unknown")
    except Exception:
        return "Unknown"


def _get_block_name(usage: Any) -> str:
    """Get the block name from a BlockUsage, cleaned up."""
    try:
        block_name = usage.block_name
        if isinstance(block_name, bytes):
            block_name = block_name.decode("utf-8", errors="replace")
        # Remove type prefix like "IM" or "LI" from names like "IMtexture.png"
        if len(block_name) >= 2 and block_name[:2].isupper():
            block_name = block_name[2:]
        return block_name
    except Exception:
        return "unknown"


def _get_source_blend_name(usage: Any) -> str:
    """Get the source .blend filepath from a BlockUsage."""
    try:
        filepath = usage.block.bfile.filepath
        return str(filepath)
    except Exception:
        return "unknown.blend"


def trace_dependencies(
    blend_path: Path,
    logger: Optional[Any] = None,
    *,
    hydrate: bool = False,
    diagnostic_report: Optional[Any] = None,
) -> Tuple[List[Path], Set[Path], Dict[Path, str], List[Any], Set[Path]]:
    """
    Lightweight dependency trace using BAT's trace.deps().

    Args:
        blend_path: Path to the .blend file to trace
        logger: Optional SubmitLogger instance for rich logging.
                If provided, logs each dependency with colors and formatting.
        hydrate: If True, reads entire files to force cloud-mounted drives
                 (OneDrive, Google Drive, iCloud, etc.) to fully download
                 "dehydrated" placeholder files. Use for PROJECT mode uploads.

    Returns:
        (dependency_paths, missing_files, unreadable_files, raw_usages, optional_paths)

    Where:
        - dependency_paths: List of absolute paths to all dependencies (expanded from sequences)
        - missing_files: Set of paths that don't exist on disk
        - unreadable_files: Dict of path -> error message for files that exist but can't be read
        - raw_usages: List of BlockUsage objects (can be passed to Packer to avoid re-tracing)
        - optional_paths: Set of paths that are optional (e.g. linked-packed libraries) and
                          should NOT affect project root calculation
    """
    deps: List[Path] = []
    missing: Set[Path] = set()
    unreadable: Dict[Path, str] = {}
    raw_usages: List[Any] = []
    optional: Set[Path] = set()

    for usage in trace.deps(blend_path):
        is_optional = getattr(usage, "is_optional", False)
        raw_usages.append(usage)

        # Get source info for logging (needed for both logger and diagnostic_report)
        needs_block_info = logger or diagnostic_report
        source_blend = _get_source_blend_name(usage) if needs_block_info else ""
        block_type = _get_block_type(usage) if needs_block_info else ""
        block_name = _get_block_name(usage) if needs_block_info else ""

        # Use usage.files() to properly expand sequences (UDIM, image sequences, etc.)
        # This handles glob patterns and returns actual file paths.
        # For non-sequences, it yields the single file path.
        expanded_files: List[Path] = []
        files_error: Optional[str] = None
        try:
            expanded_files = list(usage.files())
        except FileNotFoundError as e:
            # Expected for missing directories - not an error, just means file doesn't exist
            files_error = str(e)
            _log.debug("files() raised FileNotFoundError for %s: %s", usage.asset_path, e)
        except Exception as e:
            # Unexpected error - log it for debugging
            files_error = str(e)
            _log.warning("files() raised unexpected exception for %s: %s", usage.asset_path, e)

        if not expanded_files:
            # No files found - either pattern didn't match or file doesn't exist
            # Use bpathlib.make_absolute() for consistent path normalization (like native BAT)
            # This handles ../../ resolution without following symlinks, and Windows paths on POSIX
            try:
                abs_path = bpathlib.make_absolute(usage.abspath)
            except Exception as e:
                # Fallback if make_absolute fails (e.g., invalid path characters)
                abs_path = usage.abspath
                _log.debug("make_absolute failed for %s: %s", usage.abspath, e)

            deps.append(abs_path)
            if is_optional:
                optional.add(abs_path)
                # Don't log or report optional missing files - they're expected
            else:
                missing.add(abs_path)

                if logger is not None:
                    logger.trace_entry(
                        source_blend=source_blend,
                        block_type=block_type,
                        block_name=block_name,
                        found_file=abs_path.name,
                        status="missing",
                        error_msg=files_error,
                    )

                if diagnostic_report is not None:
                    diagnostic_report.add_trace_entry(
                        source_blend=source_blend,
                        block_type=block_type,
                        block_name=block_name,
                        resolved_path=str(abs_path),
                        status="missing",
                        error_msg=files_error,
                        file_size=0,
                    )
        else:
            # Check each expanded file
            for raw_file_path in expanded_files:
                # Normalize the path using bpathlib.make_absolute() for consistency
                # This is what native BAT does in list_deps.py
                try:
                    file_path = bpathlib.make_absolute(raw_file_path)
                except Exception:
                    # Fallback if make_absolute fails
                    file_path = raw_file_path

                deps.append(file_path)
                if is_optional:
                    optional.add(file_path)

                # Try to read the file (and hydrate if on cloud drive)
                ok, err = cloud_files.read_file_with_hydration(
                    str(file_path),
                    hydrate=hydrate,
                    timeout_seconds=30,
                )

                if ok:
                    status = "ok"
                    error_msg = None
                elif err == "File not found":
                    if is_optional:
                        # Optional missing files are expected - skip logging
                        continue
                    missing.add(file_path)
                    status = "missing"
                    error_msg = None
                else:
                    unreadable[file_path] = err or "Unknown error"
                    status = "unreadable"
                    error_msg = err

                if logger is not None:
                    logger.trace_entry(
                        source_blend=source_blend,
                        block_type=block_type,
                        block_name=block_name,
                        found_file=file_path.name,
                        status=status,
                        error_msg=error_msg,
                    )

                if diagnostic_report is not None:
                    # Get file size if file exists and is readable
                    file_size = 0
                    if status == "ok":
                        try:
                            file_size = file_path.stat().st_size
                        except Exception:
                            pass
                    diagnostic_report.add_trace_entry(
                        source_blend=source_blend,
                        block_type=block_type,
                        block_name=block_name,
                        resolved_path=str(file_path),
                        status=status,
                        error_msg=error_msg,
                        file_size=file_size,
                    )

    return deps, missing, unreadable, raw_usages, optional


# ─── Project root computation ────────────────────────────────────────────────


def compute_project_root(
    blend_path: Path,
    dependency_paths: List[Path],
    custom_project_path: Optional[Path] = None,
    missing_files: Optional[Set[Path]] = None,
    unreadable_files: Optional[Dict[Path, str]] = None,
    optional_files: Optional[Set[Path]] = None,
) -> Tuple[Path, List[Path], List[Path]]:
    """
    Compute optimal project root from blend file and its dependencies.

    Algorithm:
    1. If custom_project_path is provided and valid, use it
    2. Otherwise, compute lowest common ancestor of blend + same-drive deps
    3. Filter out cross-drive dependencies (return separately for warning)
    4. Ensure result is a directory

    Args:
        blend_path: Path to the main .blend file
        dependency_paths: List of dependency paths from trace_dependencies()
        custom_project_path: Optional user-specified project root
        missing_files: Optional set of paths that don't exist (excluded from root calculation)
        unreadable_files: Optional dict of paths that can't be read (excluded from root calculation)
        optional_files: Optional set of paths that are optional (e.g. linked-packed libraries)
                        and should not affect root calculation

    Returns:
        (project_root, same_drive_paths, cross_drive_paths)

    Where:
        - project_root: The computed project root directory
        - same_drive_paths: Dependencies on the same drive as the blend
        - cross_drive_paths: Dependencies on different drives (excluded from project upload)
    """
    # Use os.path.abspath() consistently (not resolve()) to avoid symlink surprises on Mac.
    # On macOS, resolve() can turn /Users/... into /System/Volumes/Data/Users/... which
    # breaks relative path computation when blend_path uses the non-resolved form.
    blend_abs = _norm_path(str(blend_path))
    blend_drive = _drive(blend_abs)
    blend_dir = Path(os.path.abspath(blend_path)).parent

    # Classify dependencies by drive
    same_drive_paths: List[Path] = []
    cross_drive_paths: List[Path] = []

    # Normalize missing/unreadable/optional sets for comparison - these files won't be uploaded
    # or shouldn't affect project root, so exclude from calculation
    missing_norm = {_norm_path(str(p)) for p in (missing_files or set())}
    unreadable_norm = {_norm_path(str(p)) for p in (unreadable_files or {}).keys()}
    optional_norm = {_norm_path(str(p)) for p in (optional_files or set())}
    excluded_paths = missing_norm | unreadable_norm | optional_norm

    for dep in dependency_paths:
        dep_norm = _norm_path(str(dep))

        # Skip missing/unreadable files - they won't be uploaded
        if dep_norm in excluded_paths:
            continue

        dep_drive = _drive(dep_norm)
        if dep_drive == blend_drive:
            same_drive_paths.append(dep)
        else:
            cross_drive_paths.append(dep)

    # If custom project path is provided and valid, use it
    if custom_project_path is not None:
        custom_abs = Path(os.path.abspath(custom_project_path))
        if custom_abs.is_file():
            custom_abs = custom_abs.parent
        if custom_abs.is_dir():
            return custom_abs, same_drive_paths, cross_drive_paths

    # Compute common path from blend + same-drive dependencies
    if not same_drive_paths:
        # No same-drive dependencies, just use blend's parent directory
        return blend_dir, same_drive_paths, cross_drive_paths

    # Collect all paths to compute common ancestor (use abspath, not resolve, for consistency)
    all_same_drive = [os.path.abspath(str(blend_path))] + [os.path.abspath(str(p)) for p in same_drive_paths]

    try:
        common = os.path.commonpath(all_same_drive)
        common_path = Path(common)

        # Ensure it's a directory
        if common_path.is_file():
            common_path = common_path.parent

        # Verify it's actually a directory that exists
        if common_path.is_dir():
            return common_path, same_drive_paths, cross_drive_paths
    except (ValueError, OSError):
        # commonpath can fail if paths are on different drives (shouldn't happen
        # since we filtered, but be defensive) or if paths are empty
        pass

    # Fallback to blend's parent directory
    return blend_dir, same_drive_paths, cross_drive_paths


def create_packer(
    bpath: Path,
    ppath: Path,
    target: Path,
    *,
    rewrite_blendfiles: bool = False,
    pre_traced_deps: Optional[List[Any]] = None,
) -> Packer:
    # NOTE: target is converted to str so BAT can treat it as "path ops only".
    packer = Packer(
        bpath,
        ppath,
        str(target),
        noop=True,
        compress=False,
        relative_only=False,
        rewrite_blendfiles=rewrite_blendfiles,
        pre_traced_deps=pre_traced_deps,
    )
    return packer


def pack_blend(
    infile,
    target,
    method: str = "ZIP",
    project_path: Optional[str] = None,
    *,
    rewrite_blendfiles: bool = False,
    return_report: bool = False,
    pre_traced_deps: Optional[List[Any]] = None,
    zip_emit_fn=None,
    zip_entry_cb=None,
    zip_done_cb=None,
):
    """Pack a blend.

    PROJECT:
      - returns packer.file_map (src_path -> packed_path)
      - if rewrite_blendfiles=True, blend files are rewritten and the rewritten
        temp files are copied into a persistent temp dir so they survive packer.close()

    ZIP:
      - produces zip at target (existing behavior)
      - if return_report=True, returns a dict with missing/unreadable details

    pre_traced_deps:
      - Optional list of BlockUsage objects from a previous trace_dependencies() call.
      - When provided, avoids redundant trace.deps() call inside the packer.
    """
    infile_p = Path(infile)

    if method == "PROJECT":
        if project_path is None:
            raise ValueError("project_path is required for method='PROJECT'")

        project_p = Path(project_path)

        # FAST PATH: When we have pre-traced deps and don't need blendfile rewriting,
        # skip the packer entirely and build file_map directly from trace results.
        # This avoids redundant filesystem checks in packer.strategise().
        #
        # pre_traced_deps can be either:
        # - List of BlockUsage objects (from raw trace)
        # - List of Path objects (pre-expanded file paths)
        if pre_traced_deps is not None and not rewrite_blendfiles:
            file_map: Dict[Path, Path] = {}
            # Add the main blend file
            file_map[infile_p] = infile_p

            # Add all dependencies that are within the project
            for item in pre_traced_deps:
                # Check if it's a Path (pre-expanded) or BlockUsage
                if isinstance(item, Path):
                    file_path = item
                    try:
                        file_path.relative_to(project_p)
                        file_map[file_path] = file_path
                    except ValueError:
                        pass  # Outside project
                else:
                    # BlockUsage - use abspath (don't call files() to avoid I/O)
                    try:
                        file_path = item.abspath
                        # Skip patterns - they should have been expanded already
                        if "<UDIM>" in file_path.name or "*" in file_path.name:
                            continue
                        file_path.relative_to(project_p)
                        file_map[file_path] = file_path
                    except (ValueError, AttributeError):
                        pass  # Outside project or invalid

            report: Dict[str, Any] = {
                "missing_files": [],
                "unreadable_files": {},
            }
            return (file_map, report) if return_report else file_map

        # SLOW PATH: Use full packer (needed for blendfile rewriting)
        # If target is empty, use a stable temp pack-root (path ops only)
        target_p = Path(target) if str(target).strip() else Path(
            tempfile.mkdtemp(prefix="bat_packroot_")
        )

        packer = create_packer(
            infile_p,
            project_p,
            target_p,
            rewrite_blendfiles=rewrite_blendfiles,
            pre_traced_deps=pre_traced_deps,
        )
        packer.strategise()
        packer.execute()

        file_map = dict(packer.file_map)

        # If we rewrote blend files in packer temp dir, those files will be deleted on packer.close().
        # Persist them now, and update file_map keys accordingly.
        if rewrite_blendfiles:
            persist_dir = Path(tempfile.gettempdir()) / f"bat-rewrite-{uuid.uuid4().hex[:8]}"
            persist_dir.mkdir(parents=True, exist_ok=True)

            new_map: Dict[Path, object] = {}
            for src, dst in file_map.items():
                src_p = Path(src)
                try:
                    rewrite_root = Path(packer._rewrite_in)  # type: ignore[attr-defined]
                    is_rewrite = str(src_p).startswith(str(rewrite_root))
                except Exception:
                    is_rewrite = False

                if is_rewrite and src_p.exists():
                    new_src = persist_dir / src_p.name
                    try:
                        shutil.copy2(src_p, new_src)
                        new_map[new_src] = dst
                    except Exception:
                        new_map[src_p] = dst
                else:
                    new_map[src_p] = dst

            file_map = new_map  # type: ignore[assignment]

        # Optional report (for project mode, callers often do their own scanning,
        # but we expose it anyway).
        report: Dict[str, Any] = {
            "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
            "unreadable_files": {str(k): v for k, v in sorted(getattr(packer, "unreadable_files", {}).items(), key=lambda kv: str(kv[0]))},
        }

        packer.close()
        return (file_map, report) if return_report else file_map

    elif method == "ZIP":
        import logging as _logging

        # Use provided project_path for meaningful zip structure, fallback to blend's parent
        project_p = Path(project_path) if project_path else Path(infile).parent

        # Install structured callbacks if provided (suppresses raw _emit output)
        if zip_emit_fn or zip_entry_cb or zip_done_cb:
            zipped.set_emit(fn=zip_emit_fn, entry_cb=zip_entry_cb, done_cb=zip_done_cb)

        # Suppress BAT's own "Missing file:" log.warning during packing –
        # the caller already reported missing files in the trace stage.
        _bat_pack_logger = _logging.getLogger("blender_asset_tracer.pack")
        _prev_level = _bat_pack_logger.level
        _bat_pack_logger.setLevel(_logging.ERROR)

        try:
            with zipped.ZipPacker(
                Path(infile), project_p, Path(target), pre_traced_deps=pre_traced_deps
            ) as packer:
                packer.strategise()
                packer.execute()

                if return_report:
                    return {
                        "zip_path": str(Path(target)),
                        "output_path": str(packer.output_path),
                        "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
                        "unreadable_files": {str(k): v for k, v in sorted(getattr(packer, "unreadable_files", {}).items(), key=lambda kv: str(kv[0]))},
                    }
        finally:
            # Restore logger level and reset emit callbacks
            _bat_pack_logger.setLevel(_prev_level)
            zipped.set_emit()

        return None

    raise ValueError(f"Unknown method: {method!r}")
