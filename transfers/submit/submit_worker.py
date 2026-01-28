# submit_worker.py
"""
submit_worker.py – Superluminal Submit worker (robust, with retries).
Business logic only; all generic helpers live in submit_utils.py.

Key guarantees:
- Filters out cross-drive dependencies during Project uploads so path-root
  detection is stable (works on Windows, macOS, Linux, and with fake Windows
  paths while testing on Linux).
- Sanitizes ALL S3 keys and manifest entries to prevent leading slashes or
  duplicate separators (e.g., avoids "input//Users/...").
- Handles empty/invalid custom project paths gracefully.
- User-facing logs are calm, actionable, and avoid scary wording.

IMPORTANT:
This file is imported by Blender during add-on enable/registration in some setups.
It must NOT access sys.argv[1] or run worker logic at import time.
All worker execution happens inside main(), guarded by __name__ == "__main__".
"""

from __future__ import annotations

# ─── stdlib ──────────────────────────────────────────────────────
import importlib
import json
import os
import re
import sys
import shutil
import tempfile
import time
import types
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import webbrowser

import requests


def _nfc(s: str) -> str:
    """Normalize string to NFC form (matches BAT's archive path normalization)."""
    return unicodedata.normalize("NFC", str(s))


def _is_interactive() -> bool:
    """Check if we're running in an interactive terminal."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _safe_input(prompt: str, default: str = "") -> str:
    """
    Safe input wrapper that handles non-interactive (automated) mode.

    When stdin is not a TTY (e.g., in automated tests or piped input),
    returns the default value instead of blocking on input().
    """
    if _is_interactive():
        return input(prompt)
    # Non-interactive mode: log and return default
    _LOG(f"[auto] {prompt.strip()} -> {repr(default)}")
    return default


# ─── Lightweight logger fallback ──────────────────────────────────
# This gets replaced after bootstrap when worker_utils.logger is available.
def _default_logger(msg: str) -> None:
    print(str(msg))


_LOG = _default_logger


def _set_logger(fn) -> None:
    global _LOG
    _LOG = fn if callable(fn) else _default_logger


# ─── Path helpers (OS-agnostic drive detection + S3 key cleaning) ────────────

_WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]+")
_IS_MAC = sys.platform == "darwin"


def _is_win_drive_path(p: str) -> bool:
    return bool(_WIN_DRIVE.match(str(p)))


def _norm_abs_for_detection(path: str) -> str:
    """Normalize a path for comparison but keep Windows-looking/UNC paths intact on POSIX."""
    p = str(path).replace("\\", "/")
    if _is_win_drive_path(p) or p.startswith("//") or p.startswith("\\\\"):
        return p
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/")


def _drive(path: str) -> str:
    """
    Return a drive token representing the path's root device for cross-drive checks.

    - Windows letters: "C:", "D:", ...
    - UNC: "UNC"
    - macOS volumes: "/Volumes/NAME"
    - Linux removable/media: "/media/USER/NAME" or "/mnt/NAME"
    - Otherwise POSIX root "/"
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


def _relpath_safe(child: str, base: str) -> str:
    """Safe relpath (POSIX separators). Caller must ensure same 'drive'."""
    return os.path.relpath(child, start=base).replace("\\", "/")


def _s3key_clean(key: str) -> str:
    """
    Ensure S3 keys / manifest lines are clean and relative:
    - collapse duplicate slashes
    - strip any leading slash
    - normalize '.' and '..'
    """
    k = str(key).replace("\\", "/")
    k = re.sub(r"/+", "/", k)  # collapse duplicate slashes
    k = k.lstrip("/")  # forbid leading slash
    k = os.path.normpath(k).replace("\\", "/")
    if k == ".":
        return ""  # do not allow '.' as a key
    return k


def _samepath(a: str, b: str) -> bool:
    """Case-insensitive, normalized equality check suitable for Windows/POSIX."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
        os.path.normpath(b)
    )


def _looks_like_cloud_storage_path(p: str) -> bool:
    s = str(p or "").replace("\\", "/")
    return (
        "/Library/CloudStorage/" in s
        or "/Dropbox" in s
        or "/OneDrive" in s
        or "/iCloud" in s
        or "/Mobile Documents/" in s
    )


def _mac_permission_help(path: str, err: str) -> str:
    lines = [
        "macOS blocked access to a file we need to upload/pack.",
        "",
        "Fix:",
        "  - System Settings -> Privacy & Security -> Full Disk Access",
        "  - Enable the app running this upload (Terminal/iTerm if you see this console; otherwise Blender).",
    ]
    if _looks_like_cloud_storage_path(path):
        lines += [
            "",
            "Cloud storage note:",
            "  - This file is in a cloud-synced folder.",
            "  - Make sure it's downloaded / available offline, then retry.",
        ]
    lines += ["", f"Technical: {err}"]
    return "\n".join(lines)


def _probe_readable_file(p: str) -> Tuple[bool, Optional[str]]:
    """
    Returns (ok, error_message).
    - ok=True: file exists and can be opened for reading
    - ok=False: missing or unreadable (permission / offline placeholder / etc.)
    """
    path = str(p)
    if not os.path.exists(path):
        return (False, "missing")
    if os.path.isdir(path):
        # We generally don't upload dirs directly in project mode manifests.
        return (False, "is a directory")
    try:
        with open(path, "rb") as f:
            f.read(1)
        return (True, None)
    except PermissionError as exc:
        return (False, f"PermissionError: {exc}")
    except OSError as exc:
        return (False, f"OSError: {exc}")
    except Exception as exc:
        return (False, f"{type(exc).__name__}: {exc}")


def _should_moveto_local_file(local_path: str, original_blend_path: str) -> bool:
    """
    Return True only when it's safe to let rclone delete the local file after upload.

    We treat `moveto` as *dangerous* and only allow it when:
      - local_path is NOT the same as the user's original .blend path
      - local_path is located under the OS temp directory

    Otherwise use `copyto` (never deletes).
    """
    lp = str(local_path or "").strip()
    op = str(original_blend_path or "").strip()
    if not lp:
        return False

    # Never move the user's actual blend file.
    try:
        if op and _samepath(lp, op):
            return False
    except Exception:
        return False

    # Only allow move when file is under temp dir.
    try:
        lp_abs = os.path.abspath(lp)
        tmp_abs = os.path.abspath(tempfile.gettempdir())
        common = os.path.commonpath([lp_abs, tmp_abs])
        if _samepath(common, tmp_abs):
            return True
    except Exception:
        return False

    return False


# ─── Report generation helpers ─────────────────────────────────────


def _format_size(size_bytes: int) -> str:
    """Format bytes as human readable."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _generate_report(
    blend_path: str,
    dep_paths: List[Path],
    missing_set: set,
    unreadable_dict: dict,
    project_root: Path,
    same_drive_deps: List[Path],
    cross_drive_deps: List[Path],
    upload_type: str,
    addon_dir: Optional[str] = None,
    job_id: Optional[str] = None,
    mode: str = "test",
) -> Tuple[dict, Optional[Path]]:
    """
    Generate a diagnostic report and save it to the reports directory.

    Returns: (report_dict, report_path) where report_path is None if saving failed.
    """
    from datetime import datetime

    # Build report data
    blend_size = 0
    try:
        blend_size = os.path.getsize(blend_path)
    except:
        pass

    # Classify by extension
    by_ext: Dict[str, int] = {}
    total_size = 0
    for dep in dep_paths:
        ext = dep.suffix.lower() if dep.suffix else "(no ext)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
        if dep.exists() and dep.is_file():
            try:
                total_size += dep.stat().st_size
            except:
                pass

    report = {
        "report_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "mode": mode,
        "upload_type": upload_type,
        "blend_file": {
            "path": str(blend_path),
            "name": os.path.basename(blend_path),
            "size_bytes": blend_size,
            "size_human": _format_size(blend_size),
        },
        "project_root": str(project_root),
        "dependencies": {
            "total_count": len(dep_paths),
            "total_size_bytes": total_size,
            "total_size_human": _format_size(total_size),
            "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])),
            "same_drive_count": len(same_drive_deps),
            "cross_drive_count": len(cross_drive_deps),
        },
        "issues": {
            "missing_count": len(missing_set),
            "missing_files": [str(p) for p in sorted(missing_set)],
            "unreadable_count": len(unreadable_dict),
            "unreadable_files": {str(k): v for k, v in sorted(unreadable_dict.items())},
            "cross_drive_count": len(cross_drive_deps),
            "cross_drive_files": [str(p) for p in sorted(cross_drive_deps)],
        },
        "all_dependencies": [str(p) for p in sorted(dep_paths)],
    }

    # Add job_id if available
    if job_id:
        report["job_id"] = job_id

    # Save report to file
    report_path = None
    try:
        # Determine reports directory
        if addon_dir:
            reports_dir = Path(addon_dir) / "reports"
        else:
            # Fallback: try to find addon dir from this file's location
            reports_dir = Path(__file__).parent.parent.parent / "reports"

        reports_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename: submit_report_YYYYMMDD_HHMMSS_<blend_name>.json
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        blend_name = Path(blend_path).stem[:30]  # Truncate long names
        # Sanitize blend name for filename
        blend_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in blend_name)
        filename = f"submit_report_{timestamp}_{blend_name}.json"

        report_path = reports_dir / filename
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

    except Exception as e:
        _LOG(f"Warning: Could not save report: {e}")
        report_path = None

    return report, report_path


# ─── Worker bootstrap (safe to import) ────────────────────────────

def _load_handoff_from_argv(argv: List[str]) -> Dict[str, object]:
    if len(argv) < 2:
        raise RuntimeError(
            "submit_worker.py was launched without a handoff JSON path.\n"
            "This script should be run as a subprocess by the add-on.\n"
            "Example: submit_worker.py /path/to/handoff.json"
        )
    handoff_path = Path(argv[1]).resolve(strict=True)
    return json.loads(handoff_path.read_text("utf-8"))


def _bootstrap_addon_modules(data: Dict[str, object]):
    """
    Import internal add-on modules based on addon_dir in the handoff file.
    Returns a dict with required callables/values.
    """
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")

    # Make the add-on package importable for this subprocess
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    clear_console = worker_utils.clear_console
    shorten_path = worker_utils.shorten_path
    is_blend_saved = worker_utils.is_blend_saved
    requests_retry_session = worker_utils.requests_retry_session
    _build_base = worker_utils._build_base
    CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN

    # Set logger for this script
    _set_logger(worker_utils.logger)

    bat_utils = importlib.import_module(f"{pkg_name}.utils.bat_utils")
    pack_blend = bat_utils.pack_blend
    trace_dependencies = bat_utils.trace_dependencies
    compute_project_root = bat_utils.compute_project_root

    submit_logger = importlib.import_module(f"{pkg_name}.utils.submit_logger")
    create_logger = submit_logger.create_logger

    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone

    return {
        "pkg_name": pkg_name,
        "clear_console": clear_console,
        "shorten_path": shorten_path,
        "is_blend_saved": is_blend_saved,
        "requests_retry_session": requests_retry_session,
        "_build_base": _build_base,
        "CLOUDFLARE_R2_DOMAIN": CLOUDFLARE_R2_DOMAIN,
        "pack_blend": pack_blend,
        "trace_dependencies": trace_dependencies,
        "compute_project_root": compute_project_root,
        "create_logger": create_logger,
        "run_rclone": run_rclone,
        "ensure_rclone": ensure_rclone,
    }


# ─── main ────────────────────────────────────────────────────────
def main() -> None:
    t_start = time.perf_counter()

    # Load handoff + bootstrap the add-on environment (ONLY in worker mode)
    data = _load_handoff_from_argv(sys.argv)
    mods = _bootstrap_addon_modules(data)

    clear_console = mods["clear_console"]
    shorten_path = mods["shorten_path"]
    is_blend_saved = mods["is_blend_saved"]
    requests_retry_session = mods["requests_retry_session"]
    _build_base = mods["_build_base"]
    CLOUDFLARE_R2_DOMAIN = mods["CLOUDFLARE_R2_DOMAIN"]
    pack_blend = mods["pack_blend"]
    trace_dependencies = mods["trace_dependencies"]
    compute_project_root = mods["compute_project_root"]
    create_logger = mods["create_logger"]
    run_rclone = mods["run_rclone"]
    ensure_rclone = mods["ensure_rclone"]

    proj = data["project"]

    clear_console()

    # Create rich logger for beautiful output
    logger = create_logger(_LOG, input_fn=_safe_input)

    # Single resilient session for *all* HTTP traffic
    session = requests_retry_session()

    # Optional: check for addon update (non-blocking if fails)
    try:
        github_response = session.get(
            "https://api.github.com/repos/Superluminal-Studios/sulu-blender-addon/releases/latest"
        )
        if github_response.status_code == 200:
            latest_version = github_response.json().get("tag_name")
            if latest_version:
                latest_version = tuple(int(i) for i in latest_version.split("."))
                if latest_version > tuple(data["addon_version"]):
                    logger.version_update(
                        "https://superlumin.al/blender-addon",
                        [
                            "Download the latest addon zip from the link above.",
                            "Uninstall the current version in Blender.",
                            "Install the latest version in Blender.",
                            "Restart Blender.",
                        ],
                    )
                    answer = logger.prompt("Would you like to update now? (y/n) ", "n")
                    if answer.lower() == "y":
                        webbrowser.open("https://superlumin.al/blender-addon")
                        logger.fatal("Please complete the update and restart Blender.")
    except SystemExit:
        sys.exit(0)
    except Exception:
        logger.info("Skipped add-on update check (network not available or rate-limited). Continuing...")

    headers = {"Authorization": data["user_token"]}

    # Ensure rclone is present
    try:
        rclone_bin = ensure_rclone(logger=_LOG)
    except Exception as e:
        logger.fatal(f"Couldn't prepare the uploader (rclone): {e}")

    # Verify farm availability (nice error if org misconfigured)
    try:
        farm_status = session.get(
            f"{data['pocketbase_url']}/api/farm_status/{proj['organization_id']}",
            headers=headers,
            timeout=30,
        )
        if farm_status.status_code != 200:
            logger.error(f"Farm status check failed: {farm_status.json()}")
            logger.fatal(
                "Please verify that you are logged in and a project is selected. "
                "If the issue persists, try logging out and back in."
            )
    except SystemExit:
        raise
    except Exception as exc:
        logger.error(f"Farm status check failed: {exc}")
        logger.fatal(
            "Please verify that you are logged in and a project is selected. "
            "If the issue persists, try logging out and back in."
        )

    # Local paths / settings
    blend_path: str = data["blend_path"]

    use_project: bool = bool(data["use_project_upload"])
    automatic_project_path: bool = bool(data["automatic_project_path"])
    custom_project_path_str: str = data["custom_project_path"]
    job_id: str = data["job_id"]
    tmp_blend: str = data["temp_blend_path"]

    # Test mode flags (optional in handoff)
    test_mode: bool = bool(data.get("test_mode", False))
    no_submit: bool = bool(data.get("no_submit", False))

    zip_file = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist = Path(tempfile.gettempdir()) / f"{job_id}.txt"

    org_id = proj["organization_id"]
    project_sqid = proj["sqid"]
    project_name = proj["name"]

    # Wait until .blend is fully written
    is_blend_saved(blend_path)

    # ═══════════════════════════════════════════════════════════════════════════
    # STAGE 1: TRACING - Discover all dependencies
    # ═══════════════════════════════════════════════════════════════════════════
    logger.stage_header(
        1, "TRACING DEPENDENCIES",
        "Scanning blend file for external references",
        details=[
            f"Main file: {Path(blend_path).name}",
            "Scanning for dependencies...",
        ],
    )
    logger.trace_start(blend_path)

    # Pack assets
    if use_project:
        # 1. Trace dependencies with rich logger
        # raw_usages is passed to pack_blend to avoid redundant re-tracing
        dep_paths, missing_set, unreadable_dict, raw_usages = trace_dependencies(
            Path(blend_path), logger=logger
        )

        # 2. Compute project root BEFORE calling BAT
        custom_root = None
        if not automatic_project_path:
            if not custom_project_path_str or not str(custom_project_path_str).strip():
                logger.fatal(
                    "Custom Project Path is empty. Either enable Automatic Project Path or set a valid folder."
                )
            custom_root = Path(custom_project_path_str)

        project_root, same_drive_deps, cross_drive_deps = compute_project_root(
            Path(blend_path), dep_paths, custom_root
        )
        common_path = str(project_root).replace("\\", "/")

        # 3. Build warning text for issues (shown inside trace summary panel)
        missing_files_list = [str(p) for p in sorted(missing_set)]
        unreadable_files_list = [(str(p), err) for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))]
        has_issues = bool(cross_drive_deps or missing_files_list or unreadable_files_list)

        warning_text = None
        if has_issues:
            parts: List[str] = []
            if cross_drive_deps:
                parts.append(
                    f"{len(cross_drive_deps)} file(s) on a different drive (excluded from Project upload)"
                )
            if missing_files_list:
                parts.append(f"{len(missing_files_list)} missing file(s)")
            if unreadable_files_list:
                parts.append(f"{len(unreadable_files_list)} unreadable file(s)")

            # macOS permission help if relevant
            mac_extra = ""
            if _IS_MAC and unreadable_files_list:
                for p, err in unreadable_files_list:
                    low = err.lower()
                    if "permission" in low or "operation not permitted" in low or "not permitted" in low:
                        mac_extra = "\n" + _mac_permission_help(p, err)
                        break

            warning_text = (
                "\n".join(f"  - {p}" for p in parts)
                + "\nThis may cause missing textures or linked data on the farm."
                + mac_extra
            )

        # Show trace summary (with warnings inline)
        logger.trace_summary(
            total=len(dep_paths),
            missing=len(missing_set),
            unreadable=len(unreadable_dict),
            project_root=shorten_path(common_path),
            cross_drive=len(cross_drive_deps),
            warning_text=warning_text,
        )

        # TEST MODE: Show comprehensive info and exit early
        if test_mode:
            # Build by_ext counts
            by_ext: Dict[str, int] = {}
            total_size = 0
            for dep in dep_paths:
                ext = dep.suffix.lower() if dep.suffix else "(no ext)"
                by_ext[ext] = by_ext.get(ext, 0) + 1
                if dep.exists() and dep.is_file():
                    try:
                        total_size += dep.stat().st_size
                    except:
                        pass

            report, report_path = _generate_report(
                blend_path=blend_path,
                dep_paths=dep_paths,
                missing_set=missing_set,
                unreadable_dict=unreadable_dict,
                project_root=project_root,
                same_drive_deps=same_drive_deps,
                cross_drive_deps=cross_drive_deps,
                upload_type="PROJECT",
                addon_dir=str(data["addon_dir"]),
                mode="test",
            )
            logger.test_report(
                blend_path=blend_path,
                dep_count=len(dep_paths),
                project_root=str(project_root),
                same_drive=len(same_drive_deps),
                cross_drive=len(cross_drive_deps),
                by_ext=by_ext,
                total_size=total_size,
                missing=[str(p) for p in sorted(missing_set)],
                unreadable=[(str(p), err) for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))],
                cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
                upload_type="PROJECT",
                report_path=str(report_path) if report_path else None,
                shorten_fn=shorten_path,
            )
            _safe_input("\nPress ENTER to close this window...", "")
            sys.exit(0)

        # Prompt if there are issues
        if has_issues:
            answer = logger.prompt("Continue submission anyway? y/n: ", "y")
            if answer.lower() != "y":
                sys.exit(1)

        # ═══════════════════════════════════════════════════════════════════════
        # STAGE 2: PACKING - Build file manifest
        # ═══════════════════════════════════════════════════════════════════════
        # 5. Pack with correct project root (now BAT uses the computed root)
        # Pass raw_usages to avoid redundant trace.deps() call inside packer
        fmap, report = pack_blend(
            blend_path,
            target="",
            method="PROJECT",
            project_path=common_path,
            return_report=True,
            pre_traced_deps=raw_usages,
        )

        # 6. Build manifest from BAT's file_map (src paths)
        abs_blend = _norm_abs_for_detection(blend_path)
        rel_manifest: List[str] = []
        required_storage = 0

        total_files = len(fmap)
        logger.stage_header(
            2, "WRITING MANIFEST",
            "Building file manifest for incremental upload",
            details=[f"{total_files} files to process"],
        )
        logger.pack_start()

        ok_count = 0
        skip_count = 0
        pack_idx = 0
        for idx, (src_path, dst_path) in enumerate(fmap.items()):
            src_str = str(src_path).replace("\\", "/")

            # Skip the main blend file (uploaded separately)
            if _samepath(src_str, abs_blend):
                skip_count += 1
                continue

            # Probe readability and accumulate size
            ok, err = _probe_readable_file(src_str)
            if not ok:
                # Already warned about missing/unreadable in stage 1 - skip silently
                continue

            pack_idx += 1
            ok_count += 1
            size = 0
            try:
                size = os.path.getsize(src_str)
                required_storage += size
            except Exception:
                pass
            logger.pack_entry(pack_idx, src_str, size=size, status="ok")
            # Compute relative path from project root for manifest
            rel = _relpath_safe(src_str, common_path)
            rel = _s3key_clean(rel)
            if rel:
                rel_manifest.append(rel)

        # Include main blend in storage calculation
        try:
            required_storage += os.path.getsize(blend_path)
        except Exception:
            pass

        # Write manifest file
        with filelist.open("w", encoding="utf-8") as fp:
            for rel in rel_manifest:
                fp.write(f"{rel}\n")

        # Compute main blend's S3 key from project root
        blend_rel = _relpath_safe(abs_blend, common_path)
        main_blend_s3 = _nfc(_s3key_clean(blend_rel) or os.path.basename(abs_blend))

        logger.pack_end(
            ok_count=ok_count,
            total_size=required_storage,
            title="Manifest Complete",
        )

    else:  # ZIP mode
        # 1. Trace dependencies with rich logger
        # raw_usages is passed to pack_blend to avoid redundant re-tracing
        dep_paths, missing_set, unreadable_dict, raw_usages = trace_dependencies(
            Path(blend_path), logger=logger
        )

        # 2. Compute project root for cleaner zip structure
        project_root, same_drive_deps, cross_drive_deps = compute_project_root(Path(blend_path), dep_paths)
        project_root_str = str(project_root).replace("\\", "/")

        # Build warning text for issues
        missing_files_list = [str(p) for p in sorted(missing_set)]
        unreadable_files_list = [(str(p), err) for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))]
        has_zip_issues = bool(missing_files_list or unreadable_files_list)

        zip_warning_text = None
        if has_zip_issues:
            parts_z: List[str] = []
            if missing_files_list:
                parts_z.append(f"{len(missing_files_list)} missing file(s)")
            if unreadable_files_list:
                parts_z.append(f"{len(unreadable_files_list)} unreadable file(s)")
            zip_warning_text = (
                "\n".join(f"  - {p}" for p in parts_z)
                + "\nThe zip may be incomplete."
            )

        # Show trace summary (with warnings inline)
        logger.trace_summary(
            total=len(dep_paths),
            missing=len(missing_set),
            unreadable=len(unreadable_dict),
            project_root=shorten_path(project_root_str),
            cross_drive=len(cross_drive_deps),
            warning_text=zip_warning_text,
        )

        if has_zip_issues:
            answer = logger.prompt("Continue submission anyway? y/n: ", "y")
            if answer.lower() != "y":
                sys.exit(1)

        # TEST MODE: Show comprehensive info and exit early
        if test_mode:
            by_ext: Dict[str, int] = {}
            total_size = 0
            for dep in dep_paths:
                ext = dep.suffix.lower() if dep.suffix else "(no ext)"
                by_ext[ext] = by_ext.get(ext, 0) + 1
                if dep.exists() and dep.is_file():
                    try:
                        total_size += dep.stat().st_size
                    except:
                        pass

            report, report_path = _generate_report(
                blend_path=blend_path,
                dep_paths=dep_paths,
                missing_set=missing_set,
                unreadable_dict=unreadable_dict,
                project_root=project_root,
                same_drive_deps=same_drive_deps,
                cross_drive_deps=cross_drive_deps,
                upload_type="ZIP",
                addon_dir=str(data["addon_dir"]),
                mode="test",
            )
            logger.test_report(
                blend_path=blend_path,
                dep_count=len(dep_paths),
                project_root=str(project_root),
                same_drive=len(same_drive_deps),
                cross_drive=len(cross_drive_deps),
                by_ext=by_ext,
                total_size=total_size,
                missing=[str(p) for p in sorted(missing_set)],
                unreadable=[(str(p), err) for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))],
                cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
                upload_type="ZIP",
                report_path=str(report_path) if report_path else None,
                shorten_fn=shorten_path,
            )
            _safe_input("\nPress ENTER to close this window...", "")
            sys.exit(0)

        # ═══════════════════════════════════════════════════════════════════════
        # STAGE 2: PACKING (ZIP MODE)
        # ═══════════════════════════════════════════════════════════════════════
        logger.stage_header(
            2, "PACKING",
            "Creating compressed archive with all dependencies",
        )

        # 3. Pack with computed project root (not drive root)
        # Pass raw_usages to avoid redundant trace.deps() call inside packer
        abs_blend_norm = _norm_abs_for_detection(blend_path)

        # Track whether zip_start has been emitted (first entry triggers it)
        _zip_started = False

        def _on_zip_entry(idx, total, arcname, size, method):
            nonlocal _zip_started
            if not _zip_started:
                logger.zip_start(total, 0)
                _zip_started = True
            logger.zip_entry(idx, total, arcname, size, method)

        def _on_zip_done(zippath, total_files, total_bytes, elapsed):
            logger.zip_done(zippath, total_files, total_bytes, elapsed)

        # Suppress raw _emit output; use a no-op so BAT header/verbose lines
        # don't leak to stdout (our structured callbacks handle the UI).
        def _noop_emit(msg):
            pass

        zip_report = pack_blend(
            abs_blend_norm,
            str(zip_file),
            method="ZIP",
            project_path=project_root_str,
            return_report=True,
            pre_traced_deps=raw_usages,
            zip_emit_fn=_noop_emit,
            zip_entry_cb=_on_zip_entry,
            zip_done_cb=_on_zip_done,
        )

        if not zip_file.exists():
            logger.fatal("Zip file does not exist")

        required_storage = zip_file.stat().st_size
        rel_manifest = []
        common_path = ""
        main_blend_s3 = ""

    # NO_SUBMIT MODE: Skip upload and job registration
    if no_submit:
        zip_size = 0
        if not use_project and zip_file.exists():
            zip_size = zip_file.stat().st_size
        logger.no_submit_report(
            upload_type="PROJECT" if use_project else "ZIP",
            common_path=common_path if use_project else "",
            rel_manifest_count=len(rel_manifest) if use_project else 0,
            main_blend_s3=main_blend_s3 if use_project else "",
            zip_file=str(zip_file) if not use_project else "",
            zip_size=zip_size,
            required_storage=required_storage,
        )
        # Clean up temp zip if created
        if not use_project and zip_file.exists():
            try:
                zip_file.unlink()
                logger.info(f"Cleaned up temp zip: {zip_file}")
            except:
                pass
        _safe_input("\nPress ENTER to close this window...", "")
        sys.exit(0)

    # ═══════════════════════════════════════════════════════════════════════════
    # STAGE 3: UPLOADING - Transfer files to cloud storage
    # ═══════════════════════════════════════════════════════════════════════════
    logger.stage_header(3, "UPLOADING", "Transferring files to render farm storage")

    # R2 credentials
    logger.storage_connect("connecting")
    try:
        s3_response = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={"filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')"},
            timeout=30,
        )
        s3_response.raise_for_status()
        s3info = s3_response.json()["items"][0]
        bucket = s3info["bucket_name"]
        logger.storage_connect("connected")
    except Exception as exc:
        logger.fatal(f"Could not obtain storage credentials: {exc}")

    base_cmd = _build_base(rclone_bin, f"https://{CLOUDFLARE_R2_DOMAIN}", s3info)

    rclone_settings = [
                        "--transfers", "4",           # single file, no parallelism needed
                        "--checkers", "4",
                        "--s3-chunk-size", "64M",     # larger chunks = fewer requests
                        "--s3-upload-concurrency", "4",  # very conservative for cloud drives
                        "--buffer-size", "64M",       # smaller buffer - don't outpace source
                        "--retries", "20",
                        "--low-level-retries", "20",
                        "--retries-sleep", "5s",
                        "--timeout", "5m",            # longer timeout for slow cloud drives
                        "--stats", "0.1s"
                    ]

    # Calculate upload steps
    has_addons = data.get("packed_addons") and len(data["packed_addons"]) > 0

    try:
        if not use_project:
            # ZIP MODE UPLOAD
            total_steps = 2 if has_addons else 1
            step = 1
            logger.upload_start(total_steps)

            logger.upload_step(step, total_steps, "Uploading zip archive", f"{zip_file.name} ({_format_size(required_storage)})")
            run_rclone(base_cmd, "move", str(zip_file), f":s3:{bucket}/", rclone_settings)
            logger.upload_complete("Zip uploaded")
            step += 1

            if has_addons:
                logger.upload_step(step, total_steps, "Uploading add-ons", f"{len(data['packed_addons'])} add-on(s)")
                run_rclone(
                    base_cmd,
                    "moveto",
                    data["packed_addons_path"],
                    f":s3:{bucket}/{job_id}/addons/",
                    rclone_settings,
                )
                logger.upload_complete("Add-ons uploaded")

        else:
            # PROJECT MODE UPLOAD
            total_steps = 3 if rel_manifest else 2
            if has_addons:
                total_steps += 1
            step = 1
            logger.upload_start(total_steps)

            blend_size = 0
            try:
                blend_size = os.path.getsize(blend_path)
            except:
                pass
            logger.upload_step(step, total_steps, "Uploading main .blend", f"{Path(blend_path).name} ({_format_size(blend_size)})")
            move_to_path = _nfc(_s3key_clean(f"{project_name}/{main_blend_s3}"))
            remote_main = f":s3:{bucket}/{move_to_path}"
            run_rclone(base_cmd, "copyto", blend_path, remote_main, rclone_settings)
            logger.upload_complete("Main .blend uploaded")
            step += 1

            if rel_manifest:
                logger.upload_step(step, total_steps, "Uploading dependencies", f"{len(rel_manifest)} file(s)")
                dependency_rclone_settings = ["--files-from", str(filelist)]
                dependency_rclone_settings.extend(rclone_settings)
                run_rclone(
                    base_cmd,
                    "copy",
                    str(common_path),
                    f":s3:{bucket}/{project_name}/",
                    dependency_rclone_settings,
                )
                logger.upload_complete("Dependencies uploaded")
                step += 1

            with filelist.open("a", encoding="utf-8") as fp:
                fp.write(_nfc(_s3key_clean(main_blend_s3)) + "\n")

            logger.upload_step(step, total_steps, "Uploading manifest", filelist.name)
            run_rclone(
                base_cmd,
                "move",
                str(filelist),
                f":s3:{bucket}/{project_name}/",
                rclone_settings,
            )
            logger.upload_complete("Manifest uploaded")
            step += 1

            if has_addons:
                logger.upload_step(step, total_steps, "Uploading add-ons", f"{len(data['packed_addons'])} add-on(s)")
                run_rclone(
                    base_cmd,
                    "moveto",
                    data["packed_addons_path"],
                    f":s3:{bucket}/{job_id}/addons/",
                    rclone_settings,
                )
                logger.upload_complete("Add-ons uploaded")

    except RuntimeError as exc:
        logger.fatal(f"Upload failed: {exc}")

    finally:
        try:
            if "packed_addons_path" in data and data["packed_addons_path"]:
                shutil.rmtree(data["packed_addons_path"], ignore_errors=True)
        except Exception:
            pass

    use_scene_image_format = bool(data.get("use_scene_image_format")) or (
        str(data.get("image_format", "")).upper() == "SCENE"
    )
    frame_step_val = int(data.get("frame_stepping_size", 1))

    payload: Dict[str, object] = {
        "job_data": {
            "id": data["job_id"],
            "project_id": data["project"]["id"],
            "packed_addons": data["packed_addons"],
            "organization_id": org_id,
            "main_file": _nfc(str(Path(blend_path).relative_to(project_root_str)).replace("\\", "/")) if not use_project else _nfc(_s3key_clean(main_blend_s3)),
            "project_path": project_name,
            "name": data["job_name"],
            "status": "queued",
            "start": data["start_frame"],
            "end": data["end_frame"],
            "frame_step": frame_step_val,
            "batch_size": 1,
            "image_format": data["image_format"],
            "use_scene_image_format": use_scene_image_format,
            "render_engine": data["render_engine"],
            "version": "20241125",
            "blender_version": data["blender_version"],
            "required_storage": required_storage,
            "zip": not use_project,
            "ignore_errors": data["ignore_errors"],
            "use_bserver": data["use_bserver"],
            "use_async_upload": data["use_async_upload"],
            "defer_status": data["use_async_upload"],
            "farm_url": data["farm_url"],
            "tasks": list(range(data["start_frame"], data["end_frame"] + 1, frame_step_val)),
        }
    }

    try:
        post_resp = session.post(
            f"{data['pocketbase_url']}/api/farm/{org_id}/jobs",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        post_resp.raise_for_status()
    except requests.RequestException as exc:
        logger.fatal(f"Job registration failed: {exc}")

    elapsed = time.perf_counter() - t_start
    logger.log("")
    logger.success(f"Job submitted successfully! Total time: {elapsed:.1f}s")

    try:
        # Best effort: remove the handoff file (only in worker mode)
        handoff_path = Path(sys.argv[1]).resolve()
        handoff_path.unlink(missing_ok=True)
    except Exception:
        pass

    selection = logger.prompt("\nOpen job in your browser? y/n, or just press ENTER to close...", "n")
    if selection.lower() == "y":
        web_url = f"https://superlumin.al/p/{project_sqid}/farm/jobs/{data['job_id']}"
        webbrowser.open(web_url)
        logger.job_complete(web_url)
        _safe_input("\nPress ENTER to close this window...", "")
        sys.exit(1)


# ─── entry ───────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        # Logger may not be initialized yet, fall back to print
        print(
            f"\n{exc}\n"
            "Tip: try switching to Zip upload or choose a higher level Project Path, then submit again."
        )
        try:
            _safe_input("\nPress ENTER to close this window...", "")
        except Exception:
            pass
        sys.exit(1)
