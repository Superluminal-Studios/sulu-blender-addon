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
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Dict, List, Optional

_RISKY_CHARS = set("()'\"` &|;$!#")


# ─── Lightweight logger fallback ──────────────────────────────────
# This gets replaced after bootstrap when worker_utils.logger is available.
def _default_logger(msg: str) -> None:
    print(str(msg))


_LOG = _default_logger


def _set_logger(fn) -> None:
    global _LOG
    _LOG = fn if callable(fn) else _default_logger


def _check_risky_path_chars(path_str: str) -> Optional[str]:
    found = set(c for c in path_str if c in _RISKY_CHARS)
    if found:
        chars = " ".join(repr(c) for c in sorted(found))
        return (
            f"Path contains special characters ({chars}) that may cause "
            f"issues on the render farm: {path_str}"
        )
    return None


# ─── Utilities imported after bootstrap ───────────────────────────
# These will be set by _bootstrap_addon_modules() at runtime.
# Declared here to satisfy static analysis and allow early use in type hints.
_nfc = None
_debug_enabled = None
_safe_input = None
_s3key_clean = None
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
    Returns a typed dependency container.
    """
    global _nfc, _debug_enabled, _safe_input, _s3key_clean

    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")

    # Make the add-on package importable for this subprocess
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    workflow_bootstrap = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_bootstrap"
    )
    deps = workflow_bootstrap.resolve_bootstrap_deps(
        pkg_name=pkg_name,
        set_logger_fn=_set_logger,
        log_fn=_LOG,
    )

    worker_utils = deps.worker_utils
    _nfc = worker_utils.normalize_nfc
    _debug_enabled = worker_utils.debug_enabled
    _s3key_clean = worker_utils.s3key_clean
    _safe_input = deps.safe_input
    return deps


# ─── main ────────────────────────────────────────────────────────
def main() -> None:
    t_start = time.perf_counter()

    data = _load_handoff_from_argv(sys.argv)
    deps = _bootstrap_addon_modules(data)

    clear_console = deps.clear_console
    is_blend_saved = deps.is_blend_saved
    open_folder = deps.open_folder
    build_job_payload = deps.build_job_payload
    DiagnosticReport = deps.diagnostic_report_class

    proj = data["project"]

    clear_console()

    # Rich logger: scrolling transcript UI
    logger = deps.create_logger(_LOG, input_fn=_safe_input)
    try:
        logger.logo_start()
    except Exception:
        pass

    # Local paths / settings
    blend_path: str = data["blend_path"]
    use_project: bool = bool(data["use_project_upload"])
    automatic_project_path: bool = bool(data["automatic_project_path"])
    custom_project_path_str: str = data["custom_project_path"]
    job_id: str = data["job_id"]
    test_mode: bool = bool(data.get("test_mode", False))
    no_submit: bool = bool(data.get("no_submit", False))
    zip_file = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist = Path(tempfile.gettempdir()) / f"{job_id}.txt"

    org_id = proj["organization_id"]
    project_sqid = proj["sqid"]
    project_name = proj["name"]

    workflow_types = importlib.import_module(
        f"{deps.pkg_name}.transfers.submit.workflow_types"
    )
    submit_run_context_cls = workflow_types.SubmitRunContext

    context = submit_run_context_cls(
        data=data,
        project=proj,
        blend_path=blend_path,
        use_project=use_project,
        automatic_project_path=automatic_project_path,
        custom_project_path_str=custom_project_path_str,
        job_id=job_id,
        project_name=project_name,
        project_sqid=project_sqid,
        org_id=org_id,
        test_mode=test_mode,
        no_submit=no_submit,
        zip_file=zip_file,
        filelist=filelist,
    )

    def _handle_stage_outcome(result) -> None:
        fatal_error = getattr(result, "fatal_error", None)
        if fatal_error:
            logger.fatal(fatal_error)
            sys.exit(1)

        flow = getattr(result, "flow", None)
        if flow is not None and getattr(flow, "should_exit", False):
            sys.exit(int(flow.exit_code or 0))

    # Single resilient session for all HTTP traffic
    session = deps.requests_retry_session()
    preflight = deps.run_preflight_phase(
        context=context,
        session=session,
        logger=logger,
        worker_utils=deps.worker_utils,
        ensure_rclone=deps.ensure_rclone,
        debug_enabled_fn=_debug_enabled,
    )
    _handle_stage_outcome(preflight)
    headers = preflight.headers
    rclone_bin = preflight.rclone_bin
    preflight_issues = preflight.preflight_issues
    preflight_ok = preflight.preflight_ok
    _preflight_user_override = preflight.preflight_user_override

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

    stage_artifacts = None
    if use_project:
        trace_project_result = deps.run_trace_project_stage(
            context=context,
            logger=logger,
            report=report,
            deps=deps.trace_project_deps,
            is_mac=_IS_MAC,
        )
        _handle_stage_outcome(trace_project_result)

        pack_project_result = deps.run_pack_project_stage(
            context=context,
            trace_result=trace_project_result,
            logger=logger,
            report=report,
            deps=deps.pack_project_deps,
        )
        _handle_stage_outcome(pack_project_result)
        stage_artifacts = pack_project_result.artifacts
    else:
        trace_zip_result = deps.run_trace_zip_stage(
            context=context,
            logger=logger,
            report=report,
            deps=deps.trace_zip_deps,
        )
        _handle_stage_outcome(trace_zip_result)

        pack_zip_result = deps.run_pack_zip_stage(
            context=context,
            trace_result=trace_zip_result,
            logger=logger,
            report=report,
            deps=deps.pack_zip_deps,
        )
        _handle_stage_outcome(pack_zip_result)
        stage_artifacts = pack_zip_result.artifacts

    if stage_artifacts is None:
        logger.fatal("Internal error: trace stage produced no artifacts.")
        sys.exit(1)

    project_root_str = stage_artifacts.project_root_str
    main_blend_s3 = stage_artifacts.main_blend_s3
    required_storage = stage_artifacts.required_storage

    no_submit_flow = deps.handle_no_submit_mode(
        context=context,
        artifacts=stage_artifacts,
        logger=logger,
        safe_input_fn=_safe_input,
    )
    if no_submit_flow.should_exit:
        sys.exit(int(no_submit_flow.exit_code or 0))

    upload_result = deps.run_upload_stage(
        context=context,
        artifacts=stage_artifacts,
        session=session,
        headers=headers,
        logger=logger,
        report=report,
        rclone_bin=rclone_bin,
        deps=deps.upload_deps,
    )
    _handle_stage_outcome(upload_result)

    payload = build_job_payload(
        data=data,
        org_id=org_id,
        project_name=project_name,
        blend_path=blend_path,
        project_root_str=project_root_str,
        main_blend_s3=main_blend_s3,
        required_storage=required_storage,
        use_project=use_project,
        normalize_nfc_fn=_nfc,
        clean_key_fn=_s3key_clean,
    )

    finalize_result = deps.finalize_submission(
        context=context,
        session=session,
        headers=headers,
        payload=payload,
        logger=logger,
        report=report,
        t_start=t_start,
        open_folder_fn=open_folder,
        safe_input_fn=_safe_input,
        argv=sys.argv,
    )
    _handle_stage_outcome(finalize_result)


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
