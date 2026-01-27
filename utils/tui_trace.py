"""
tui_trace.py - BAT trace wrapper with TUI progress reporting.

Wraps the trace.deps() generator to provide real-time feedback to the TUI
about both datablocks being processed and files being discovered.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set, Tuple, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .submit_tui import SubmitTUI


def trace_dependencies_with_tui(
    blend_path: Path,
    tui: "SubmitTUI",
) -> Tuple[List[Path], Set[Path], Dict[Path, str]]:
    """
    Trace dependencies while feeding progress to the TUI.

    This wraps the BAT trace.deps() generator and extracts both:
    - Datablock info (block type + name) for the left column
    - File paths discovered for the right column

    Returns:
        (dependency_paths, missing_files, unreadable_files)
    """
    # Import here to avoid circular imports and ensure BAT is available
    import sys
    import os

    # Find the addon root to import BAT
    addon_dir = Path(__file__).parent.parent
    if str(addon_dir) not in sys.path:
        sys.path.insert(0, str(addon_dir))

    from blender_asset_tracer import trace
    from blender_asset_tracer.trace import progress as trace_progress

    # Create a custom callback that feeds the TUI
    class TUITraceCallback(trace_progress.Callback):
        def trace_blendfile(self, filename: Path) -> None:
            tui.trace_blendfile(str(filename))

    callback = TUITraceCallback()

    # Start tracing
    tui.set_phase("trace")
    tui.trace_blendfile(str(blend_path))

    deps: List[Path] = []
    missing: Set[Path] = set()
    unreadable: Dict[Path, str] = {}
    seen_hashes: Set[int] = set()

    for usage in trace.deps(blend_path, callback):
        abs_path = usage.abspath

        # Extract datablock info for TUI
        try:
            block_name = usage.block_name
            if isinstance(block_name, bytes):
                block_name = block_name.decode("utf-8", errors="replace")
            # Remove type prefix if present (e.g., "IMtexture.png" -> "texture.png")
            if len(block_name) >= 2 and block_name[:2].isupper():
                block_name = block_name[2:]
        except Exception:
            block_name = "?"

        try:
            block_type = getattr(usage.block, "dna_type_name", None) or "Block"
        except Exception:
            block_type = "Block"

        # Feed TUI
        tui.trace_datablock(block_type, block_name)
        tui.trace_file(str(abs_path))

        # Dedupe
        usage_hash = hash((str(abs_path), block_name))
        if usage_hash in seen_hashes:
            continue
        seen_hashes.add(usage_hash)

        deps.append(abs_path)

        # Check file status
        if not abs_path.exists():
            missing.add(abs_path)
        else:
            try:
                if abs_path.is_file():
                    with abs_path.open("rb") as f:
                        f.read(1)
            except (PermissionError, OSError) as e:
                unreadable[abs_path] = str(e)
            except Exception as e:
                unreadable[abs_path] = f"{type(e).__name__}: {e}"

    tui.trace_done()
    return deps, missing, unreadable


def pack_with_tui(
    infile: str,
    target: str,
    method: str,
    project_path: str,
    tui: "SubmitTUI",
    rewrite_blendfiles: bool = False,
) -> Tuple[Dict[Path, object], Dict[str, object]]:
    """
    Pack a blend file while feeding progress to the TUI.

    For PROJECT mode, returns (file_map, report).
    For ZIP mode, returns (empty_dict, report).
    """
    import sys
    import tempfile
    import shutil
    import uuid
    from pathlib import Path

    addon_dir = Path(__file__).parent.parent
    if str(addon_dir) not in sys.path:
        sys.path.insert(0, str(addon_dir))

    from blender_asset_tracer.pack import Packer, progress as pack_progress
    from blender_asset_tracer.pack import zipped

    infile_p = Path(infile)

    # Create TUI-feeding callback
    class TUIPackCallback(pack_progress.Callback):
        def pack_start(self) -> None:
            pass  # We set phase before calling

        def pack_done(self, output_blendfile, missing_files) -> None:
            tui.pack_done()

        def pack_aborted(self, reason: str) -> None:
            tui.set_error(f"Pack aborted: {reason}")

        def trace_blendfile(self, filename: Path) -> None:
            pass  # Already traced

        def trace_asset(self, filename: Path) -> None:
            pass  # Already traced

        def rewrite_blendfile(self, orig_filename: Path) -> None:
            tui.pack_rewrite(str(orig_filename))

        def transfer_file(self, src: Path, dst) -> None:
            try:
                size = src.stat().st_size if src.exists() else 0
            except Exception:
                size = 0
            tui.pack_file(str(src), size)

        def transfer_file_skipped(self, src: Path, dst) -> None:
            tui.pack_file(str(src), 0)

        def transfer_progress(self, total_bytes: int, transferred_bytes: int) -> None:
            # Update TUI progress
            pass

        def missing_file(self, filename: Path) -> None:
            tui.pack_missing(str(filename))

    callback = TUIPackCallback()

    tui.set_phase("pack")

    if method == "PROJECT":
        if not project_path:
            raise ValueError("project_path is required for method='PROJECT'")

        target_p = (
            Path(target)
            if str(target).strip()
            else Path(tempfile.mkdtemp(prefix="bat_packroot_"))
        )

        packer = Packer(
            infile_p,
            Path(project_path),
            str(target_p),
            noop=True,
            compress=False,
            relative_only=False,
            rewrite_blendfiles=rewrite_blendfiles,
        )
        packer.progress_cb = callback

        # Estimate file count for progress
        tui.pack_start(total_files=100, mode="PROJECT")  # Estimate

        packer.strategise()
        packer.execute()

        file_map = dict(packer.file_map)
        tui.state.pack.files_total = len(file_map)
        tui.update()

        # Persist rewritten blends if needed
        if rewrite_blendfiles:
            persist_dir = Path(tempfile.gettempdir()) / f"bat-rewrite-{uuid.uuid4().hex[:8]}"
            persist_dir.mkdir(parents=True, exist_ok=True)

            new_map: Dict[Path, object] = {}
            for src, dst in file_map.items():
                src_p = Path(src)
                try:
                    rewrite_root = Path(packer._rewrite_in)
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

            file_map = new_map

        report = {
            "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
            "unreadable_files": {
                str(k): v
                for k, v in sorted(
                    getattr(packer, "unreadable_files", {}).items(),
                    key=lambda kv: str(kv[0]),
                )
            },
        }

        packer.close()
        tui.pack_done()
        return file_map, report

    elif method == "ZIP":
        project_p = Path(project_path) if project_path else infile_p.parent

        # Start pack with estimated file count
        tui.pack_start(total_files=100, mode="ZIP")

        with zipped.ZipPacker(infile_p, project_p, Path(target)) as packer:
            packer.progress_cb = callback
            packer.strategise()

            # Update with actual count
            tui.state.pack.files_total = len(packer._actions)
            tui.update()

            packer.execute()

            report = {
                "zip_path": str(Path(target)),
                "output_path": str(packer.output_path),
                "missing_files": [str(p) for p in sorted(getattr(packer, "missing_files", set()))],
                "unreadable_files": {
                    str(k): v
                    for k, v in sorted(
                        getattr(packer, "unreadable_files", {}).items(),
                        key=lambda kv: str(kv[0]),
                    )
                },
            }

        tui.pack_done()
        return {}, report

    raise ValueError(f"Unknown method: {method!r}")
