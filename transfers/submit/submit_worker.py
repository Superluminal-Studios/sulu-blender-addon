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

# Standard library
import importlib
import json
import os
import re
import subprocess
import sys
import shutil
import tempfile
import threading
import time
import types
import zipfile
import webbrowser
from concurrent.futures import Future
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


# Lightweight logger fallback
# This gets replaced after bootstrap when worker_utils.logger is available.
def _default_logger(msg: str) -> None:
    print(str(msg))


_LOG = _default_logger
_UPLOAD_RESULT_PREFIX = "SULU_UPLOAD_RESULT "
_PHASE_TIMING_PREFIX = "SULU_PHASE_TIMING "
_ZIP_SINGLE_PUT_CUTOFF_BYTES = 100 * 1024 * 1024
_MAX_CLOCK_DRIFT_SECONDS = 300
_MAX_SETTINGS_SCHEMA_BYTES = 2 * 1024 * 1024


def _build_rclone_upload_settings(
    *,
    single_zip_archive: bool = False,
    archive_size_bytes: int = 0,
) -> List[str]:
    """Build bounded-memory S3 settings for the requested upload shape.

    ZIP submissions upload one known-size archive.  Keep archives up to 100 MiB
    on S3's single-PUT path, then use 16 MiB multipart chunks so concurrency is
    useful for larger archives without the 64 MiB progress/memory lead observed
    in the benchmark runs.  Other upload shapes retain their established
    settings until they have their own live A/B evidence.
    """
    if single_zip_archive:
        transfers = "1"
        checkers = "1"
        chunk_size = "16M"
        upload_cutoff = "100M"
        upload_concurrency = "8"
        buffer_size = "16M"
    else:
        transfers = "4"
        checkers = "4"
        chunk_size = "64M"
        upload_cutoff = "64M"
        upload_concurrency = "4"
        buffer_size = "64M"

    settings = [
        "--transfers",
        transfers,
        "--checkers",
        checkers,
        "--s3-chunk-size",
        chunk_size,
        "--s3-upload-cutoff",
        upload_cutoff,
        "--s3-upload-concurrency",
        upload_concurrency,
        "--buffer-size",
        buffer_size,
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
    ]
    if single_zip_archive:
        # ZIP archive names are generated from a fresh job UUID. There is no
        # useful destination object to compare before upload, so avoid the
        # serial preflight HEAD. This does not disable rclone's post-upload
        # verification, and a retried submission safely overwrites the same
        # job-scoped archive.
        settings.append("--no-check-dest")
    if single_zip_archive and int(archive_size_bytes or 0) > _ZIP_SINGLE_PUT_CUTOFF_BYTES:
        # The archive key is unique to this job. For multipart archives, avoid
        # rereading the entire staged ZIP solely to attach a whole-object MD5;
        # rclone still validates every uploaded part and performs its normal
        # post-upload HEAD, while ZIP CRCs protect extraction on the node.
        settings.append("--s3-disable-checksum")
    return settings


def _clock_drift_from_http_date(
    value: object,
    *,
    local_time: Optional[float] = None,
) -> Optional[int]:
    """Return signed local-minus-server clock drift from an HTTP Date value."""
    try:
        server_time = parsedate_to_datetime(str(value or "")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None
    return int((time.time() if local_time is None else float(local_time)) - server_time)


def _set_logger(fn) -> None:
    global _LOG
    _LOG = fn if callable(fn) else _default_logger


def _build_upload_success_payload(
    *,
    job_id: str,
    job_name: str,
    job_url: str,
    upload_type: str,
    rel_manifest: List[str],
    main_blend_s3: str,
    blend_path: str,
    packed_addons: Optional[List[object]] = None,
    report_path: str = "",
    elapsed: float = 0.0,
) -> Dict[str, object]:
    """Build the machine-readable success marker consumed by upload smoke tests."""
    upload_type = str(upload_type).upper()
    dependency_file_count = len(rel_manifest) if upload_type == "PROJECT" else 0
    content_file_count = dependency_file_count + 1
    manifest_file_count = content_file_count if upload_type == "PROJECT" else 0
    addon_file_count = len(packed_addons or [])

    return {
        "status": "success",
        "job_id": str(job_id),
        "job_name": str(job_name),
        "job_url": str(job_url),
        "upload_type": upload_type,
        "uploaded_file_count": content_file_count,
        "dependency_file_count": dependency_file_count,
        "manifest_file_count": manifest_file_count,
        "storage_object_count": content_file_count
        + (1 if upload_type == "PROJECT" else 0)
        + addon_file_count,
        "addon_file_count": addon_file_count,
        "main_file": (
            str(main_blend_s3)
            if upload_type == "PROJECT"
            else Path(str(blend_path)).name
        ),
        "report_path": str(report_path),
        "elapsed_sec": round(max(float(elapsed), 0.0), 3),
    }


def _emit_upload_success_payload(payload: Dict[str, object]) -> None:
    print(
        _UPLOAD_RESULT_PREFIX + json.dumps(payload, sort_keys=True),
        flush=True,
    )


def _emit_upload_success_payload_if_requested(
    data: Dict[str, object], payload: Dict[str, object]
) -> None:
    """Emit the automation marker only for an explicitly opted-in harness."""
    if data.get("emit_upload_result") is True:
        _emit_upload_success_payload(payload)


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


def _archive_name_for_display(name: object) -> str:
    return str(name or "").replace("\\", "/")


def _path_basename_cross_platform(path_str: str) -> str:
    normalized = _archive_name_for_display(path_str).rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _farm_zip_unpack_skip_reason(archive_name: object) -> Optional[str]:
    """Return why the farm's ZIP extractor will skip this member, if it will."""
    name = _archive_name_for_display(archive_name)
    if not name:
        return None
    if name.startswith("/"):
        return 'starts with "/"'
    if ".." in name:
        return 'contains consecutive dots ("..")'
    return None


def _farm_unpack_blocked_archive_names(archive_names: Iterable[object]) -> List[str]:
    blocked: List[str] = []
    seen = set()
    for archive_name in archive_names:
        name = _archive_name_for_display(archive_name)
        if name in seen:
            continue
        if _farm_zip_unpack_skip_reason(name):
            blocked.append(name)
            seen.add(name)
    return blocked


def _farm_unpack_preflight_issue(blocked_names: List[str]) -> str:
    first = blocked_names[0] if blocked_names else "unknown"
    extra = "" if len(blocked_names) == 1 else f" and {len(blocked_names) - 1} more"
    return (
        "ZIP upload cannot use file names with consecutive dots or leading slashes: "
        f"{first}{extra}"
    )


def _format_farm_unpack_blocking_message(blocked_names: List[str]) -> str:
    listed = blocked_names[:8]
    lines = "\n".join(f"  - {name}" for name in listed)
    if len(blocked_names) > len(listed):
        lines += f"\n  - ... and {len(blocked_names) - len(listed)} more"

    subject = (
        "this file path in the ZIP"
        if len(blocked_names) == 1
        else "these file paths in the ZIP"
    )
    entry_label = "Blocked entry" if len(blocked_names) == 1 else "Blocked entries"
    return (
        f"Submission cancelled: the render farm cannot unpack {subject}.\n\n"
        'ZIP entries that contain consecutive dots ("..") or start with "/" are '
        "rejected by the farm extractor. Rename the file(s) below to remove "
        "consecutive dots, save the .blend, then submit again.\n\n"
        f"{entry_label}:\n"
        f"{lines}"
    )


def _farm_unpack_blocked_zip_members(zip_path: Path) -> List[str]:
    with zipfile.ZipFile(zip_path, "r") as archive:
        return _farm_unpack_blocked_archive_names(archive.namelist())


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


def _normalize_frame_step(frame_step: object) -> int:
    try:
        return max(1, abs(int(frame_step or 1)))
    except (TypeError, ValueError):
        return 1


def _build_render_tasks(
    start_frame: int,
    end_frame: int,
    render_order: str,
    frame_step: object = 1,
) -> List[int]:
    """
    Build task order based on requested render order.

    LINEAR: start -> end in ascending order.
    TEMPORAL_REFINE: render with the largest clean power-of-two stride
    the frame count supports, then halve the stride until all frames are filled.

    Example with start=1, end=10:
    TEMPORAL_REFINE: [1, 9, 5, 3, 7, 2, 4, 6, 8, 10]
    """
    start = int(start_frame)
    end = int(end_frame)
    step = _normalize_frame_step(frame_step)
    if end < start:
        return []

    frame_numbers = list(range(start, end + 1, step))

    mode = str(render_order or "LINEAR").upper()
    if mode == "LINEAR":
        return frame_numbers

    if mode in {"TEMPORAL_REFINE", "PROGRESSIVE_STEPPING"}:
        tasks: List[int] = []
        seen: set[int] = set()

        def _add(frame: int) -> None:
            if start <= frame <= end and frame not in seen:
                seen.add(frame)
                tasks.append(frame)

        frame_count = len(frame_numbers)
        stride = 1
        while stride * 2 <= frame_count - 1:
            stride *= 2

        while stride >= 1:
            for index in range(0, frame_count, stride):
                _add(frame_numbers[index])
            stride //= 2
        return tasks

    return frame_numbers


def _build_settings_schema_registration(
    data: Dict[str, object],
) -> Optional[Dict[str, object]]:
    """Build the optional schema envelope piggybacked on job registration."""
    schema = data.get("settings_schema")
    schema_key = str(data.get("settings_schema_key") or "")
    if not isinstance(schema, dict) or not schema or not schema_key:
        return None

    registration: Dict[str, object] = {
        "schema_key": schema_key,
        "blender_version": str(schema.get("blender_version", "") or ""),
        "schema": schema,
    }
    try:
        encoded_size = len(
            json.dumps(registration, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError, UnicodeError):
        return None
    if encoded_size > _MAX_SETTINGS_SCHEMA_BYTES:
        return None
    return registration


def _missing_project_identity_fields(project: dict | None) -> list[str]:
    """Return required project fields that are missing/blank."""
    if not isinstance(project, dict):
        return ["id", "organization_id", "sqid"]
    missing = []
    for key in ("id", "organization_id", "sqid"):
        value = project.get(key)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(key)
    return missing


def _parse_project_storage_payload(payload: dict | None) -> tuple[dict, str]:
    """
    Parse project_storage list payload and return (storage_record, bucket_name).
    """
    if not isinstance(payload, dict):
        raise RuntimeError("storage API returned a non-object payload")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise RuntimeError(
            "no accessible project_storage records found for this project "
            "(organization membership may be missing)"
        )

    first = items[0]
    if not isinstance(first, dict):
        raise RuntimeError("storage API returned an invalid record shape")

    bucket = str(first.get("bucket_name") or "").strip()
    if not bucket:
        raise RuntimeError("project_storage record is missing bucket_name")
    return first, bucket


def _response_error_message(response) -> str:
    if response is None:
        return ""

    body = ""
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if isinstance(message, str) and message.strip():
            body = message.strip()
        elif payload:
            body = json.dumps(payload, ensure_ascii=False)

    if not body:
        try:
            body = str(response.text or "").strip()
        except Exception:
            body = ""

    if len(body) > 800:
        body = body[:800] + "..."
    return body


def _request_exception_details(exc: requests.RequestException) -> str:
    details = str(exc)
    response = getattr(exc, "response", None)
    message = _response_error_message(response)
    if message:
        details = f"{details}\nServer response: {message}"
    return details


# Utilities imported after bootstrap
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


# Worker bootstrap (safe to import)


def _load_handoff_from_argv(argv: List[str]) -> Dict[str, object]:
    if len(argv) < 2:
        raise RuntimeError(
            "submit_worker.py was launched without a handoff JSON path.\n"
            "This script should be run as a subprocess by the add-on.\n"
            "Example: submit_worker.py /path/to/handoff.json"
        )
    handoff_path = Path(argv[1]).resolve(strict=True)
    try:
        data = json.loads(handoff_path.read_text("utf-8"))
    finally:
        try:
            handoff_path.unlink()
        except OSError:
            pass
    return data


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
    worker_utils.apply_debug_handoff(data)

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
    fetch_project_storage = worker_utils.fetch_project_storage

    bat_utils = importlib.import_module(f"{pkg_name}.utils.bat_utils")
    pack_blend = bat_utils.pack_blend
    trace_dependencies = bat_utils.trace_dependencies
    compute_project_root = bat_utils.compute_project_root

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
        "fetch_project_storage": fetch_project_storage,
        "pack_blend": pack_blend,
        "trace_dependencies": trace_dependencies,
        "compute_project_root": compute_project_root,
        "cloud_files": cloud_files,
        "create_logger": create_logger,
        "run_rclone": run_rclone,
        "ensure_rclone": ensure_rclone,
        "DiagnosticReport": DiagnosticReport,
        "generate_test_report": generate_test_report,
    }


@dataclass
class _SubmitContext:
    data: Dict[str, object]
    mods: Dict[str, object]
    t_start: float
    proj: Dict[str, object]
    logger: Any
    session: requests.Session
    preflight_ok: bool = True
    preflight_issues: List[str] = field(default_factory=list)
    preflight_user_override: Optional[bool] = None
    headers: Dict[str, str] = field(default_factory=dict)
    rclone_bin: Any = None
    blend_path: str = ""
    use_project: bool = False
    automatic_project_path: bool = True
    custom_project_path_str: str = ""
    job_id: str = ""
    test_mode: bool = False
    no_submit: bool = False
    render_order: str = "LINEAR"
    frame_step_val: int = 1
    render_tasks: List[int] = field(default_factory=list)
    effective_end_frame: int = 0
    zip_file: Optional[Path] = None
    filelist: Optional[Path] = None
    org_id: str = ""
    project_sqid: str = ""
    project_name: str = ""
    report: Any = None
    rel_manifest: List[str] = field(default_factory=list)
    dependency_total_size: int = 0
    required_storage: int = 0
    common_path: str = ""
    main_blend_s3: str = ""
    project_root_str: str = ""
    phase_timings: Dict[str, Dict[str, object]] = field(default_factory=dict)
    storage_future: Optional[Future] = None
    storage_thread: Optional[threading.Thread] = None
    update_future: Optional[Future] = None
    update_thread: Optional[threading.Thread] = None


def _record_phase_timing(
    ctx: _SubmitContext,
    phase: str,
    duration_ms: float,
    **details: object,
) -> None:
    """Persist and optionally log a monotonic phase duration.

    Detail values are deliberately bounded scalars so the structured record
    cannot accidentally absorb request bodies, credentials, or large IDs.
    """
    entry: Dict[str, object] = {
        "duration_ms": round(max(0.0, float(duration_ms)), 3),
    }
    for key, value in details.items():
        if isinstance(value, bool):
            entry[str(key)] = value
        elif isinstance(value, (int, float)):
            entry[str(key)] = round(float(value), 3)
        elif value is not None:
            entry[str(key)] = str(value)[:80]

    phase_timings = getattr(ctx, "phase_timings", None)
    if not isinstance(phase_timings, dict):
        phase_timings = {}
        setattr(ctx, "phase_timings", phase_timings)
    phase_timings[str(phase)] = entry

    set_metadata = getattr(getattr(ctx, "report", None), "set_metadata", None)
    if callable(set_metadata):
        set_metadata(
            "phase_timings",
            {name: dict(values) for name, values in phase_timings.items()},
        )

    if _debug_enabled and _debug_enabled():
        _LOG(
            _PHASE_TIMING_PREFIX
            + json.dumps(
                {"phase": str(phase), **entry},
                sort_keys=True,
            )
        )


def _record_archive_rclone_timings(ctx: _SubmitContext, result: object) -> None:
    """Record rclone's process and post-byte-count finalization boundaries."""
    if not isinstance(result, dict):
        return

    process_seconds = result.get("process_elapsed_time")
    if isinstance(process_seconds, (int, float)):
        reported_seconds = result.get("reported_bytes_complete_time")
        _record_phase_timing(
            ctx,
            "archive_upload",
            float(process_seconds) * 1000.0,
            reported_bytes_complete_ms=(
                float(reported_seconds) * 1000.0
                if isinstance(reported_seconds, (int, float))
                else None
            ),
        )

    finalization_seconds = result.get("finalization_time")
    if isinstance(finalization_seconds, (int, float)):
        _record_phase_timing(
            ctx,
            "archive_finalization",
            float(finalization_seconds) * 1000.0,
            boundary="reported_bytes_complete_to_process_exit",
        )


def _preflight(ctx: _SubmitContext) -> None:
    data = ctx.data
    mods = ctx.mods
    logger = ctx.logger
    session = ctx.session

    # Early preflight checks
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
        check_clock=False,
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

    ctx.preflight_ok = preflight_ok
    ctx.preflight_issues = preflight_issues
    ctx.preflight_user_override = _preflight_user_override


def _ensure_farm_ready(ctx: _SubmitContext) -> None:
    data = ctx.data
    mods = ctx.mods
    proj = ctx.proj
    logger = ctx.logger
    session = ctx.session
    preflight_ok = ctx.preflight_ok
    preflight_issues = ctx.preflight_issues
    _preflight_user_override = ctx.preflight_user_override
    is_blend_saved = mods["is_blend_saved"]
    DiagnosticReport = mods["DiagnosticReport"]
    headers = {"Authorization": data["user_token"]}
    test_mode = bool(data.get("test_mode", False))
    no_submit = bool(data.get("no_submit", False))
    missing_project_fields = _missing_project_identity_fields(proj)
    if missing_project_fields:
        logger.fatal("Selected project metadata is incomplete. Refresh projects and try again.")
    farm_status_started_at = time.perf_counter()
    if not test_mode and not no_submit:
        _coordinator(ctx).tool("render_capacity_get", {"organization_id": proj["organization_id"]})
    farm_status_duration_ms = (time.perf_counter() - farm_status_started_at) * 1000.0

    # Local paths / settings
    blend_path: str = data["blend_path"]

    use_project: bool = bool(data["use_project_upload"])
    automatic_project_path: bool = bool(data["automatic_project_path"])
    custom_project_path_str: str = data["custom_project_path"]
    job_id: str = data["job_id"]

    render_order = str(data.get("render_order", "LINEAR"))
    frame_step_val = _normalize_frame_step(data.get("frame_stepping_size", 1))
    render_tasks = _build_render_tasks(
        int(data["start_frame"]),
        int(data["end_frame"]),
        render_order,
        frame_step_val,
    )
    effective_end_frame = (
        max(render_tasks) if render_tasks else int(data["end_frame"])
    )

    zip_file = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist = Path(tempfile.gettempdir()) / f"{job_id}.txt"

    org_id = proj["organization_id"]
    project_sqid = proj["sqid"]
    project_name = proj["name"]

    # Wait until .blend is fully written
    is_blend_saved(
        blend_path,
        logger_instance=logger,
        expected_signature=data.get("blend_file_signature"),
    )

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

    _source_unpack_blocked: List[str] = []
    if not use_project:
        _source_unpack_blocked = _farm_unpack_blocked_archive_names(
            [_path_basename_cross_platform(blend_path)]
        )
        if _source_unpack_blocked:
            preflight_issues.append(_farm_unpack_preflight_issue(_source_unpack_blocked))

    # Record preflight results and environment into the diagnostic report
    report.record_preflight(
        preflight_ok and not _source_unpack_blocked,
        preflight_issues,
        _preflight_user_override,
    )
    report.set_environment("transfer_mode", "oauth-authorized-receipt")

    if _source_unpack_blocked:
        report.set_metadata("farm_unpack_blocked_entries", _source_unpack_blocked)
        report.set_status("failed")
        logger.fatal(_format_farm_unpack_blocking_message(_source_unpack_blocked))

    ctx.headers = headers
    ctx.blend_path = blend_path
    ctx.use_project = use_project
    ctx.automatic_project_path = automatic_project_path
    ctx.custom_project_path_str = custom_project_path_str
    ctx.job_id = job_id
    ctx.test_mode = test_mode
    ctx.no_submit = no_submit
    ctx.render_order = render_order
    ctx.frame_step_val = frame_step_val
    ctx.render_tasks = render_tasks
    ctx.effective_end_frame = effective_end_frame
    ctx.zip_file = zip_file
    ctx.filelist = filelist
    ctx.org_id = org_id
    ctx.project_sqid = project_sqid
    ctx.project_name = project_name
    ctx.report = report
    _record_phase_timing(
        ctx,
        "farm_status",
        farm_status_duration_ms,
        storage_prefetch_started=ctx.storage_future is not None,
    )


def _run_test_mode_report(
    ctx: _SubmitContext,
    *,
    upload_type: str,
    dep_paths: List[Path],
    missing_set: set,
    unreadable_dict: Dict[Path, str],
    project_root: Path,
    same_drive_deps: List[Path],
    cross_drive_deps: List[Path],
    has_issues: bool,
) -> None:
    data = ctx.data
    mods = ctx.mods
    logger = ctx.logger
    report = ctx.report
    generate_test_report = mods["generate_test_report"]
    shorten_path = mods["shorten_path"]
    open_folder = mods["open_folder"]

    if ctx.test_mode:
        by_ext: Dict[str, int] = {}
        total_size = 0
        for dep in dep_paths:
            ext = dep.suffix.lower() if dep.suffix else "(no ext)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            if dep.exists() and dep.is_file():
                try:
                    total_size += dep.stat().st_size
                except OSError:
                    pass

        _, test_report_path = generate_test_report(
            blend_path=ctx.blend_path,
            dep_paths=dep_paths,
            missing_set=missing_set,
            unreadable_dict=unreadable_dict,
            project_root=project_root,
            same_drive_deps=same_drive_deps,
            cross_drive_deps=cross_drive_deps,
            upload_type=upload_type,
            addon_dir=str(data["addon_dir"]),
            mode="test",
            format_size_fn=_format_size,
        )
        logger.test_report(
            blend_path=ctx.blend_path,
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
            upload_type=upload_type,
            report_path=str(test_report_path) if test_report_path else None,
            shorten_fn=shorten_path,
        )
        _safe_input("\nPress Enter to close.", "")
        sys.exit(0)

    if not has_issues:
        return

    answer = logger.ask_choice(
        "Some dependencies have problems. Continue anyway?",
        [
            ("y", "Continue", "Proceed with submission"),
            ("n", "Cancel", "Cancel and close"),
            (
                "r",
                "Open diagnostic reports",
                "Open the diagnostic reports folder",
            ),
        ],
        default="y",
    )
    report.record_user_choice(
        "Dependency issues found",
        answer,
        options=["Continue", "Cancel", "Open reports"],
    )
    if answer == "r":
        logger.report_info(str(report.get_path()))
        open_folder(str(report.get_reports_dir()), logger_instance=logger)
        answer = logger.ask_choice(
            "Continue with submission?",
            [
                ("y", "Continue", "Proceed with submission"),
                ("n", "Cancel", "Cancel and close"),
            ],
            default="y",
        )
        report.record_user_choice(
            "Continue after viewing reports?",
            answer,
            options=["Continue", "Cancel"],
        )
    if answer != "y":
        report.set_status("cancelled")
        sys.exit(1)


def _trace_and_pack(ctx: _SubmitContext) -> None:
    data = ctx.data
    mods = ctx.mods
    logger = ctx.logger
    report = ctx.report
    shorten_path = mods["shorten_path"]
    pack_blend = mods["pack_blend"]
    trace_dependencies = mods["trace_dependencies"]
    compute_project_root = mods["compute_project_root"]
    blend_path = ctx.blend_path
    use_project = ctx.use_project
    automatic_project_path = ctx.automatic_project_path
    custom_project_path_str = ctx.custom_project_path_str
    test_mode = ctx.test_mode
    no_submit = ctx.no_submit
    zip_file = ctx.zip_file
    filelist = ctx.filelist

    # Stage 1: Tracing — discover dependencies
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
        # Probe accessibility without fully hydrating every dependency. rclone
        # opens files only when they actually need transfer, so warm PROJECT
        # submissions can skip unchanged cloud placeholders without rereading
        # the entire project first.
        dep_paths, missing_set, unreadable_dict, raw_usages, optional_set = trace_dependencies(
            Path(blend_path), logger=logger, hydrate=False, diagnostic_report=report
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
        common_path = str(project_root).replace("\\", "/")
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

        # Build warning text for issues
        missing_files_list = [str(p) for p in sorted(missing_set)]
        unreadable_files_list = [
            (str(p), err)
            for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))
        ]
        absolute_path_files_list = [str(p) for p in sorted(absolute_path_deps)]
        has_issues = bool(
            cross_drive_deps
            or missing_files_list
            or unreadable_files_list
            or absolute_path_deps
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

            if (
                (missing_files_list or unreadable_files_list)
                and not absolute_path_deps
                and not cross_drive_deps
            ):
                warning_parts.append("Missing or unreadable files excluded.")

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
            shorten_fn=shorten_path,
            automatic_project_path=automatic_project_path,
        )
        report.complete_stage("trace")

        _run_test_mode_report(
            ctx,
            upload_type="PROJECT",
            dep_paths=dep_paths,
            missing_set=missing_set,
            unreadable_dict=unreadable_dict,
            project_root=project_root,
            same_drive_deps=same_drive_deps,
            cross_drive_deps=cross_drive_deps,
            has_issues=has_issues,
        )

        # Stage 2: Manifest — map dependencies into project structure
        logger.stage_header(
            2,
            "Building manifest",
            "Mapping dependencies into the project structure",
        )

        report.start_stage("pack")

        # Build file map from pre-expanded OK files (no filesystem I/O needed)
        fmap = pack_blend(
            blend_path,
            target="",
            method="PROJECT",
            project_path=common_path,
            pre_traced_deps=list(ok_files_set),
        )

        abs_blend = _norm_abs_for_detection(blend_path)
        rel_manifest: List[str] = []
        dependency_total_size = 0  # Track dependency size separately for progress bar

        total_files = len(fmap)
        logger.pack_start()

        ok_count = 0
        pack_idx = 0
        for src_path in fmap:
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
                report.add_pack_entry(src_str, rel, file_size=size, status="ok")

        # Calculate total required storage (dependencies + main blend)
        required_storage = dependency_total_size
        try:
            required_storage += os.path.getsize(blend_path)
        except Exception:
            pass

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
            ok_count=ok_count,
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

        _run_test_mode_report(
            ctx,
            upload_type="ZIP",
            dep_paths=dep_paths,
            missing_set=missing_set,
            unreadable_dict=unreadable_dict,
            project_root=project_root,
            same_drive_deps=same_drive_deps,
            cross_drive_deps=cross_drive_deps,
            has_issues=has_zip_issues,
        )

        # Stage 2: Packing (Zip upload)
        logger.stage_header(
            2,
            "Packing",
            "Preparing and writing a ZIP archive with all dependencies",
        )
        report.start_stage("pack")
        pack_stage_started = time.perf_counter()

        abs_blend_norm = _norm_abs_for_detection(blend_path)

        _zip_started = False
        _zip_dep_size = 0
        _zip_done_data = {}

        def _ensure_zip_started(total, source_bytes):
            nonlocal _zip_started
            if not _zip_started:
                logger.zip_start(total, source_bytes)
                _zip_started = True

        def _on_zip_progress(
            idx,
            total,
            arcname,
            file_bytes_done,
            file_size,
            source_bytes_done,
            source_bytes,
            method,
            file_elapsed,
            total_elapsed,
        ):
            _ensure_zip_started(total, source_bytes)
            logger.zip_progress(
                idx,
                total,
                arcname,
                file_bytes_done,
                file_size,
                source_bytes_done,
                source_bytes,
                method,
                file_elapsed,
                total_elapsed,
            )

        def _on_zip_stats(
            idx,
            total,
            arcname,
            source_bytes,
            archive_bytes,
            method,
            elapsed,
        ):
            nonlocal _zip_dep_size
            _zip_dep_size += source_bytes
            _ensure_zip_started(total, 0)
            logger.zip_entry(
                idx,
                total,
                arcname,
                source_bytes,
                archive_bytes,
                method,
                elapsed,
            )
            # Log to diagnostic report
            report.add_pack_entry(
                arcname,
                arcname,
                file_size=source_bytes,
                status="ok",
                archive_size=archive_bytes,
                method=method,
                elapsed_seconds=elapsed,
            )

        def _on_zip_done(zippath, total_files, source_bytes, elapsed):
            _zip_done_data.update(
                zippath=zippath,
                total_files=total_files,
                source_bytes=source_bytes,
                archive_write_elapsed=elapsed,
            )

        def _noop_emit(msg):
            pass

        pack_blend(
            abs_blend_norm,
            str(zip_file),
            method="ZIP",
            project_path=project_root_str,
            pre_traced_deps=raw_usages,
            zip_emit_fn=_noop_emit,
            zip_done_cb=_on_zip_done,
            zip_progress_cb=_on_zip_progress,
            zip_stats_cb=_on_zip_stats,
        )

        pack_total_elapsed = max(0.0, time.perf_counter() - pack_stage_started)
        if _zip_done_data:
            archive_path = Path(_zip_done_data["zippath"])
            archive_write_elapsed = float(
                _zip_done_data["archive_write_elapsed"]
            )
            archive_size = archive_path.stat().st_size
            logger.zip_done(
                str(archive_path),
                int(_zip_done_data["total_files"]),
                source_bytes=int(_zip_done_data["source_bytes"]),
                archive_bytes=archive_size,
                preparation_elapsed=max(
                    0.0, pack_total_elapsed - archive_write_elapsed
                ),
                archive_write_elapsed=archive_write_elapsed,
                total_elapsed=pack_total_elapsed,
            )
            report.set_zip_pack_summary(
                source_bytes=int(_zip_done_data["source_bytes"]),
                archive_bytes=archive_size,
                preparation_elapsed=max(
                    0.0, pack_total_elapsed - archive_write_elapsed
                ),
                archive_write_elapsed=archive_write_elapsed,
                total_elapsed=pack_total_elapsed,
            )

        if not zip_file.exists():
            report.set_status("failed")
            logger.fatal("Archive not created. Check disk space and permissions.")

        _blocked_zip_members = _farm_unpack_blocked_zip_members(zip_file)
        if _blocked_zip_members:
            report.set_metadata("farm_unpack_blocked_entries", _blocked_zip_members)
            report.set_status("failed")
            logger.fatal(_format_farm_unpack_blocking_message(_blocked_zip_members))

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
            except OSError:
                pass
        _safe_input("\nPress Enter to close.", "")
        sys.exit(0)

    ctx.rel_manifest = rel_manifest
    ctx.dependency_total_size = dependency_total_size if use_project else 0
    ctx.required_storage = required_storage
    ctx.common_path = common_path
    ctx.main_blend_s3 = main_blend_s3
    ctx.project_root_str = project_root_str if not use_project else ""


def _start_storage_prefetch(ctx: _SubmitContext) -> None:
    """Fetch short-lived R2 credentials while dependency packing is running."""
    if ctx.no_submit or ctx.test_mode or ctx.storage_future is not None:
        return

    data = ctx.data
    mods = ctx.mods

    future: Future = Future()

    def _fetch() -> None:
        if not future.set_running_or_notify_cancel():
            return
        started_at = time.perf_counter()
        session = None
        result: Optional[tuple[object, float]] = None
        failure: Optional[BaseException] = None
        try:
            session = mods["requests_retry_session"]()
            payload = mods["fetch_project_storage"](
                session,
                data["pocketbase_url"],
                data["user_token"],
                data["project"]["id"],
            )
            result = (payload, (time.perf_counter() - started_at) * 1000.0)
        except BaseException as exc:
            failure = exc
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
        if failure is not None:
            future.set_exception(failure)
        else:
            future.set_result(result)

    # A daemon is deliberate: if tracing aborts while the bounded retrying HTTP
    # request is in flight, it must not keep the failed submit process open.
    # On the normal path _project_storage_payload waits for the full existing
    # retry policy, preserving the synchronous behavior this replaced.
    thread = threading.Thread(
        target=_fetch,
        name="sulu-storage-prefetch",
        daemon=True,
    )
    ctx.storage_future = future
    ctx.storage_thread = thread
    thread.start()


def _cancel_storage_prefetch(ctx: _SubmitContext) -> None:
    """Detach optional prefetch work without delaying process shutdown."""
    future = ctx.storage_future
    ctx.storage_future = None
    ctx.storage_thread = None
    if future is not None:
        future.cancel()


def _version_numbers(value: object) -> tuple[int, int, int]:
    numbers = [int(part) for part in re.findall(r"\d+", str(value or ""))[:3]]
    return tuple((numbers + [0, 0, 0])[:3])


def _start_update_discovery(ctx: _SubmitContext) -> None:
    """Start release discovery for packaged builds only."""
    if ctx.update_future is not None:
        return
    if str(ctx.data.get("addon_build_channel") or "").lower() != "release":
        return

    future: Future = Future()
    current_version = _version_numbers(ctx.data.get("addon_version"))

    def _fetch() -> None:
        if not future.set_running_or_notify_cancel():
            return
        available = False
        failure: Optional[BaseException] = None
        try:
            with requests.Session() as session:
                response = session.get(
                    "https://api.github.com/repos/"
                    "Superluminal-Studios/sulu-blender-addon/releases/latest",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "Sulu-Blender-Addon/update-check",
                    },
                    timeout=5,
                )
                if response.status_code == 200:
                    latest = response.json().get("tag_name")
                    available = _version_numbers(latest) > current_version
        except BaseException as exc:
            failure = exc
        if failure is not None:
            future.set_exception(failure)
        else:
            future.set_result(available)

    thread = threading.Thread(
        target=_fetch,
        name="sulu-update-discovery",
        daemon=True,
    )
    ctx.update_future = future
    ctx.update_thread = thread
    thread.start()


def _show_update_before_submit(ctx: _SubmitContext) -> None:
    """Offer an available release before submission work begins."""
    future = ctx.update_future
    if future is None:
        return
    ctx.update_future = None
    ctx.update_thread = None
    try:
        # The request itself has a five-second timeout. This outer bound also
        # prevents a broken discovery thread from holding submission forever.
        available = bool(future.result(timeout=6))
    except BaseException:
        return
    if not available:
        return

    try:
        answer = ctx.logger.version_update(
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
            ctx.logger.info_exit("Install the new version, then restart Blender.")
    except SystemExit:
        raise
    except Exception:
        # Release discovery is optional and happens after job receipt. A
        # notification integration failure cannot turn success into failure.
        return


def _cancel_update_discovery(ctx: _SubmitContext) -> None:
    future = ctx.update_future
    ctx.update_future = None
    ctx.update_thread = None
    if future is not None:
        future.cancel()


def _project_storage_payload(ctx: _SubmitContext) -> object:
    """Return prefetched storage data, falling back to the synchronous path."""
    wait_started_at = time.perf_counter()
    future = ctx.storage_future
    thread = ctx.storage_thread
    ctx.storage_future = None
    ctx.storage_thread = None

    if future is None:
        started_at = time.perf_counter()
        payload = ctx.mods["fetch_project_storage"](
            ctx.session,
            ctx.data["pocketbase_url"],
            ctx.data["user_token"],
            ctx.data["project"]["id"],
        )
        _record_phase_timing(
            ctx,
            "storage_credentials",
            (time.perf_counter() - started_at) * 1000.0,
            overlapped=False,
        )
        return payload

    payload, fetch_ms = future.result()
    if thread is not None:
        thread.join(timeout=0)
    _record_phase_timing(
        ctx,
        "storage_credentials",
        fetch_ms,
        overlapped=True,
        critical_path_wait_ms=(time.perf_counter() - wait_started_at) * 1000.0,
    )
    return payload


def _coordinator(ctx):
    if getattr(ctx, "coordinator_client", None) is None:
        module = importlib.import_module(f"{ctx.mods['pkg_name']}.transfers.submit.coordinator_client")
        identity = module.recovery_identity(ctx.data)

        def confirm(tool, impact):
            labels = {
                "render_upload_prepare": "Reserve these exact render inputs for upload?",
                "render_upload_finalize": "Finalize and verify the uploaded render inputs?",
                "render_job_submit": "Submit this render using the quoted cost and settings?",
            }
            # Impact is the sanitized semantic DTO. Never show request headers,
            # raw dependency errors, transfer URLs, or identity assertions.
            explanation = labels.get(tool, "Confirm render action?")
            safe_impact = json.dumps(impact, ensure_ascii=False, sort_keys=True)[:8000]
            return ctx.logger.ask_choice(explanation + "\n" + safe_impact,
                                         [("y", "Confirm", "Continue"), ("n", "Cancel", "Do not commit")],
                                         default="n") == "y"

        ctx.coordinator_client = module.RenderCoordinatorClient(
            ctx.data["pocketbase_url"], ctx.data["user_token"], ctx.session,
            Path(ctx.data["addon_dir"]) / "reports" / ("render-recovery-" + identity + ".json"),
            identity, confirm,
        )
    return ctx.coordinator_client


def _receipt_input_files(ctx):
    """Preserve ZIP/project packaging but expose logical names only."""
    module = importlib.import_module(f"{ctx.mods['pkg_name']}.transfers.submit.coordinator_client")
    files = {}
    if ctx.use_project:
        main = module.logical_name(_nfc(_s3key_clean(ctx.main_blend_s3)))
        files[main] = Path(ctx.blend_path)
        root = Path(ctx.common_path)
        for relative in ctx.rel_manifest:
            logical = module.logical_name(_nfc(relative.replace("\\", "/")))
            candidate = root.joinpath(*logical.split("/"))
            if logical in files and files[logical].resolve() != candidate.resolve():
                raise ValueError("Duplicate render input name")
            files[logical] = candidate
        mode = {"input_mode": "project", "main_file": main}
    else:
        main = module.logical_name(_nfc(Path(ctx.blend_path).relative_to(ctx.project_root_str).as_posix()))
        archive = "render-input.zip"
        files[archive] = Path(ctx.zip_file)
        mode = {"input_mode": "zip", "main_file": main, "archive_file": archive}
    addons_path = ctx.data.get("packed_addons_path")
    addon_names = []
    if ctx.data.get("packed_addons") and addons_path:
        addon_root = Path(addons_path)
        for candidate in sorted(addon_root.rglob("*")):
            if candidate.is_file():
                logical = module.logical_name("addons/" + candidate.relative_to(addon_root).as_posix())
                if logical in files:
                    raise ValueError("Duplicate render input name")
                files[logical] = candidate
                if candidate.suffix.lower() != ".zip":
                    raise ValueError("Packed add-ons must be portable ZIP archives")
                addon_names.append(logical)
    if addon_names:
        mode["packed_addons"] = addon_names
    manifest = []
    for name, source in files.items():
        if not source.is_file() or source.is_symlink():
            raise ValueError("A render input is unavailable or is a symbolic link")
        manifest.append({"name": name, "size": source.stat().st_size})
    return files, manifest, mode


def _upload(ctx: _SubmitContext) -> None:
    started = time.perf_counter()
    client = _coordinator(ctx)
    completed = client.completed("render_upload_finalize")
    if completed:
        ctx.upload_receipt = completed["upload_receipt"]
        return
    files, manifest, mode = _receipt_input_files(ctx)
    ctx.logger.stage_header(3, "Uploading", "Transferring verified render inputs")
    ctx.report.start_stage("upload")
    preparation = {
        "organization_id": ctx.org_id, "project_id": ctx.proj["id"], "files": manifest, **mode,
    }
    prepared = client.mutate("render_upload_prepare", preparation)
    descriptors = prepared.get("files")
    if not isinstance(descriptors, list) or len(descriptors) != len(files):
        raise ValueError("Upload preparation did not cover every input")
    expected = {item["name"]: item["size"] for item in manifest}
    if {item.get("name"): item.get("size") for item in descriptors} != expected:
        raise ValueError("Upload preparation did not match the intended inputs")
    expires = float(prepared.get("expires_at", 0))

    def renew():
        nonlocal expires
        if time.time() < expires - 120:
            return
        # Renewal is the same immutable manifest/session, with its own durable
        # command. A failed response resumes that renewal before doing more IO.
        renewed = client.mutate("render_upload_prepare", {
            **preparation, "upload_session": prepared["upload_session"],
        }, stage="render_upload_renew_" + str(int(expires)))
        if renewed.get("upload_session") != prepared["upload_session"]:
            raise ValueError("Upload renewal changed the session")
        expires = float(renewed["expires_at"])
    ctx.logger.upload_start(len(files))
    for index, descriptor in enumerate(descriptors, 1):
        ctx.logger.upload_step(index, len(files), descriptor["name"])
        client.upload_file(files[descriptor["name"]], descriptor, before_chunk=renew)
        ctx.logger._transfer_total = descriptor["size"]
        ctx.logger.upload_complete("Input uploaded")
    finalized = client.mutate("render_upload_finalize", {
        "organization_id": ctx.org_id, "upload_session": prepared["upload_session"],
    })
    receipt = finalized.get("upload_receipt")
    if not isinstance(receipt, str) or not receipt:
        raise ValueError("Upload finalization did not return a receipt")
    ctx.upload_receipt = receipt
    ctx.required_storage = sum(item["size"] for item in manifest)
    ctx.report.complete_stage("upload")
    _record_phase_timing(ctx, "upload", (time.perf_counter() - started) * 1000, outcome="completed")


def _register_job(ctx: _SubmitContext) -> None:
    started = time.perf_counter()
    data = ctx.data
    client = _coordinator(ctx)
    registration = _build_settings_schema_registration(data)
    if registration:
        client.register_schema(registration)
    metadata = dict(data.get("scene_metadata") or {})
    if registration:
        # The independently registered immutable schema is not duplicated in
        # each template; scene settings and actual overrides remain intact.
        metadata.pop("settings_schema", None)
    coordinator_started = time.perf_counter()
    template = {
        "name": data["job_name"], "blender_version": data["blender_version"],
        "frame_start": int(data["start_frame"]), "frame_end": ctx.effective_end_frame,
        "frame_step": ctx.frame_step_val, "render_order": ctx.render_order, "batch_size": 1,
        "image_format": data["image_format"],
        "use_scene_image_format": bool(data.get("use_scene_image_format")) or str(data.get("image_format", "")).upper() == "SCENE",
        "render_engine": data["render_engine"], "scene_metadata": metadata,
        "zip": not ctx.use_project, "ignore_errors": bool(data.get("ignore_errors")),
        "use_bserver": bool(data.get("use_bserver")), "packed_addons": data.get("packed_addons") or [],
    }
    if data.get("settings_schema_key"):
        template["settings_schema_key"] = str(data["settings_schema_key"])
    request = {"organization_id": ctx.org_id, "project_id": ctx.proj["id"],
               "upload_receipt": ctx.upload_receipt, "template": template}
    result = client.completed("render_job_submit")
    if result is None:
        # If acceptance was committed but its response was lost, the receipt
        # may already be claimed. Recover the durable command before quoting
        # that receipt again. A missing/expired quote is safe to replace only
        # after the server explicitly says the command is still uncommitted.
        if "render_job_submit" in client.journal:
            try:
                result = client.mutate("render_job_submit", request)
            except Exception as exc:
                if getattr(exc, "code", "") != "QUOTE_EXPIRED":
                    raise
        if result is None:
            quote = client.tool("render_job_quote", request)
            result = client.mutate("render_job_submit", {**request, "quote_token": quote["quote_token"]})
    new_job = result.get("job_id")
    if not isinstance(new_job, str) or not new_job:
        raise ValueError("Completed render submission did not return its job reference")
    # Only the backend allocates execution identity. Keep the journal's local
    # intent stable, then hand the actual new job ID to the existing viewer.
    ctx.job_id = new_job
    data["job_id"] = new_job
    data["render_coordinator"] = True
    _record_phase_timing(ctx, "registration", (time.perf_counter() - started) * 1000,
                         schema_payload_bytes=len(json.dumps(registration).encode()) if registration else 0,
                         coordinator_ms=(time.perf_counter() - coordinator_started) * 1000,
                         outcome="completed")


def _run_integrated_download(data: Dict[str, object], pkg_name: str) -> str:
    """Hand a successful submission to the downloader in this terminal."""
    download_worker = importlib.import_module(
        f"{pkg_name}.transfers.download.download_worker"
    )
    return download_worker.run_download(
        data,
        clear_console=False,
        integrated=True,
    )


def _finish(ctx: _SubmitContext) -> None:
    data = ctx.data
    mods = ctx.mods
    logger = ctx.logger
    report = ctx.report
    t_start = ctx.t_start
    use_project = ctx.use_project
    project_sqid = ctx.project_sqid
    rel_manifest = ctx.rel_manifest
    main_blend_s3 = ctx.main_blend_s3
    blend_path = ctx.blend_path
    open_folder = mods["open_folder"]

    # Finalize the diagnostic report
    report.finalize()

    elapsed = time.perf_counter() - t_start
    job_url = f"https://superlumin.al/p/{project_sqid}/farm/jobs/{data['job_id']}"
    upload_result = _build_upload_success_payload(
        job_id=data["job_id"],
        job_name=data["job_name"],
        job_url=job_url,
        upload_type="PROJECT" if use_project else "ZIP",
        rel_manifest=rel_manifest,
        main_blend_s3=main_blend_s3,
        blend_path=blend_path,
        packed_addons=data.get("packed_addons") or [],
        report_path=str(report.get_reports_dir()),
        elapsed=elapsed,
    )
    _emit_upload_success_payload_if_requested(data, upload_result)

    continue_to_download = bool(data.get("download_after_submit"))
    selection = "c"
    try:
        selection = logger.logo_end(
            job_id=data["job_id"],
            elapsed=elapsed,
            job_url=job_url,
            report_path=str(report.get_reports_dir()),
            continue_to_download=continue_to_download,
        )
    except Exception:
        selection = "c"

    if continue_to_download:
        download_handoff = dict(data)
        download_handoff.update(
            {
                "job_url": job_url,
                "report_path": str(report.get_reports_dir()),
            }
        )
        try:
            _run_integrated_download(download_handoff, str(mods["pkg_name"]))
        except SystemExit:
            raise
        except Exception as exc:
            logger.warn_block(
                "The job was submitted, but automatic downloading could not "
                f"start. You can resume it from Manage & Download.\nDetails: {exc}",
                severity="error",
            )
            _safe_input("\nPress Enter to close.", "")
            sys.exit(1)
        sys.exit(0)

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


def main() -> None:
    t_start = time.perf_counter()
    data = _load_handoff_from_argv(sys.argv)
    mods = _bootstrap_addon_modules(data)
    proj = data["project"]

    mods["clear_console"]()
    logger = mods["create_logger"](_LOG, input_fn=_safe_input)
    try:
        logger.logo_start()
    except Exception:
        pass

    ctx = _SubmitContext(
        data=data,
        mods=mods,
        t_start=t_start,
        proj=proj,
        logger=logger,
        # Mutations own their durable retry policy; transfers recover an
        # ambiguous PUT with HEAD rather than transport-level replay.
        session=mods["requests_retry_session"](allowed_methods=("HEAD", "GET", "OPTIONS")),
    )
    try:
        # Let release users decide whether to update before any submission work
        # continues. Development installs are explicitly excluded.
        _start_update_discovery(ctx)
        _show_update_before_submit(ctx)
        _preflight(ctx)
        _ensure_farm_ready(ctx)
        _trace_and_pack(ctx)
        _upload(ctx)
        _register_job(ctx)
        _finish(ctx)
    finally:
        _cancel_storage_prefetch(ctx)
        _cancel_update_discovery(ctx)
        try:
            ctx.session.close()
        except Exception:
            pass


# Entry point
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
