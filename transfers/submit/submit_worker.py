# submit_worker.py
"""
submit_worker.py – Sulu Submit worker (robust, with retries).

Business logic only; UI is handled by utils/submit_logger.py (Rich transcript).

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
import subprocess
import sys
import shutil
import tempfile
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import webbrowser

import requests


# ─── Lightweight logger fallback ──────────────────────────────────
# This gets replaced after bootstrap when worker_utils.logger is available.
def _default_logger(msg: str) -> None:
    print(str(msg))


_LOG = _default_logger


def _set_logger(fn) -> None:
    global _LOG
    _LOG = fn if callable(fn) else _default_logger


def _rclone_bytes(result) -> int:
    """Extract bytes_transferred from run_rclone's dict-or-None return."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("bytes_transferred", 0)
    return int(result)  # backward compat if somehow still int


def _rclone_stats(result):
    """Extract the stats dict from run_rclone's return, or None."""
    if isinstance(result, dict):
        return result
    return None


def _is_empty_upload(result, expected_file_count: int) -> bool:
    """True if rclone transferred nothing despite files being expected."""
    if expected_file_count <= 0:
        return False
    if result is None:
        return True
    if isinstance(result, dict):
        if not result.get("stats_received", True):
            return True
        return result.get("transfers", 0) == 0
    return False


def _get_rclone_tail(result) -> list:
    """Extract tail log lines from run_rclone result."""
    if isinstance(result, dict):
        return result.get("tail_lines", [])
    return []


def _log_upload_result(result, expected_bytes: int = 0, label: str = "") -> None:
    """Log a brief summary of rclone transfer stats to the terminal (debug only)."""
    if not _debug_enabled or not _debug_enabled():
        return
    if result is None:
        _LOG(f"  {label}result: no stats (rclone returned None)")
        return
    if not isinstance(result, dict):
        _LOG(f"  {label}result: {result}")
        return

    actual = result.get("bytes_transferred", 0)
    checks = result.get("checks", 0)
    transfers = result.get("transfers", 0)
    errors = result.get("errors", 0)
    received = result.get("stats_received", True)

    parts = []
    if not received:
        parts.append("stats_received=False")
    parts.append(f"transferred={_format_size(actual)}")
    if expected_bytes > 0:
        parts.append(f"expected={_format_size(expected_bytes)}")
    parts.append(f"checks={checks}")
    parts.append(f"transfers={transfers}")
    if errors:
        parts.append(f"errors={errors}")

    _LOG(f"  {label}{', '.join(parts)}")

    cmd = result.get("command")
    if cmd:
        _LOG(f"  {label}cmd: {cmd}")


def _check_rclone_errors(result, label: str = "") -> None:
    """Log a warning if rclone reported errors > 0 despite exit code 0 (debug only)."""
    if not _debug_enabled or not _debug_enabled():
        return
    if not isinstance(result, dict):
        return
    errors = result.get("errors", 0) or 0
    if errors > 0:
        _LOG(
            f"  WARNING ({label}): rclone reported {errors} error(s) "
            "despite exit code 0 — some files may not have uploaded"
        )


_WIN_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]?$")


def _is_filesystem_root(path: str) -> bool:
    """True if path is a filesystem root where rclone --files-from is unreliable."""
    p = str(path).replace("\\", "/").rstrip("/")
    if not p:
        return True
    if _WIN_DRIVE_ROOT_RE.match(p):
        return True
    if p == "":
        return True
    # macOS volume root: /Volumes/VolumeName
    if re.match(r"^/Volumes/[^/]+$", p):
        return True
    # Linux: /mnt/X or /media/user/X
    if re.match(r"^/mnt/[^/]+$", p):
        return True
    if re.match(r"^/media/[^/]+/[^/]+$", p):
        return True
    return False


_RISKY_CHARS = set("()'\"` &|;$!#")


def _check_risky_path_chars(path_str: str) -> Optional[str]:
    """Return a warning string if *path_str* contains shell-risky characters, else None."""
    found = set(c for c in path_str if c in _RISKY_CHARS)
    if found:
        chars = " ".join(repr(c) for c in sorted(found))
        return (
            f"Path contains special characters ({chars}) that may cause "
            f"issues on the render farm: {path_str}"
        )
    return None


def _split_manifest_by_first_dir(rel_manifest):
    """Group manifest entries by first path component. Returns {dir_name: [sub_paths]}."""
    groups = {}
    for rel in rel_manifest:
        slash_pos = rel.find("/")
        if slash_pos > 0:
            first_dir = rel[:slash_pos]
            remainder = rel[slash_pos + 1:]
        else:
            first_dir = ""
            remainder = rel
        groups.setdefault(first_dir, []).append(remainder)
    return groups


@dataclass
class ManifestBuildResult:
    rel_manifest: List[str]
    manifest_source_map: Dict[str, str]
    dependency_total_size: int
    ok_count: int


def _standard_continue_options() -> list[tuple[str, str, str]]:
    return [
        ("y", "Continue", "Proceed with submission"),
        ("n", "Cancel", "Cancel and close"),
        (
            "r",
            "Open diagnostic reports",
            "Open the diagnostic reports folder",
        ),
    ]


def _prompt_continue_with_reports(
    *,
    logger,
    report,
    prompt: str,
    choice_label: str,
    open_folder_fn,
    default: str = "y",
    followup_prompt: str = "Continue with submission?",
    followup_default: str = "y",
    followup_choice_label: str = "Continue after viewing reports?",
) -> bool:
    answer = logger.ask_choice(
        prompt,
        _standard_continue_options(),
        default=default,
    )
    report.record_user_choice(
        choice_label,
        answer,
        options=["Continue", "Cancel", "Open reports"],
    )

    if answer == "r":
        logger.report_info(str(report.get_path()))
        open_folder_fn(str(report.get_reports_dir()), logger_instance=logger)
        answer = logger.ask_choice(
            followup_prompt,
            [
                ("y", "Continue", "Proceed with submission"),
                ("n", "Cancel", "Cancel and close"),
            ],
            default=followup_default,
        )
        report.record_user_choice(
            followup_choice_label,
            answer,
            options=["Continue", "Cancel"],
        )

    if answer != "y":
        report.set_status("cancelled")
        return False
    return True


def _record_manifest_touch_mismatch(
    *,
    logger,
    report,
    total_touched: int,
    manifest_count: int,
) -> None:
    if total_touched <= 0 or total_touched >= manifest_count:
        return

    mismatch_msg = (
        f"rclone touched {total_touched} of {manifest_count} "
        "manifest files; some dependencies may have been skipped."
    )
    logger.warning(mismatch_msg)
    if _debug_enabled():
        _LOG(f"WARNING: {mismatch_msg}")
    report.add_issue_code(
        "UPLOAD_TOUCHED_LT_MANIFEST",
        "Retry upload and inspect manifest/source root alignment.",
    )


def _build_project_manifest_from_map(
    *,
    fmap: Dict[Any, Any],
    abs_blend: str,
    common_path: str,
    ok_files_cache: set[str],
    logger,
    report,
) -> ManifestBuildResult:
    rel_manifest: List[str] = []
    manifest_source_map: Dict[str, str] = {}
    dependency_total_size = 0
    ok_count = 0
    pack_idx = 0

    for src_path, _dst_path in fmap.items():
        src_str = str(src_path).replace("\\", "/")

        # Skip the main blend file (uploaded separately)
        if _samepath(src_str, abs_blend):
            continue

        # Use cached readability from Stage 1
        if src_str not in ok_files_cache:
            continue

        pack_idx += 1
        ok_count += 1

        size = 0
        try:
            size = os.path.getsize(src_str)
            dependency_total_size += size
        except Exception:
            pass

        logger.pack_entry(pack_idx, src_str, size=size, status="ok")

        rel = _relpath_safe(src_str, common_path)
        rel = _s3key_clean(rel)
        if rel:
            rel_manifest.append(rel)
            if rel not in manifest_source_map:
                manifest_source_map[rel] = src_str
            report.add_pack_entry(src_str, rel, file_size=size, status="ok")

    return ManifestBuildResult(
        rel_manifest=rel_manifest,
        manifest_source_map=manifest_source_map,
        dependency_total_size=dependency_total_size,
        ok_count=ok_count,
    )


def _apply_manifest_validation(
    *,
    rel_manifest: List[str],
    common_path: str,
    manifest_source_map: Dict[str, str],
    validate_manifest_entries,
    logger,
    report,
    open_folder_fn,
) -> tuple[List[str], bool]:
    manifest_validation = validate_manifest_entries(
        rel_manifest,
        source_root=common_path,
        source_map=manifest_source_map,
        clean_key=_s3key_clean,
    )
    normalized_manifest = manifest_validation.normalized_entries
    report.set_metadata("manifest_entry_count", len(normalized_manifest))
    report.set_metadata(
        "manifest_source_match_count",
        int(manifest_validation.stats.get("source_match_count", 0)),
    )
    report.set_metadata("manifest_validation_stats", manifest_validation.stats)
    for code in manifest_validation.issue_codes:
        report.add_issue_code(code, manifest_validation.actions.get(code))
    for warning in manifest_validation.warnings:
        logger.warning(warning)

    if not manifest_validation.has_blocking_risk:
        return normalized_manifest, True

    keep_going = _prompt_continue_with_reports(
        logger=logger,
        report=report,
        prompt="Manifest/source mapping risk detected. Continue anyway?",
        choice_label="Manifest validation risk found",
        open_folder_fn=open_folder_fn,
        default="n",
        followup_default="n",
        followup_choice_label="Continue after manifest risk report?",
    )
    return normalized_manifest, keep_going


def _build_job_payload(
    *,
    data: Dict[str, Any],
    org_id: str,
    project_name: str,
    blend_path: str,
    project_root_str: str,
    main_blend_s3: str,
    required_storage: int,
    use_project: bool,
) -> Dict[str, object]:
    use_scene_image_format = bool(data.get("use_scene_image_format")) or (
        str(data.get("image_format", "")).upper() == "SCENE"
    )
    frame_step_val = int(data.get("frame_stepping_size", 1))

    return {
        "job_data": {
            "id": data["job_id"],
            "project_id": data["project"]["id"],
            "packed_addons": data["packed_addons"],
            "organization_id": org_id,
            "main_file": (
                _nfc(
                    str(Path(blend_path).relative_to(project_root_str)).replace(
                        "\\", "/"
                    )
                )
                if not use_project
                else _nfc(_s3key_clean(main_blend_s3))
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


# ─── Utilities imported after bootstrap ───────────────────────────
# These will be set by _bootstrap_addon_modules() at runtime.
# Declared here to satisfy static analysis and allow early use in type hints.
_count = None
_format_size = None
_nfc = None
_debug_enabled = None
_is_interactive = None
_safe_input = None
_norm_abs_for_detection = None
_relpath_safe = None
_s3key_clean = None
_samepath = None
_mac_permission_help = None
_IS_MAC = sys.platform == "darwin"


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
    global _count, _format_size, _nfc, _debug_enabled, _is_interactive, _safe_input
    global \
        _norm_abs_for_detection, \
        _relpath_safe, \
        _s3key_clean, \
        _samepath, \
        _mac_permission_help

    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")

    # Make the add-on package importable for this subprocess
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")

    # Set logger for this script
    _set_logger(worker_utils.logger)

    # Import utility functions from worker_utils
    _count = worker_utils.count
    _format_size = worker_utils.format_size
    _nfc = worker_utils.normalize_nfc
    _debug_enabled = worker_utils.debug_enabled
    _is_interactive = worker_utils.is_interactive
    _norm_abs_for_detection = worker_utils.norm_abs_for_detection
    _relpath_safe = worker_utils.relpath_safe
    _s3key_clean = worker_utils.s3key_clean
    _samepath = worker_utils.samepath
    _mac_permission_help = worker_utils.mac_permission_help

    # Create a safe_input wrapper that uses the global _LOG
    def _safe_input_wrapper(prompt: str, default: str = "") -> str:
        return worker_utils.safe_input(prompt, default, log_fn=_LOG)

    _safe_input = _safe_input_wrapper

    # Other imports
    clear_console = worker_utils.clear_console
    shorten_path = worker_utils.shorten_path
    is_blend_saved = worker_utils.is_blend_saved
    requests_retry_session = worker_utils.requests_retry_session
    _build_base = worker_utils._build_base
    CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN
    open_folder = worker_utils.open_folder

    bat_utils = importlib.import_module(f"{pkg_name}.utils.bat_utils")
    pack_blend = bat_utils.pack_blend
    trace_dependencies = bat_utils.trace_dependencies
    compute_project_root = bat_utils.compute_project_root
    classify_out_of_root_ok_files = bat_utils.classify_out_of_root_ok_files

    project_upload_validator = importlib.import_module(
        f"{pkg_name}.utils.project_upload_validator"
    )
    validate_project_upload = project_upload_validator.validate_project_upload
    validate_manifest_entries = project_upload_validator.validate_manifest_entries

    cloud_files = importlib.import_module(f"{pkg_name}.utils.cloud_files")

    submit_logger = importlib.import_module(f"{pkg_name}.utils.submit_logger")
    create_logger = submit_logger.create_logger

    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone_utils")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone

    diagnostic_report_mod = importlib.import_module(
        f"{pkg_name}.utils.diagnostic_report"
    )
    DiagnosticReport = diagnostic_report_mod.DiagnosticReport
    generate_test_report = diagnostic_report_mod.generate_test_report

    return {
        "pkg_name": pkg_name,
        "clear_console": clear_console,
        "shorten_path": shorten_path,
        "is_blend_saved": is_blend_saved,
        "requests_retry_session": requests_retry_session,
        "_build_base": _build_base,
        "CLOUDFLARE_R2_DOMAIN": CLOUDFLARE_R2_DOMAIN,
        "open_folder": open_folder,
        "pack_blend": pack_blend,
        "trace_dependencies": trace_dependencies,
        "compute_project_root": compute_project_root,
        "classify_out_of_root_ok_files": classify_out_of_root_ok_files,
        "validate_project_upload": validate_project_upload,
        "validate_manifest_entries": validate_manifest_entries,
        "cloud_files": cloud_files,
        "create_logger": create_logger,
        "run_rclone": run_rclone,
        "ensure_rclone": ensure_rclone,
        "DiagnosticReport": DiagnosticReport,
        "generate_test_report": generate_test_report,
    }


# ─── main ────────────────────────────────────────────────────────
def main() -> None:
    t_start = time.perf_counter()

    data = _load_handoff_from_argv(sys.argv)
    mods = _bootstrap_addon_modules(data)

    clear_console = mods["clear_console"]
    shorten_path = mods["shorten_path"]
    is_blend_saved = mods["is_blend_saved"]
    requests_retry_session = mods["requests_retry_session"]
    _build_base = mods["_build_base"]
    CLOUDFLARE_R2_DOMAIN = mods["CLOUDFLARE_R2_DOMAIN"]
    open_folder = mods["open_folder"]
    pack_blend = mods["pack_blend"]
    trace_dependencies = mods["trace_dependencies"]
    compute_project_root = mods["compute_project_root"]
    classify_out_of_root_ok_files = mods["classify_out_of_root_ok_files"]
    validate_project_upload = mods["validate_project_upload"]
    validate_manifest_entries = mods["validate_manifest_entries"]
    cloud_files = mods["cloud_files"]
    create_logger = mods["create_logger"]
    run_rclone = mods["run_rclone"]
    ensure_rclone = mods["ensure_rclone"]
    DiagnosticReport = mods["DiagnosticReport"]
    generate_test_report = mods["generate_test_report"]

    proj = data["project"]

    clear_console()

    # Rich logger: scrolling transcript UI
    logger = create_logger(_LOG, input_fn=_safe_input)
    try:
        logger.logo_start()
    except Exception:
        pass

    # Single resilient session for all HTTP traffic
    session = requests_retry_session()

    # ─── Preflight checks (run early so user knows quickly if something's wrong) ───
    worker_utils = importlib.import_module(f"{mods['pkg_name']}.utils.worker_utils")
    run_preflight_checks = worker_utils.run_preflight_checks
    get_temp_space_available = worker_utils.get_temp_space_available

    # Estimate storage needs
    blend_size = 0
    try:
        blend_size = os.path.getsize(data["blend_path"])
    except Exception:
        pass

    # For ZIP mode, we need ~2x blend size in temp (archive + headroom)
    # For PROJECT mode, we just need temp space for manifest file
    use_project = bool(data.get("use_project_upload"))
    temp_needed = (
        blend_size * 2 if not use_project else 10 * 1024 * 1024
    )  # 10 MB for manifest

    storage_checks = [
        (tempfile.gettempdir(), temp_needed, "Temp folder"),
    ]

    preflight_ok, preflight_issues = run_preflight_checks(
        session=session,
        storage_checks=storage_checks,
    )

    _preflight_user_override = None  # recorded into report after it's created
    if not preflight_ok and preflight_issues:
        issue_text = "\n".join(f"• {issue}" for issue in preflight_issues)
        answer = logger.ask_choice(
            issue_text,
            [
                ("y", "Continue", "Upload anyway"),
                ("n", "Cancel", "Exit and resolve issues"),
            ],
            default="n",
        )
        if answer != "y":
            sys.exit(1)
        _preflight_user_override = True

    # Optional: check for addon update
    try:
        github_response = session.get(
            "https://api.github.com/repos/Superluminal-Studios/sulu-blender-addon/releases/latest"
        )
        if github_response.status_code == 200:
            latest_version = github_response.json().get("tag_name")
            if latest_version:
                latest_version = tuple(int(i) for i in latest_version.split("."))
                if latest_version > tuple(data["addon_version"]):
                    answer = logger.version_update(
                        "https://superlumin.al/blender-addon",
                        [
                            "Download the add-on .zip file from the link.",
                            "Uninstall the current add-on in Blender preferences.",
                            "Install the downloaded .zip file.",
                            "Restart Blender.",
                        ],
                        prompt="Update now?",
                        options=[
                            ("y", "Update", "Open the download page and close"),
                            ("n", "Not now", "Continue with current version"),
                        ],
                        default="n",
                    )
                    if answer == "y":
                        webbrowser.open("https://superlumin.al/blender-addon")
                        logger.info_exit(
                            "Install the new version, then restart Blender."
                        )
    except SystemExit:
        sys.exit(0)
    except Exception:
        logger.info(
            "Couldn't check for add-on updates. Continuing with current version."
        )

    headers = {"Authorization": data["user_token"]}

    # Ensure rclone is present (shows Rich download progress)
    try:
        rclone_bin = ensure_rclone(logger=logger)
    except Exception as e:
        logger.fatal(
            "Couldn't set up transfer tool. "
            "Restart Blender. If this keeps happening, reinstall the add-on.\n"
            f"Details: {e}"
        )

    # Verify farm availability (nice error if org misconfigured)
    try:
        farm_status = session.get(
            f"{data['pocketbase_url']}/api/farm_status/{proj['organization_id']}",
            headers=headers,
            timeout=30,
        )
        if farm_status.status_code != 200:
            # Keep the user-facing message calm; include details only in debug.
            if _debug_enabled():
                try:
                    logger.error(f"Farm status check response: {farm_status.json()}")
                except Exception:
                    logger.error(f"Farm status check response: {farm_status.text}")

            logger.fatal(
                "Couldn't confirm farm availability.\n"
                "Verify you're logged in and a project is selected. "
                "If this continues, log out and log back in."
            )
    except SystemExit:
        raise
    except Exception as exc:
        if _debug_enabled():
            logger.error(f"Farm status check exception: {exc}")
        logger.fatal(
            "Couldn't confirm farm availability.\n"
            "Verify you're logged in and a project is selected. "
            "If this continues, log out and log back in."
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
    is_blend_saved(blend_path, logger_instance=logger)

    # Create diagnostic report for continuous logging
    report = DiagnosticReport(
        reports_dir=Path(data["addon_dir"]) / "reports",
        job_id=job_id,
        blend_name=Path(blend_path).stem,
        metadata={
            "source_blend": blend_path,
            "upload_type": "PROJECT" if use_project else "ZIP",
            "job_name": data["job_name"],
            "blender_version": data["blender_version"],
            "addon_version": data["addon_version"],
            "device_type": data.get("device_type", ""),
            "start_frame": data["start_frame"],
            "end_frame": data["end_frame"],
        },
    )

    # Check for path characters that may cause farm-side issues
    _path_warn = _check_risky_path_chars(blend_path)
    if _path_warn:
        preflight_issues.append(_path_warn)

    # Record preflight results and environment into the diagnostic report
    report.record_preflight(preflight_ok, preflight_issues, _preflight_user_override)
    report.set_environment("rclone_bin", str(rclone_bin))
    try:
        _ver_out = subprocess.check_output(
            [str(rclone_bin), "--version"], timeout=5, text=True
        )
        _rclone_ver = _ver_out.strip().splitlines()[0] if _ver_out.strip() else ""
        report.set_environment("rclone_version", _rclone_ver)
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════════════════
    # Stage 1: Tracing — discover dependencies
    # ═══════════════════════════════════════════════════════════════════════════
    logger.stage_header(
        1,
        "Tracing dependencies",
        "Scanning for external assets referenced by this blend file",
        details=[
            f"Main file: {Path(blend_path).name}",
            "Resolving dependencies",
        ],
    )
    logger.trace_start(blend_path)
    report.start_stage("trace")

    # Pack assets
    if use_project:
        # Trace dependencies (hydrate cloud placeholders)
        dep_paths, missing_set, unreadable_dict, raw_usages, optional_set = trace_dependencies(
            Path(blend_path), logger=logger, hydrate=True, diagnostic_report=report
        )

        # Detect absolute paths in the blend file (PROJECT mode requires relative paths)
        absolute_path_deps: List[Path] = []
        for usage in raw_usages:
            try:
                # Skip optional assets (e.g. linked-packed libraries) - no warnings needed
                if getattr(usage, "is_optional", False):
                    continue
                # Check if the path stored in the blend file is absolute (not //-relative)
                if not usage.asset_path.is_blendfile_relative():
                    abs_path = usage.abspath
                    if abs_path not in missing_set and abs_path not in unreadable_dict:
                        if abs_path not in absolute_path_deps:
                            absolute_path_deps.append(abs_path)
            except Exception:
                pass  # Skip if we can't check the path

        # Log absolute-path dependencies as trace entries in the diagnostic report
        for abs_dep in absolute_path_deps:
            try:
                report.add_trace_entry(
                    source_blend=blend_path,
                    block_type="",
                    block_name="",
                    resolved_path=str(abs_dep),
                    status="absolute_path",
                    error_msg="Absolute path — farm cannot resolve. Make relative or use Zip upload.",
                )
            except Exception:
                pass

        ok_files_set = set(
            p for p in dep_paths if p not in missing_set and p not in unreadable_dict
        )
        ok_files_cache = set(str(p).replace("\\", "/") for p in ok_files_set)

        # Compute project root
        custom_root = None
        if not automatic_project_path:
            if not custom_project_path_str or not str(custom_project_path_str).strip():
                logger.fatal(
                    "Custom project path is empty.\n"
                    "Turn on Automatic Project Path, or select a valid folder."
                )
            custom_root = Path(custom_project_path_str)

        project_root, same_drive_deps, cross_drive_deps = compute_project_root(
            Path(blend_path),
            dep_paths,
            custom_root,
            missing_files=missing_set,
            unreadable_files=unreadable_dict,
            optional_files=optional_set,
        )
        out_of_root_ok_files = classify_out_of_root_ok_files(
            same_drive_deps, project_root
        )
        common_path = str(project_root).replace("\\", "/")
        project_root_str = common_path
        report.set_metadata("project_root", common_path)

        # Determine project_root_method for the report
        if not automatic_project_path:
            report.set_metadata("project_root_method", "custom")
        elif _is_filesystem_root(common_path):
            report.set_metadata("project_root_method", "filesystem_root")
        else:
            report.set_metadata("project_root_method", "automatic")

        if _is_filesystem_root(common_path) and _debug_enabled():
            _LOG(
                f"NOTE: Project root is a filesystem root ({common_path}). "
                "Dependencies span multiple top-level directories on the same drive."
            )
        if cross_drive_deps:
            report.add_cross_drive_files([str(p) for p in cross_drive_deps])
        if absolute_path_deps:
            report.add_absolute_path_files([str(p) for p in absolute_path_deps])
        if out_of_root_ok_files:
            report.add_out_of_root_files([str(p) for p in out_of_root_ok_files])

        project_validation = validate_project_upload(
            blend_path=Path(blend_path),
            project_root=project_root,
            dep_paths=dep_paths,
            raw_usages=raw_usages,
            missing_set=missing_set,
            unreadable_dict=unreadable_dict,
            optional_set=optional_set,
            cross_drive_files=list(cross_drive_deps),
            absolute_path_files=list(absolute_path_deps),
            out_of_root_files=list(out_of_root_ok_files),
        )
        report.set_metadata("project_validation_version", "1.0")
        report.set_metadata("project_validation_stats", project_validation.stats)
        for code in project_validation.issue_codes:
            report.add_issue_code(code, project_validation.actions.get(code))

        # Build warning text for issues
        missing_files_list = [str(p) for p in sorted(missing_set)]
        unreadable_files_list = [
            (str(p), err)
            for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))
        ]
        absolute_path_files_list = [str(p) for p in sorted(absolute_path_deps)]
        out_of_root_files_list = [str(p) for p in sorted(out_of_root_ok_files)]
        has_issues = bool(
            cross_drive_deps
            or missing_files_list
            or unreadable_files_list
            or absolute_path_deps
            or out_of_root_files_list
            or project_validation.has_blocking_risk
        )

        warning_text = None
        if has_issues:
            parts: List[str] = []
            if absolute_path_deps:
                parts.append(
                    f"{_count(len(absolute_path_deps), 'dependency')} with absolute paths (excluded)"
                )
            if cross_drive_deps:
                parts.append(
                    f"{_count(len(cross_drive_deps), 'dependency')} on another drive (not included in Project upload)"
                )
            if missing_files_list:
                parts.append(f"{_count(len(missing_files_list), 'missing dependency')}")
            if unreadable_files_list:
                parts.append(
                    f"{_count(len(unreadable_files_list), 'dependency')} not readable"
                )
            if out_of_root_files_list:
                parts.append(
                    f"{_count(len(out_of_root_files_list), 'dependency')} outside selected project root (not included)"
                )

            mac_extra = ""
            if _IS_MAC and unreadable_files_list:
                for p, err in unreadable_files_list:
                    low = err.lower()
                    if (
                        "permission" in low
                        or "operation not permitted" in low
                        or "not permitted" in low
                    ):
                        mac_extra = "\n" + _mac_permission_help(p, err)
                        break

            # Build contextual warning text based on which issues are present
            warning_parts = []

            if absolute_path_deps:
                warning_parts.append(
                    "Farm cannot resolve absolute paths. "
                    "Make paths relative (File → External Data → Make All Paths Relative), or use Zip upload."
                )

            if cross_drive_deps:
                warning_parts.append(
                    "Cross-drive files excluded from Project upload. "
                    "Use Zip upload, or move files to the project drive."
                )

            if out_of_root_files_list:
                warning_parts.append(
                    "Some dependencies are outside the selected project root and are excluded from Project upload. "
                    "Use Zip upload, or broaden Custom Project Path."
                )

            if (
                (missing_files_list or unreadable_files_list)
                and not absolute_path_deps
                and not cross_drive_deps
            ):
                warning_parts.append("Missing or unreadable files excluded.")

            if project_validation.warnings:
                warning_parts.extend(project_validation.warnings)

            warning_text = (
                "\n".join(warning_parts) + mac_extra if warning_parts else None
            )

        logger.trace_summary(
            total=len(dep_paths),
            missing=len(missing_set),
            unreadable=len(unreadable_dict),
            project_root=shorten_path(common_path),
            cross_drive=len(cross_drive_deps),
            warning_text=warning_text,
            cross_drive_excluded=True,
            missing_files=missing_files_list,
            unreadable_files=unreadable_files_list,
            cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
            absolute_path_files=absolute_path_files_list,
            out_of_root_files=out_of_root_files_list,
            shorten_fn=shorten_path,
            automatic_project_path=automatic_project_path,
        )
        report.complete_stage("trace")

        # TEST MODE: show report and exit
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

            test_report_data, test_report_path = generate_test_report(
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
                format_size_fn=_format_size,
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
                unreadable=[
                    (str(p), err)
                    for p, err in sorted(
                        unreadable_dict.items(), key=lambda x: str(x[0])
                    )
                ],
                cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
                upload_type="PROJECT",
                report_path=str(test_report_path) if test_report_path else None,
                shorten_fn=shorten_path,
            )
            _safe_input("\nPress Enter to close.", "")
            sys.exit(0)

        # Prompt if there are issues
        if has_issues:
            issue_prompt = "Some dependencies have problems. Continue anyway?"
            issue_default = "y"
            issue_choice_label = "Dependency issues found"
            if project_validation.has_blocking_risk:
                issue_prompt = (
                    "Project upload risk detected (path mapping may fail on farm). Continue anyway?"
                )
                issue_default = "n"
                issue_choice_label = "Project upload blocking risks found"

            keep_going = _prompt_continue_with_reports(
                logger=logger,
                report=report,
                prompt=issue_prompt,
                choice_label=issue_choice_label,
                open_folder_fn=open_folder,
                default=issue_default,
                followup_default="y",
            )
            if not keep_going:
                sys.exit(1)

        # ═══════════════════════════════════════════════════════════════════════
        # Stage 2: Manifest — map dependencies into project structure
        # ═══════════════════════════════════════════════════════════════════════
        logger.stage_header(
            2,
            "Building manifest",
            "Mapping dependencies into the project structure",
        )

        report.start_stage("pack")

        # Build file map from pre-expanded OK files (no filesystem I/O needed)
        fmap, pack_report = pack_blend(
            blend_path,
            target="",
            method="PROJECT",
            project_path=common_path,
            return_report=True,
            pre_traced_deps=list(ok_files_set),
        )

        abs_blend = _norm_abs_for_detection(blend_path)
        logger.pack_start()
        manifest_build = _build_project_manifest_from_map(
            fmap=fmap,
            abs_blend=abs_blend,
            common_path=common_path,
            ok_files_cache=ok_files_cache,
            logger=logger,
            report=report,
        )
        rel_manifest = manifest_build.rel_manifest
        manifest_source_map = manifest_build.manifest_source_map
        dependency_total_size = manifest_build.dependency_total_size

        # Calculate total required storage (dependencies + main blend)
        required_storage = dependency_total_size
        try:
            required_storage += os.path.getsize(blend_path)
        except Exception:
            pass

        rel_manifest, keep_going = _apply_manifest_validation(
            rel_manifest=rel_manifest,
            common_path=common_path,
            manifest_source_map=manifest_source_map,
            validate_manifest_entries=validate_manifest_entries,
            logger=logger,
            report=report,
            open_folder_fn=open_folder,
        )
        if not keep_going:
            sys.exit(1)

        with filelist.open("w", encoding="utf-8") as fp:
            for rel in rel_manifest:
                fp.write(f"{rel}\n")

        # Validate manifest write-back
        try:
            written_lines = filelist.read_text("utf-8").splitlines()
            written_count = len([line for line in written_lines if line.strip()])
            if written_count != len(rel_manifest):
                if _debug_enabled():
                    _LOG(
                        f"WARNING: Manifest line count mismatch — "
                        f"expected {len(rel_manifest)}, got {written_count}"
                    )
                report.set_metadata("manifest_validation", "mismatch")
                report.set_metadata("manifest_expected", len(rel_manifest))
                report.set_metadata("manifest_written", written_count)
            else:
                report.set_metadata("manifest_validation", "ok")
        except Exception as exc:
            if _debug_enabled():
                _LOG(f"WARNING: Could not validate manifest: {exc}")
            report.set_metadata("manifest_validation", f"error: {exc}")

        blend_rel = _relpath_safe(abs_blend, common_path)
        main_blend_s3 = _nfc(_s3key_clean(blend_rel) or os.path.basename(abs_blend))

        logger.pack_end(
            ok_count=manifest_build.ok_count,
            total_size=required_storage,
            title="Manifest complete",
        )
        report.set_pack_dependency_size(dependency_total_size)
        report.complete_stage("pack")

    else:  # ZIP mode
        dep_paths, missing_set, unreadable_dict, raw_usages, optional_set = trace_dependencies(
            Path(blend_path), logger=logger, diagnostic_report=report
        )

        project_root, same_drive_deps, cross_drive_deps = compute_project_root(
            Path(blend_path),
            dep_paths,
            missing_files=missing_set,
            unreadable_files=unreadable_dict,
            optional_files=optional_set,
        )
        project_root_str = str(project_root).replace("\\", "/")
        report.set_metadata("project_root", project_root_str)
        report.set_metadata("project_root_method", "automatic")
        if cross_drive_deps:
            report.add_cross_drive_files([str(p) for p in cross_drive_deps])

        missing_files_list = [str(p) for p in sorted(missing_set)]
        unreadable_files_list = [
            (str(p), err)
            for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))
        ]
        has_zip_issues = bool(missing_files_list or unreadable_files_list)

        zip_warning_text = None
        if has_zip_issues:
            zip_warning_text = "The archive may be incomplete."

        logger.trace_summary(
            total=len(dep_paths),
            missing=len(missing_set),
            unreadable=len(unreadable_dict),
            project_root=shorten_path(project_root_str),
            cross_drive=len(cross_drive_deps),
            warning_text=zip_warning_text,
            cross_drive_excluded=False,
            missing_files=missing_files_list,
            unreadable_files=unreadable_files_list,
            cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
            shorten_fn=shorten_path,
            automatic_project_path=True,  # ZIP mode always auto-detects
        )
        report.complete_stage("trace")

        if has_zip_issues:
            keep_going = _prompt_continue_with_reports(
                logger=logger,
                report=report,
                prompt="Some dependencies have problems. Continue anyway?",
                choice_label="Dependency issues found",
                open_folder_fn=open_folder,
                default="y",
                followup_default="y",
            )
            if not keep_going:
                sys.exit(1)

        # TEST MODE
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

            test_report_data, test_report_path = generate_test_report(
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
                format_size_fn=_format_size,
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
                unreadable=[
                    (str(p), err)
                    for p, err in sorted(
                        unreadable_dict.items(), key=lambda x: str(x[0])
                    )
                ],
                cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
                upload_type="ZIP",
                report_path=str(test_report_path) if test_report_path else None,
                shorten_fn=shorten_path,
            )
            _safe_input("\nPress Enter to close.", "")
            sys.exit(0)

        # ═══════════════════════════════════════════════════════════════════════
        # Stage 2: Packing (Zip upload)
        # ═══════════════════════════════════════════════════════════════════════
        logger.stage_header(
            2,
            "Packing",
            "Creating a compressed archive with all dependencies",
        )
        report.start_stage("pack")

        abs_blend_norm = _norm_abs_for_detection(blend_path)

        _zip_started = False
        _zip_dep_size = 0

        def _on_zip_entry(idx, total, arcname, size, method):
            nonlocal _zip_started, _zip_dep_size
            _zip_dep_size += size
            if not _zip_started:
                logger.zip_start(total, 0)
                _zip_started = True
            logger.zip_entry(idx, total, arcname, size, method)
            # Log to diagnostic report
            report.add_pack_entry(arcname, arcname, file_size=size, status="ok")

        def _on_zip_done(zippath, total_files, total_bytes, elapsed):
            logger.zip_done(zippath, total_files, total_bytes, elapsed)

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
            report.set_status("failed")
            logger.fatal("Archive not created. Check disk space and permissions.")

        required_storage = zip_file.stat().st_size
        rel_manifest = []
        common_path = ""
        main_blend_s3 = ""
        report.set_pack_dependency_size(_zip_dep_size)
        report.complete_stage("pack")

    # NO_SUBMIT MODE
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
        if not use_project and zip_file.exists():
            try:
                zip_file.unlink()
                logger.info(f"Temporary archive removed: {zip_file}")
            except:
                pass
        _safe_input("\nPress Enter to close.", "")
        sys.exit(0)

    # ═══════════════════════════════════════════════════════════════════════════
    # Stage 3: Uploading — transfer to cloud storage
    # ═══════════════════════════════════════════════════════════════════════════
    logger.stage_header(3, "Uploading", "Transferring data to farm storage")
    report.start_stage("upload")

    # R2 credentials
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
        logger.fatal(
            f"Couldn't get storage credentials. Check your connection and try again.\nDetails: {exc}"
        )

    base_cmd = _build_base(rclone_bin, f"https://{CLOUDFLARE_R2_DOMAIN}", s3info)

    rclone_settings = [
        "--transfers",
        "4",
        "--checkers",
        "4",
        "--s3-chunk-size",
        "64M",
        "--s3-upload-cutoff",
        "64M",
        "--s3-upload-concurrency",
        "4",
        "--buffer-size",
        "64M",
        "--retries",
        "20",
        "--low-level-retries",
        "20",
        "--retries-sleep",
        "5s",
        "--timeout",
        "5m",
        "--contimeout",
        "30s",
        "--no-traverse",
        "--stats",
        "0.1s",
    ]

    has_addons = data.get("packed_addons") and len(data["packed_addons"]) > 0

    try:
        if not use_project:
            # Zip upload
            total_steps = 2 if has_addons else 1
            step = 1
            logger.upload_start(total_steps)

            logger.upload_step(step, total_steps, "Uploading archive")
            report.start_upload_step(
                step, total_steps, "Uploading archive",
                expected_bytes=required_storage,
                source=str(zip_file),
                destination=f":s3:{bucket}/",
                verb="move",
            )
            rclone_result = run_rclone(
                base_cmd,
                "move",
                str(zip_file),
                f":s3:{bucket}/",
                extra=rclone_settings,
                logger=logger,
                total_bytes=required_storage,
            )
            if required_storage > 0 and logger._transfer_total == 0:
                logger._transfer_total = required_storage
            logger.upload_complete("Archive uploaded")
            _log_upload_result(rclone_result, expected_bytes=required_storage, label="Archive: ")
            _check_rclone_errors(rclone_result, label="Archive")
            report.complete_upload_step(
                bytes_transferred=_rclone_bytes(rclone_result),
                rclone_stats=_rclone_stats(rclone_result),
            )
            step += 1

            if has_addons:
                logger.upload_step(step, total_steps, "Uploading add-ons")
                report.start_upload_step(
                    step, total_steps, "Uploading add-ons",
                    source=data["packed_addons_path"],
                    destination=f":s3:{bucket}/{job_id}/addons/",
                    verb="moveto",
                )
                rclone_result = run_rclone(
                    base_cmd,
                    "moveto",
                    data["packed_addons_path"],
                    f":s3:{bucket}/{job_id}/addons/",
                    extra=rclone_settings,
                    logger=logger,
                )
                logger.upload_complete("Add-ons uploaded")
                _log_upload_result(rclone_result, label="Add-ons: ")
                _check_rclone_errors(rclone_result, label="Add-ons")
                report.complete_upload_step(
                    bytes_transferred=_rclone_bytes(rclone_result),
                    rclone_stats=_rclone_stats(rclone_result),
                )

            report.complete_stage("upload")

        else:
            # Project upload
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
            logger.upload_step(step, total_steps, "Uploading main blend")
            move_to_path = _nfc(_s3key_clean(f"{project_name}/{main_blend_s3}"))
            remote_main = f":s3:{bucket}/{move_to_path}"
            report.start_upload_step(
                step, total_steps, "Uploading main blend",
                expected_bytes=blend_size,
                source=blend_path,
                destination=remote_main,
                verb="copyto",
            )
            rclone_result = run_rclone(
                base_cmd,
                "copyto",
                blend_path,
                remote_main,
                extra=rclone_settings,
                logger=logger,
                total_bytes=blend_size,
            )
            # Ensure completion panel shows the blend size even if rclone
            # finished too fast to emit stats (stats_received=False).
            if blend_size > 0 and logger._transfer_total == 0:
                logger._transfer_total = blend_size
            logger.upload_complete("Main blend uploaded")
            _log_upload_result(rclone_result, expected_bytes=blend_size, label="Blend: ")
            report.complete_upload_step(
                bytes_transferred=_rclone_bytes(rclone_result),
                rclone_stats=_rclone_stats(rclone_result),
            )
            step += 1

            if rel_manifest:
                logger.upload_step(step, total_steps, "Uploading dependencies")
                if _debug_enabled():
                    _LOG(f"Manifest: {len(rel_manifest)} files, {_format_size(dependency_total_size)} expected")

                if _is_filesystem_root(common_path):
                    # --- SPLIT PATH: filesystem root source ---
                    if _debug_enabled():
                        _LOG(f"Project root is a filesystem root ({common_path}), splitting upload by directory")
                    groups = _split_manifest_by_first_dir(rel_manifest)
                    if _debug_enabled():
                        _LOG(f"Split into {len(groups)} group(s): {list(groups.keys())}")

                    report.start_upload_step(
                        step, total_steps, "Uploading dependencies (split)",
                        manifest_entries=len(rel_manifest),
                        expected_bytes=dependency_total_size,
                        source=common_path,
                        destination=f":s3:{bucket}/{project_name}/",
                        verb="copy",
                    )

                    agg_bytes = 0
                    agg_checks = 0
                    agg_transfers = 0
                    agg_errors = 0
                    any_empty = False

                    for group_name, group_entries in groups.items():
                        if not group_entries:
                            continue

                        # Build group source and dest
                        if group_name:
                            group_source = common_path.rstrip("/") + "/" + group_name
                            group_dest = f":s3:{bucket}/{project_name}/{group_name}/"
                        else:
                            # Files directly at root level (rare)
                            group_source = common_path
                            group_dest = f":s3:{bucket}/{project_name}/"

                        # Write temporary filelist for this group
                        group_filelist = Path(tempfile.gettempdir()) / f"{job_id}_g_{hash(group_name) & 0xFFFF:04x}.txt"
                        with group_filelist.open("w", encoding="utf-8") as fp:
                            for entry in group_entries:
                                fp.write(f"{entry}\n")

                        # Validate group filelist write-back
                        try:
                            gl = group_filelist.read_text("utf-8").splitlines()
                            gc = len([line for line in gl if line.strip()])
                            if gc != len(group_entries) and _debug_enabled():
                                _LOG(
                                    f"  WARNING: Group '{group_name}' filelist mismatch — "
                                    f"expected {len(group_entries)}, got {gc}"
                                )
                        except Exception:
                            pass

                        group_rclone = ["--files-from", str(group_filelist)]
                        group_rclone.extend(rclone_settings)

                        if _debug_enabled():
                            _LOG(f"  Group '{group_name}': {len(group_entries)} files, source={group_source}")
                        grp_result = run_rclone(
                            base_cmd, "copy", group_source, group_dest,
                            extra=group_rclone, logger=logger,
                            total_bytes=dependency_total_size,
                        )
                        _log_upload_result(grp_result, label=f"  Group '{group_name}': ")
                        _check_rclone_errors(grp_result, label=f"Group '{group_name}'")
                        report.add_upload_split_group(
                            group_name=group_name or "(root)",
                            file_count=len(group_entries),
                            source=group_source,
                            destination=group_dest,
                            rclone_stats=_rclone_stats(grp_result),
                        )

                        # Clean up temp filelist
                        try:
                            group_filelist.unlink(missing_ok=True)
                        except Exception:
                            pass

                        # Accumulate stats
                        agg_bytes += _rclone_bytes(grp_result)
                        if isinstance(grp_result, dict):
                            agg_checks += grp_result.get("checks", 0)
                            agg_transfers += grp_result.get("transfers", 0)
                            agg_errors += grp_result.get("errors", 0)
                        if _is_empty_upload(grp_result, len(group_entries)):
                            any_empty = True
                            if _debug_enabled():
                                grp_tail = _get_rclone_tail(grp_result)
                                _LOG(f"  WARNING: Group '{group_name}' transferred 0 files")
                                if grp_tail:
                                    for line in grp_tail[-5:]:
                                        _LOG(f"    {line}")

                    # Set aggregated total so upload_complete panel shows correct size
                    logger._transfer_total = dependency_total_size
                    logger.upload_complete("Dependencies uploaded")
                    if _debug_enabled():
                        _LOG(
                            f"  Split upload totals: "
                            f"transferred={_format_size(agg_bytes)}, "
                            f"checks={agg_checks}, transfers={agg_transfers}, "
                            f"errors={agg_errors}, groups={len(groups)}"
                        )
                    agg_stats = {
                        "bytes_transferred": agg_bytes,
                        "checks": agg_checks,
                        "transfers": agg_transfers,
                        "errors": agg_errors,
                        "stats_received": True,
                        "split_groups": len(groups),
                    }
                    report.complete_upload_step(
                        bytes_transferred=agg_bytes,
                        rclone_stats=agg_stats,
                    )
                    if any_empty and dependency_total_size > 0 and _debug_enabled():
                        _LOG(
                            "WARNING: Some dependency groups transferred 0 files. "
                            "See diagnostic report."
                        )
                    # Post-upload transfer count validation
                    total_touched = agg_transfers + agg_checks
                    _record_manifest_touch_mismatch(
                        logger=logger,
                        report=report,
                        total_touched=total_touched,
                        manifest_count=len(rel_manifest),
                    )
                else:
                    # --- NORMAL PATH: non-root source (existing behavior) ---
                    report.start_upload_step(
                        step, total_steps, "Uploading dependencies",
                        manifest_entries=len(rel_manifest),
                        expected_bytes=dependency_total_size,
                        source=str(common_path),
                        destination=f":s3:{bucket}/{project_name}/",
                        verb="copy",
                    )
                    dependency_rclone_settings = ["--files-from", str(filelist)]
                    dependency_rclone_settings.extend(rclone_settings)
                    rclone_result = run_rclone(
                        base_cmd,
                        "copy",
                        str(common_path),
                        f":s3:{bucket}/{project_name}/",
                        extra=dependency_rclone_settings,
                        logger=logger,
                        total_bytes=dependency_total_size,
                    )
                    logger.upload_complete("Dependencies uploaded")
                    _log_upload_result(rclone_result, expected_bytes=dependency_total_size, label="Dependencies: ")
                    _check_rclone_errors(rclone_result, label="Dependencies")
                    stats = _rclone_stats(rclone_result)
                    report.complete_upload_step(
                        bytes_transferred=_rclone_bytes(rclone_result),
                        rclone_stats=stats,
                    )
                    if _is_empty_upload(rclone_result, len(rel_manifest)) and _debug_enabled():
                        tail = _get_rclone_tail(rclone_result)
                        _LOG(
                            f"WARNING: Expected {_format_size(dependency_total_size)} "
                            f"across {len(rel_manifest)} files, but rclone transferred 0. "
                            "See diagnostic report for details."
                        )
                        if tail:
                            _LOG("rclone tail log:")
                            for line in tail[-10:]:
                                _LOG(f"  {line}")
                    # Post-upload transfer count validation
                    if stats:
                        total_touched = (stats.get("transfers", 0) or 0) + (stats.get("checks", 0) or 0)
                        _record_manifest_touch_mismatch(
                            logger=logger,
                            report=report,
                            total_touched=total_touched,
                            manifest_count=len(rel_manifest),
                        )
                step += 1

            with filelist.open("a", encoding="utf-8") as fp:
                fp.write(_nfc(_s3key_clean(main_blend_s3)) + "\n")

            logger.upload_step(step, total_steps, "Uploading manifest")
            report.start_upload_step(
                step, total_steps, "Uploading manifest",
                source=str(filelist),
                destination=f":s3:{bucket}/{project_name}/",
                verb="move",
            )
            rclone_result = run_rclone(
                base_cmd,
                "move",
                str(filelist),
                f":s3:{bucket}/{project_name}/",
                extra=rclone_settings,
                logger=logger,
            )
            logger.upload_complete("Manifest uploaded")
            _log_upload_result(rclone_result, label="Manifest: ")
            _check_rclone_errors(rclone_result, label="Manifest")
            report.complete_upload_step(
                bytes_transferred=_rclone_bytes(rclone_result),
                rclone_stats=_rclone_stats(rclone_result),
            )
            step += 1

            if has_addons:
                logger.upload_step(step, total_steps, "Uploading add-ons")
                report.start_upload_step(
                    step, total_steps, "Uploading add-ons",
                    source=data["packed_addons_path"],
                    destination=f":s3:{bucket}/{job_id}/addons/",
                    verb="moveto",
                )
                rclone_result = run_rclone(
                    base_cmd,
                    "moveto",
                    data["packed_addons_path"],
                    f":s3:{bucket}/{job_id}/addons/",
                    extra=rclone_settings,
                    logger=logger,
                )
                logger.upload_complete("Add-ons uploaded")
                _log_upload_result(rclone_result, label="Add-ons: ")
                _check_rclone_errors(rclone_result, label="Add-ons")
                report.complete_upload_step(
                    bytes_transferred=_rclone_bytes(rclone_result),
                    rclone_stats=_rclone_stats(rclone_result),
                )

        report.complete_stage("upload")

    except RuntimeError as exc:
        report.set_status("failed")
        logger.fatal(
            f"Upload stopped. Check your connection and try again.\nDetails: {exc}"
        )

    finally:
        try:
            if "packed_addons_path" in data and data["packed_addons_path"]:
                shutil.rmtree(data["packed_addons_path"], ignore_errors=True)
        except Exception:
            pass

    payload = _build_job_payload(
        data=data,
        org_id=org_id,
        project_name=project_name,
        blend_path=blend_path,
        project_root_str=project_root_str,
        main_blend_s3=main_blend_s3,
        required_storage=required_storage,
        use_project=use_project,
    )

    try:
        post_resp = session.post(
            f"{data['pocketbase_url']}/api/farm/{org_id}/jobs",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        post_resp.raise_for_status()
    except requests.RequestException as exc:
        report.set_status("failed")
        logger.fatal(
            f"Couldn't register job. Check your connection and try again.\nDetails: {exc}"
        )

    # Finalize the diagnostic report
    report.finalize()

    elapsed = time.perf_counter() - t_start
    job_url = f"https://superlumin.al/p/{project_sqid}/farm/jobs/{data['job_id']}"

    selection = "c"
    try:
        selection = logger.logo_end(
            job_id=data["job_id"],
            elapsed=elapsed,
            job_url=job_url,
            report_path=str(report.get_reports_dir()),
        )
    except Exception:
        selection = "c"

    try:
        # Best effort: remove the handoff file (only in worker mode)
        handoff_path = Path(sys.argv[1]).resolve()
        handoff_path.unlink(missing_ok=True)
    except Exception:
        pass

    # Act on the integrated success prompt.
    if selection == "j":
        try:
            webbrowser.open(job_url)
            logger.job_complete(job_url)
        except Exception:
            pass
        _safe_input("\nPress Enter to close.", "")
        sys.exit(0)

    if selection == "r":
        try:
            open_folder(str(report.get_reports_dir()), logger_instance=logger)
            logger.info("Diagnostic reports folder opened.")
        except Exception:
            pass
        _safe_input("\nPress Enter to close.", "")
        sys.exit(0)

    # selection == "c" (close)
    sys.exit(0)


# ─── entry ───────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(
            f"\n{exc}\n"
            "Try Zip upload or select a different project path, then submit again."
        )
        try:
            _safe_input("\nPress Enter to close.", "")
        except Exception:
            pass
        sys.exit(1)
