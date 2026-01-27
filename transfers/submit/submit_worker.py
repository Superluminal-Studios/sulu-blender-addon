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

TUI Mode:
- Set USE_TUI=1 environment variable or add --tui flag to enable beautiful TUI
- The TUI shows real-time progress for tracing, packing, and uploading
- Falls back to plain text in non-interactive terminals
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
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import webbrowser

import requests

# ─── TUI mode detection ──────────────────────────────────────────
# TUI is ON by default. Disable with: NO_TUI=1 env var, or --no-tui flag
_TUI_DISABLED = (
    os.environ.get("NO_TUI", "").lower() in ("1", "true", "yes")
    or "--no-tui" in sys.argv
)
_TUI_ENABLED = not _TUI_DISABLED
_TUI_INSTANCE: Any = None  # Will hold SubmitTUI instance when enabled


# ─── Lightweight logger fallback ──────────────────────────────────
# This gets replaced after bootstrap when worker_utils.logger is available.
def _default_logger(msg: str) -> None:
    print(str(msg))


_LOG = _default_logger


def _set_logger(fn) -> None:
    global _LOG
    _LOG = fn if callable(fn) else _default_logger


def warn(
    message: str,
    emoji: str = "x",
    close_window: bool = True,
    new_line: bool = False,
) -> None:
    emojis = {
        "x": "❌",  # error / stop
        "w": "⚠️",  # warning
        "c": "✅",  # success/ok
        "i": "ℹ️",  # info
    }
    new_line_str = "\n" if new_line else ""
    _LOG(f"{new_line_str}{emojis.get(emoji, '❌')}  {message}")
    if close_window:
        try:
            input("\nPress ENTER to close this window…")
        except Exception:
            pass
        sys.exit(1)


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
        "  • System Settings → Privacy & Security → Full Disk Access",
        "  • Enable the app running this upload (Terminal/iTerm if you see this console; otherwise Blender).",
    ]
    if _looks_like_cloud_storage_path(path):
        lines += [
            "",
            "Cloud storage note:",
            "  • This file is in a cloud-synced folder.",
            "  • Make sure it’s downloaded / available offline, then retry.",
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


def _print_missing_unreadable_summary(
    missing: List[str],
    unreadable: List[Tuple[str, str]],
    *,
    header: str = "Dependency check",
) -> None:
    if not missing and not unreadable:
        return

    _LOG(f"\n⚠️  {header}: issues detected\n")

    if missing:
        _LOG(f"⚠️  Missing files: {len(missing)}")
        for p in missing[:25]:
            _LOG(f"    - {p}")
        if len(missing) > 25:
            _LOG(f"    ... (+{len(missing) - 25} more)")

    if unreadable:
        _LOG(f"\n❌  Unreadable files: {len(unreadable)}")
        for p, err in unreadable[:25]:
            _LOG(f"    - {p}")
            _LOG(f"      {err}")
        if len(unreadable) > 25:
            _LOG(f"    ... (+{len(unreadable) - 25} more)")

        # macOS help block once
        if _IS_MAC:
            # If *any* unreadable looks like permission, show help.
            for p, err in unreadable:
                low = err.lower()
                if (
                    "permission" in low
                    or "operation not permitted" in low
                    or "not permitted" in low
                ):
                    _LOG("\n" + _mac_permission_help(p, err) + "\n")
                    break


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


def _run_test_mode(
    blend_path: str,
    dep_paths: List[Path],
    missing_set: set,
    unreadable_dict: dict,
    project_root: Path,
    same_drive_deps: List[Path],
    cross_drive_deps: List[Path],
    upload_type: str,
    shorten_path_fn,
    addon_dir: Optional[str] = None,
) -> None:
    """
    Run in test mode: display comprehensive dependency information without submitting.
    Also generates a diagnostic report.
    """
    _LOG("\n" + "=" * 70)
    _LOG(f"  SUBMISSION TEST MODE - {upload_type}")
    _LOG("=" * 70)

    _LOG(f"\n[1/6] Blend file: {blend_path}")
    try:
        _LOG(f"      Size: {_format_size(os.path.getsize(blend_path))}")
    except:
        pass

    _LOG(f"\n[2/6] Dependencies traced: {len(dep_paths)}")

    _LOG(f"\n[3/6] Project root: {project_root}")
    _LOG(f"      Same-drive deps: {len(same_drive_deps)}")
    _LOG(f"      Cross-drive deps: {len(cross_drive_deps)}")

    # Classify by extension
    by_ext: Dict[str, List[Path]] = {}
    total_size = 0
    for dep in dep_paths:
        ext = dep.suffix.lower() if dep.suffix else "(no ext)"
        by_ext.setdefault(ext, []).append(dep)
        if dep.exists() and dep.is_file():
            try:
                total_size += dep.stat().st_size
            except:
                pass

    _LOG(f"\n[4/6] Dependency breakdown:")
    _LOG(f"      By extension:")
    for ext, paths in sorted(by_ext.items(), key=lambda x: -len(x[1])):
        _LOG(f"        {ext:12} : {len(paths):4} files")
    _LOG(f"\n      Total size: {_format_size(total_size)}")

    # Issues
    _LOG(f"\n[5/6] Issues:")

    if missing_set:
        _LOG(f"\n      MISSING ({len(missing_set)}):")
        for p in sorted(missing_set)[:15]:
            _LOG(f"        - {shorten_path_fn(str(p))}")
        if len(missing_set) > 15:
            _LOG(f"        ... and {len(missing_set) - 15} more")
    else:
        _LOG(f"      No missing files")

    if unreadable_dict:
        _LOG(f"\n      UNREADABLE ({len(unreadable_dict)}):")
        for p, err in sorted(unreadable_dict.items())[:10]:
            _LOG(f"        - {shorten_path_fn(str(p))}")
            _LOG(f"          {err}")
        if len(unreadable_dict) > 10:
            _LOG(f"        ... and {len(unreadable_dict) - 10} more")
    else:
        _LOG(f"      No unreadable files")

    if cross_drive_deps:
        _LOG(f"\n      CROSS-DRIVE ({len(cross_drive_deps)}):")
        for p in cross_drive_deps[:15]:
            _LOG(f"        - {shorten_path_fn(str(p))}")
        if len(cross_drive_deps) > 15:
            _LOG(f"        ... and {len(cross_drive_deps) - 15} more")
    else:
        _LOG(f"      No cross-drive files")

    # Generate report
    _LOG(f"\n[6/6] Generating report...")
    report, report_path = _generate_report(
        blend_path=blend_path,
        dep_paths=dep_paths,
        missing_set=missing_set,
        unreadable_dict=unreadable_dict,
        project_root=project_root,
        same_drive_deps=same_drive_deps,
        cross_drive_deps=cross_drive_deps,
        upload_type=upload_type,
        addon_dir=addon_dir,
        mode="test",
    )

    if report_path:
        _LOG(f"      Report saved: {report_path}")
    else:
        _LOG(f"      Report could not be saved to file")

    # Summary
    _LOG("\n" + "=" * 70)
    _LOG("  SUMMARY")
    _LOG("=" * 70)

    issues = len(missing_set) + len(unreadable_dict) + len(cross_drive_deps)
    if issues == 0:
        _LOG("\n  [OK] No issues detected. Ready for submission.")
    else:
        _LOG(f"\n  [INFO] {issues} issue(s) to review:")
        if missing_set:
            _LOG(f"    - {len(missing_set)} missing file(s)")
        if unreadable_dict:
            _LOG(f"    - {len(unreadable_dict)} unreadable file(s)")
        if cross_drive_deps and upload_type == "PROJECT":
            _LOG(
                f"    - {len(cross_drive_deps)} cross-drive file(s) (excluded in PROJECT mode)"
            )

    _LOG("\n  [TEST MODE] No actual submission performed.")
    if report_path:
        _LOG(f"  [REPORT] Full details saved to: {report_path}")
    _LOG("=" * 70 + "\n")


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
    global _TUI_INSTANCE

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

    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone

    # TUI modules (optional)
    tui_module = None
    tui_trace_module = None
    tui_rclone_module = None

    if _TUI_ENABLED:
        try:
            tui_module = importlib.import_module(f"{pkg_name}.utils.submit_tui")
            tui_trace_module = importlib.import_module(f"{pkg_name}.utils.tui_trace")
            tui_rclone_module = importlib.import_module(f"{pkg_name}.utils.tui_rclone")
        except ImportError as e:
            _LOG(f"TUI modules not available: {e}")

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
        "run_rclone": run_rclone,
        "ensure_rclone": ensure_rclone,
        # TUI modules
        "tui_module": tui_module,
        "tui_trace_module": tui_trace_module,
        "tui_rclone_module": tui_rclone_module,
    }


# ─── main ────────────────────────────────────────────────────────
def main() -> None:
    global _TUI_INSTANCE
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
    run_rclone = mods["run_rclone"]
    ensure_rclone = mods["ensure_rclone"]

    # TUI setup
    tui_module = mods.get("tui_module")
    tui_trace_module = mods.get("tui_trace_module")
    tui_rclone_module = mods.get("tui_rclone_module")

    proj = data["project"]
    use_project: bool = bool(data["use_project_upload"])

    # Initialize TUI if available
    # Force TUI mode since we're running in a dedicated terminal window
    has_packed_addons = bool(data.get("packed_addons") and len(data["packed_addons"]) > 0)

    if _TUI_ENABLED and tui_module:
        try:
            _TUI_INSTANCE = tui_module.SubmitTUI(
                blend_name=Path(data["blend_path"]).name,
                project_name=proj["name"],
                upload_type="PROJECT" if use_project else "ZIP",
                force_tui=True,  # Force since terminal launched from Blender
                include_addons=has_packed_addons,
            )
            _TUI_INSTANCE.start()
        except Exception as e:
            _LOG(f"TUI initialization failed: {e}")
            import traceback

            traceback.print_exc()
            _TUI_INSTANCE = None

    # Override trace_dependencies if TUI is active
    if _TUI_INSTANCE and tui_trace_module:
        _original_trace = trace_dependencies

        def trace_dependencies(blend_path):
            return tui_trace_module.trace_dependencies_with_tui(
                blend_path, _TUI_INSTANCE
            )

    # Override run_rclone if TUI is active
    if _TUI_INSTANCE and tui_rclone_module:
        run_rclone = tui_rclone_module.create_rclone_runner(_TUI_INSTANCE)

    # clear_console()

    # Single resilient session for *all* HTTP traffic
    session = requests_retry_session()

    # Optional: check for addon update (non-blocking if fails)
    try:
        github_response = session.get(
            "https://api.github.com/repos/Superluminal-Studios/sulu-blender-addon/releases/latest"
        )
        if github_response.status_code == 200:
            latest_version_str = github_response.json().get("tag_name", "")
            if latest_version_str:
                latest_version = tuple(int(i) for i in latest_version_str.split("."))
                current_version = tuple(data["addon_version"])
                if latest_version > current_version:
                    current_str = ".".join(str(x) for x in current_version)
                    latest_str = ".".join(str(x) for x in latest_version)

                    if _TUI_INSTANCE:
                        # Use beautiful TUI dialog (waits for single keypress)
                        key = _TUI_INSTANCE.show_update_dialog(current_str, latest_str)

                        if key == "ESC":
                            _LOG("Cancelled.")
                            sys.exit(0)
                        elif key == "y":
                            webbrowser.open("https://superlumin.al/blender-addon")
                            _TUI_INSTANCE.show_question(
                                title="Update Instructions",
                                text="Opening download page...\n\n"
                                     "  1. Download the latest addon zip\n"
                                     "  2. Uninstall current version in Blender\n"
                                     "  3. Install the new version\n"
                                     "  4. Restart Blender",
                                options=["Close"],
                                hotkeys=["y", "n"],
                            )
                            _TUI_INSTANCE.wait_for_key(["y", "n"])
                            sys.exit(0)
                        # User chose Skip (n) - continue
                    else:
                        # Fallback to simple prompt
                        answer = input(
                            f"Update available: v{latest_str} (you have v{current_str}). Update [y] Skip [n]: "
                        ).strip().lower()
                        if answer in ("y", "yes"):
                            webbrowser.open("https://superlumin.al/blender-addon")
                            print("\nhttps://superlumin.al/blender-addon")
                            warn(
                                "To update:\n"
                                "  • Download the latest addon zip from the link above.\n"
                                "  • Uninstall the current version in Blender.\n"
                                "  • Install the latest version in Blender.\n"
                                "  • Close this window and restart Blender.",
                                emoji="i",
                                close_window=True,
                                new_line=True,
                            )
    except SystemExit:
        sys.exit(0)
    except Exception:
        _LOG(
            "ℹ️  Skipped add-on update check (network not available or rate-limited). Continuing..."
        )

    headers = {"Authorization": data["user_token"]}

    # Ensure rclone is present
    try:
        rclone_bin = ensure_rclone(logger=_LOG)
    except Exception as e:
        warn(
            f"Couldn't prepare the uploader (rclone): {e}", emoji="x", close_window=True
        )

    # Verify farm availability (nice error if org misconfigured)
    try:
        farm_status = session.get(
            f"{data['pocketbase_url']}/api/farm_status/{proj['organization_id']}",
            headers=headers,
            timeout=30,
        )
        if farm_status.status_code != 200:
            warn(
                f"Farm status check failed: {farm_status.json()}",
                emoji="x",
                close_window=False,
            )
            warn(
                "Please verify that you are logged in and a project is selected. "
                "If the issue persists, try logging out and back in.",
                emoji="w",
                close_window=True,
            )
    except Exception as exc:
        warn(f"Farm status check failed: {exc}", emoji="x", close_window=False)
        warn(
            "Please verify that you are logged in and a project is selected. "
            "If the issue persists, try logging out and back in.",
            emoji="w",
            close_window=True,
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

    # Pack assets
    if use_project:
        if not _TUI_INSTANCE:
            _LOG("🔍  Scanning project files, this can take a while…\n")

        # 1. Trace dependencies (lightweight, before BAT packing)
        # Note: If TUI is enabled, trace_dependencies was overridden above
        dep_paths, missing_set, unreadable_dict = trace_dependencies(Path(blend_path))

        # 2. Compute project root BEFORE calling BAT
        custom_root = None
        if not automatic_project_path:
            if not custom_project_path_str or not str(custom_project_path_str).strip():
                warn(
                    "Custom Project Path is empty. Either enable Automatic Project Path or set a valid folder.",
                    emoji="w",
                    close_window=True,
                )
            custom_root = Path(custom_project_path_str)

        project_root, same_drive_deps, cross_drive_deps = compute_project_root(
            Path(blend_path), dep_paths, custom_root
        )
        common_path = str(project_root).replace("\\", "/")
        _LOG(f"ℹ️  Using project root: {shorten_path(common_path)}")

        # TEST MODE: Show comprehensive info and exit early
        if test_mode:
            _run_test_mode(
                blend_path=blend_path,
                dep_paths=dep_paths,
                missing_set=missing_set,
                unreadable_dict=unreadable_dict,
                project_root=project_root,
                same_drive_deps=same_drive_deps,
                cross_drive_deps=cross_drive_deps,
                upload_type="PROJECT",
                shorten_path_fn=shorten_path,
                addon_dir=str(data["addon_dir"]),
            )
            input("\nPress ENTER to close this window...")
            sys.exit(0)

        # 3. Warn about cross-drive dependencies
        if cross_drive_deps:
            if _TUI_INSTANCE:
                _TUI_INSTANCE.add_warning(
                    f"{len(cross_drive_deps)} file(s) on different drive (excluded)"
                )
                _TUI_INSTANCE.stop()  # Pause TUI for user input

            warn(
                f"{len(cross_drive_deps)} file(s) are on a different drive/root. "
                "They will be excluded from Project upload. Consider Zip upload.",
                emoji="w",
                close_window=False,
                new_line=True,
            )
            warn(
                "Would you like to continue submission?", emoji="w", close_window=False
            )
            answer = input("y/n: ")
            if answer.lower() != "y":
                sys.exit(1)

            if _TUI_INSTANCE:
                _TUI_INSTANCE.start()  # Resume TUI

        # 4. Warn about missing/unreadable
        missing_files_list = [str(p) for p in sorted(missing_set)]
        unreadable_files_list = [
            (str(p), err)
            for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))
        ]

        if _TUI_INSTANCE:
            if missing_files_list:
                _TUI_INSTANCE.add_warning(f"{len(missing_files_list)} missing file(s)")
            if unreadable_files_list:
                _TUI_INSTANCE.add_warning(
                    f"{len(unreadable_files_list)} unreadable file(s)"
                )
            if missing_files_list or unreadable_files_list:
                _TUI_INSTANCE.stop()  # Pause TUI for user input

        _print_missing_unreadable_summary(
            missing_files_list,
            unreadable_files_list,
            header="Project upload dependency check",
        )
        if missing_files_list or unreadable_files_list:
            warn(
                "Some dependencies are missing or unreadable. This can cause missing textures/linked data on the farm.",
                emoji="w",
                close_window=False,
            )
            warn("Continue submission anyway?", emoji="w", close_window=False)
            answer = input("y/n: ")
            if answer.lower() != "y":
                sys.exit(1)

            if _TUI_INSTANCE:
                _TUI_INSTANCE.start()  # Resume TUI

        # 5. Pack with correct project root (now BAT uses the computed root)
        if _TUI_INSTANCE:
            _TUI_INSTANCE.set_phase("pack")
            _TUI_INSTANCE.pack_start(total_files=len(dep_paths), mode="PROJECT")

        fmap, report = pack_blend(
            blend_path,
            target="",
            method="PROJECT",
            project_path=common_path,
            return_report=True,
        )

        if _TUI_INSTANCE:
            _TUI_INSTANCE.pack_done()

        # 6. Build manifest from BAT's file_map directly
        abs_blend = _norm_abs_for_detection(blend_path)
        rel_manifest: List[str] = []
        required_storage = 0

        # Iterate over file_map entries: src_path -> packed_path (relative to target)
        total_files = len(fmap)
        for idx, (src_path, dst_path) in enumerate(fmap.items()):
            src_str = str(src_path).replace("\\", "/")
            dst_str = str(dst_path).replace("\\", "/")

            # Skip the main blend file (uploaded separately)
            if _samepath(src_str, abs_blend):
                # Capture main blend's relative path for upload
                blend_rel = dst_str
                continue

            # Probe readability and accumulate size
            ok, err = _probe_readable_file(src_str)
            if ok:
                if not _TUI_INSTANCE:
                    _LOG(f"✅  [{idx + 1}/{total_files}] {shorten_path(src_str)}")
                try:
                    file_size = os.path.getsize(src_str)
                    required_storage += file_size
                    if _TUI_INSTANCE:
                        _TUI_INSTANCE.pack_file(src_str, file_size)
                except Exception:
                    if _TUI_INSTANCE:
                        _TUI_INSTANCE.pack_file(src_str, 0)
                # Use BAT's computed destination path for manifest
                rel = _s3key_clean(dst_str)
                if rel:
                    rel_manifest.append(rel)
            else:
                if err == "missing":
                    if not _TUI_INSTANCE:
                        _LOG(
                            f"⚠️  [{idx + 1}/{total_files}] {shorten_path(src_str)} — not found"
                        )
                    else:
                        _TUI_INSTANCE.pack_missing(src_str)
                else:
                    if not _TUI_INSTANCE:
                        _LOG(
                            f"❌  [{idx + 1}/{total_files}] {shorten_path(src_str)} — unreadable"
                        )
                    else:
                        _TUI_INSTANCE.pack_unreadable(src_str, err or "unreadable")

        # Include main blend in storage calculation
        try:
            required_storage += os.path.getsize(blend_path)
        except Exception:
            pass

        # Write manifest file
        with filelist.open("w", encoding="utf-8") as fp:
            for rel in rel_manifest:
                fp.write(f"{rel}\n")

        # Compute main blend's S3 key from BAT's file_map or fallback
        blend_rel = _relpath_safe(abs_blend, common_path)
        main_blend_s3 = _s3key_clean(blend_rel) or os.path.basename(abs_blend)

        if not _TUI_INSTANCE:
            _LOG(
                f"\n📄  [Summary] to upload: {len(rel_manifest)} dependencies (+ main .blend), "
                f"excluded (other drives): {len(cross_drive_deps)}, missing on disk: {len(missing_files_list)}, unreadable: {len(unreadable_files_list)}"
            )

    else:  # ZIP mode
        if not _TUI_INSTANCE:
            _LOG(
                "📦  Creating a single zip with all dependencies, this can take a while…"
            )

        # 1. Trace dependencies (lightweight, before BAT packing)
        # Note: If TUI is enabled, trace_dependencies was overridden above
        dep_paths, missing_set, unreadable_dict = trace_dependencies(Path(blend_path))

        # 2. Compute project root for cleaner zip structure
        project_root, same_drive_deps, cross_drive_deps = compute_project_root(
            Path(blend_path), dep_paths
        )
        project_root_str = str(project_root).replace("\\", "/")
        _LOG(f"ℹ️  Using project root for zip: {shorten_path(project_root_str)}")

        # TEST MODE: Show comprehensive info and exit early
        if test_mode:
            _run_test_mode(
                blend_path=blend_path,
                dep_paths=dep_paths,
                missing_set=missing_set,
                unreadable_dict=unreadable_dict,
                project_root=project_root,
                same_drive_deps=same_drive_deps,
                cross_drive_deps=cross_drive_deps,
                upload_type="ZIP",
                shorten_path_fn=shorten_path,
                addon_dir=str(data["addon_dir"]),
            )
            input("\nPress ENTER to close this window...")
            sys.exit(0)

        # 3. Pack with computed project root (not drive root)
        if _TUI_INSTANCE:
            _TUI_INSTANCE.set_phase("pack")
            _TUI_INSTANCE.pack_start(total_files=len(dep_paths), mode="ZIP")

        abs_blend_norm = _norm_abs_for_detection(blend_path)
        zip_report = pack_blend(
            abs_blend_norm,
            str(zip_file),
            method="ZIP",
            project_path=project_root_str,
            return_report=True,
        )

        if _TUI_INSTANCE:
            _TUI_INSTANCE.pack_done()

        if not zip_file.exists():
            warn("Zip file does not exist", emoji="x", close_window=True)

        # Report issues from packer
        missing = []
        unreadable = []
        if isinstance(zip_report, dict):
            missing = list(zip_report.get("missing_files") or [])
            u = zip_report.get("unreadable_files") or {}
            if isinstance(u, dict):
                unreadable = [(k, str(v)) for k, v in u.items()]

        if _TUI_INSTANCE:
            if missing:
                _TUI_INSTANCE.add_warning(f"{len(missing)} missing file(s)")
            if unreadable:
                _TUI_INSTANCE.add_warning(f"{len(unreadable)} unreadable file(s)")
            if missing or unreadable:
                _TUI_INSTANCE.stop()  # Pause TUI for user input

        _print_missing_unreadable_summary(
            missing,
            unreadable,
            header="Zip pack dependency check",
        )

        if missing or unreadable:
            warn(
                "Some files were missing or unreadable during packing. The zip may be incomplete.",
                emoji="w",
                close_window=False,
            )
            warn("Continue submission anyway?", emoji="w", close_window=False)
            answer = input("y/n: ")
            if answer.lower() != "y":
                sys.exit(1)

            if _TUI_INSTANCE:
                _TUI_INSTANCE.start()  # Resume TUI

        required_storage = zip_file.stat().st_size
        rel_manifest = []
        common_path = ""
        main_blend_s3 = ""
        _LOG(f"ℹ️  Zip size estimate: {required_storage / 1_048_576:.1f} MiB")

    # NO_SUBMIT MODE: Skip upload and job registration
    if no_submit:
        _LOG("\n" + "=" * 70)
        _LOG("  NO-SUBMIT MODE")
        _LOG("=" * 70)
        _LOG("\n  Packing completed successfully.")
        _LOG(f"  Upload type: {'PROJECT' if use_project else 'ZIP'}")
        if use_project:
            _LOG(f"  Project root: {common_path}")
            _LOG(f"  Dependencies: {len(rel_manifest)}")
            _LOG(f"  Main blend S3 key: {main_blend_s3}")
        else:
            _LOG(f"  Zip file: {zip_file}")
            if zip_file.exists():
                _LOG(f"  Zip size: {_format_size(zip_file.stat().st_size)}")
        _LOG(f"\n  Storage estimate: {_format_size(required_storage)}")
        _LOG("\n  [NO-SUBMIT] Skipping upload and job registration.")
        _LOG("=" * 70)
        # Clean up temp zip if created
        if not use_project and zip_file.exists():
            try:
                zip_file.unlink()
                _LOG(f"\n  Cleaned up temp zip: {zip_file}")
            except:
                pass
        input("\nPress ENTER to close this window...")
        sys.exit(0)

    # R2 credentials
    _LOG("\n🔑  Fetching temporary storage credentials...")
    try:
        s3_response = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={
                "filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')"
            },
            timeout=30,
        )
        s3_response.raise_for_status()
        s3info = s3_response.json()["items"][0]
        bucket = s3info["bucket_name"]
    except Exception as exc:
        warn(
            f"Could not obtain storage credentials: {exc}", emoji="x", close_window=True
        )

    base_cmd = _build_base(rclone_bin, f"https://{CLOUDFLARE_R2_DOMAIN}", s3info)

    if _TUI_INSTANCE:
        _TUI_INSTANCE.set_phase("upload")
    else:
        _LOG("🚀  Uploading\n")

    try:
        if not use_project:
            run_rclone(
                base_cmd,
                "move",
                str(zip_file),
                f":s3:{bucket}/",
                [
                    "--transfers",
                    "32",
                    "--checkers",
                    "32",
                    "--s3-chunk-size",
                    "50M",
                    "--s3-upload-concurrency",
                    "32",
                    "--buffer-size",
                    "64M",
                    "--multi-thread-streams",
                    "8",
                    "--fast-list",
                    "--retries",
                    "10",
                    "--low-level-retries",
                    "50",
                    "--retries-sleep",
                    "2s",
                    "--stats",
                    "0.1s",
                ],
            )
        else:
            if not _TUI_INSTANCE:
                _LOG("📤  Uploading the main .blend\n")
            move_to_path = _s3key_clean(f"{project_name}/{main_blend_s3}")
            remote_main = f":s3:{bucket}/{move_to_path}"
            run_rclone(
                base_cmd,
                "copyto",
                blend_path,
                remote_main,
                [
                    "--transfers",
                    "32",
                    "--checkers",
                    "32",
                    "--s3-chunk-size",
                    "50M",
                    "--s3-upload-concurrency",
                    "32",
                    "--buffer-size",
                    "64M",
                    "--multi-thread-streams",
                    "8",
                    "--fast-list",
                    "--retries",
                    "10",
                    "--low-level-retries",
                    "50",
                    "--retries-sleep",
                    "2s",
                    "--stats",
                    "0.1s",
                ],
            )

            if rel_manifest:
                if not _TUI_INSTANCE:
                    _LOG("📤  Uploading dependencies\n")
                run_rclone(
                    base_cmd,
                    "copy",
                    str(common_path),
                    f":s3:{bucket}/{project_name}/",
                    ["--files-from", str(filelist), "--checksum", "--stats", "0.1s"],
                )

            with filelist.open("a", encoding="utf-8") as fp:
                fp.write(_s3key_clean(main_blend_s3) + "\n")

            if not _TUI_INSTANCE:
                _LOG("📤  Uploading dependency manifest\n")
            run_rclone(
                base_cmd,
                "move",
                str(filelist),
                f":s3:{bucket}/{project_name}/",
                ["--checksum", "--stats", "0.1s"],
            )

        if data.get("packed_addons") and len(data["packed_addons"]) > 0:
            if not _TUI_INSTANCE:
                _LOG("📤  Uploading packed add-ons")
            run_rclone(
                base_cmd,
                "moveto",
                data["packed_addons_path"],
                f":s3:{bucket}/{job_id}/addons/",
                [
                    "--transfers",
                    "32",
                    "--checkers",
                    "32",
                    "--s3-chunk-size",
                    "50M",
                    "--s3-upload-concurrency",
                    "32",
                    "--buffer-size",
                    "64M",
                    "--multi-thread-streams",
                    "8",
                    "--fast-list",
                    "--retries",
                    "10",
                    "--low-level-retries",
                    "50",
                    "--retries-sleep",
                    "2s",
                    "--stats",
                    "0.1s",
                ],
            )

    except RuntimeError as exc:
        if _TUI_INSTANCE:
            _TUI_INSTANCE.finish(success=False, message=f"Upload failed: {exc}")
        warn(f"Upload failed: {exc}", emoji="x", close_window=True)

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
            "main_file": (
                str(Path(blend_path).relative_to(project_root_str)).replace("\\", "/")
                if not use_project
                else _s3key_clean(main_blend_s3)
            ),
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
            "tasks": list(
                range(data["start_frame"], data["end_frame"] + 1, frame_step_val)
            ),
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
        warn(f"Job registration failed: {exc}", emoji="x", close_window=True)

    elapsed = time.perf_counter() - t_start

    if _TUI_INSTANCE:
        _TUI_INSTANCE.upload_done()

    try:
        # Best effort: remove the handoff file (only in worker mode)
        handoff_path = Path(sys.argv[1]).resolve()
        handoff_path.unlink(missing_ok=True)
    except Exception:
        pass

    web_url = f"https://superlumin.al/p/{project_sqid}/farm/jobs/{data['job_id']}"

    if _TUI_INSTANCE:
        # Show browser prompt inline with success panel (keeps all panels visible)
        key = _TUI_INSTANCE.show_browser_prompt(
            job_name=data["job_name"],
            elapsed=elapsed,
        )

        if key == "y":
            webbrowser.open(web_url)
            _TUI_INSTANCE.finish(success=True, message=f"Opened {web_url}")
        else:
            _TUI_INSTANCE.finish(success=True, message=f"Job submitted in {elapsed:.1f}s")
    else:
        _LOG(f"✅  Job submitted successfully. Total time: {elapsed:.1f}s")
        selection = input("\nOpen in browser? [y/n]: ").strip().lower()
        if selection in ("y", "yes"):
            webbrowser.open(web_url)
            _LOG(f"🌐  Opened {web_url}")


# ─── entry ───────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback

        traceback.print_exc()

        # Stop TUI if running
        if _TUI_INSTANCE:
            try:
                _TUI_INSTANCE.finish(success=False, message=f"Submission failed: {exc}")
            except Exception:
                pass

        warn(
            "Submission encountered an unexpected error. "
            f"Details:\n{exc}\n"
            "Tip: try switching to Zip upload or choose a higher level Project Path, then submit again.",
            emoji="x",
            close_window=True,
        )
