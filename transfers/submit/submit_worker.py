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
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Dict, List, Optional

_RISKY_CHARS = set("()'\"` &|;$!#")
_RUNTIME_HELPERS = None


# ─── Lightweight logger fallback ──────────────────────────────────
# This gets replaced after bootstrap when worker_utils.logger is available.
def _default_logger(msg: str) -> None:
    print(str(msg))


_LOG = _default_logger


def _set_logger(fn) -> None:
    global _LOG
    _LOG = fn if callable(fn) else _default_logger


def _runtime_helpers():
    global _RUNTIME_HELPERS
    if _RUNTIME_HELPERS is None:
        helper_path = Path(__file__).with_name("workflow_runtime_helpers.py")
        spec = importlib.util.spec_from_file_location(
            "_sulu_submit_runtime_helpers",
            helper_path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _RUNTIME_HELPERS = module
    return _RUNTIME_HELPERS


def _rclone_bytes(result) -> int:
    return _runtime_helpers().rclone_bytes(result)


def _rclone_stats(result):
    return _runtime_helpers().rclone_stats(result)


def _is_empty_upload(result, expected_file_count: int) -> bool:
    return _runtime_helpers().is_empty_upload(result, expected_file_count)


def _get_rclone_tail(result) -> list:
    return _runtime_helpers().get_rclone_tail(result)


def _log_upload_result(result, expected_bytes: int = 0, label: str = "") -> None:
    _runtime_helpers().log_upload_result(
        result,
        expected_bytes=expected_bytes,
        label=label,
        debug_enabled_fn=_debug_enabled,
        format_size_fn=_format_size,
        log_fn=_LOG,
    )


def _check_rclone_errors(result, label: str = "") -> None:
    _runtime_helpers().check_rclone_errors(
        result,
        label=label,
        debug_enabled_fn=_debug_enabled,
        log_fn=_LOG,
    )


def _is_filesystem_root(path: str) -> bool:
    return _runtime_helpers().is_filesystem_root(path)


def _check_risky_path_chars(path_str: str) -> Optional[str]:
    return _runtime_helpers().check_risky_path_chars(path_str)


def _split_manifest_by_first_dir(rel_manifest):
    return _runtime_helpers().split_manifest_by_first_dir(rel_manifest)


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
    Returns a typed dependency container.
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

    workflow_bootstrap = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_bootstrap"
    )
    deps = workflow_bootstrap.resolve_bootstrap_deps(
        pkg_name=pkg_name,
        set_logger_fn=_set_logger,
        log_fn=_LOG,
    )

    worker_utils = deps.worker_utils
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
    _safe_input = deps.safe_input
    return deps


# ─── main ────────────────────────────────────────────────────────
def main() -> None:
    t_start = time.perf_counter()

    data = _load_handoff_from_argv(sys.argv)
    deps = _bootstrap_addon_modules(data)

    clear_console = deps.clear_console
    shorten_path = deps.shorten_path
    is_blend_saved = deps.is_blend_saved
    open_folder = deps.open_folder
    pack_blend = deps.pack_blend
    trace_dependencies = deps.trace_dependencies
    compute_project_root = deps.compute_project_root
    classify_out_of_root_ok_files = deps.classify_out_of_root_ok_files
    validate_project_upload = deps.validate_project_upload
    validate_manifest_entries = deps.validate_manifest_entries
    prompt_continue_with_reports = deps.prompt_continue_with_reports
    build_project_manifest_from_map = deps.build_project_manifest_from_map
    apply_manifest_validation = deps.apply_manifest_validation
    write_manifest_file = deps.write_manifest_file
    validate_manifest_writeback = deps.validate_manifest_writeback
    build_job_payload = deps.build_job_payload
    apply_project_validation = deps.apply_project_validation
    DiagnosticReport = deps.diagnostic_report_class
    generate_test_report = deps.generate_test_report

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

    META_PROJECT_VALIDATION_VERSION = deps.meta_project_validation_version
    META_PROJECT_VALIDATION_STATS = deps.meta_project_validation_stats
    META_MANIFEST_ENTRY_COUNT = deps.meta_manifest_entry_count
    META_MANIFEST_SOURCE_MATCH_COUNT = deps.meta_manifest_source_match_count
    META_MANIFEST_VALIDATION_STATS = deps.meta_manifest_validation_stats
    DEFAULT_PROJECT_VALIDATION_VERSION = deps.default_project_validation_version
    UPLOAD_TOUCHED_LT_MANIFEST = deps.upload_touched_lt_manifest

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
            shorten_path_fn=shorten_path,
            format_size_fn=_format_size,
            is_filesystem_root_fn=_is_filesystem_root,
            debug_enabled_fn=_debug_enabled,
            log_fn=_LOG,
            is_mac=_IS_MAC,
            mac_permission_help_fn=_mac_permission_help,
            trace_dependencies=trace_dependencies,
            compute_project_root=compute_project_root,
            classify_out_of_root_ok_files=classify_out_of_root_ok_files,
            apply_project_validation=apply_project_validation,
            validate_project_upload=validate_project_upload,
            meta_project_validation_version=META_PROJECT_VALIDATION_VERSION,
            meta_project_validation_stats=META_PROJECT_VALIDATION_STATS,
            default_project_validation_version=DEFAULT_PROJECT_VALIDATION_VERSION,
            prompt_continue_with_reports=prompt_continue_with_reports,
            open_folder_fn=open_folder,
            generate_test_report=generate_test_report,
            safe_input_fn=_safe_input,
        )
        _handle_stage_outcome(trace_project_result)

        pack_project_result = deps.run_pack_project_stage(
            context=context,
            trace_result=trace_project_result,
            logger=logger,
            report=report,
            pack_blend=pack_blend,
            norm_abs_for_detection_fn=_norm_abs_for_detection,
            build_project_manifest_from_map=build_project_manifest_from_map,
            samepath_fn=_samepath,
            relpath_safe_fn=_relpath_safe,
            clean_key_fn=_s3key_clean,
            normalize_nfc_fn=_nfc,
            apply_manifest_validation=apply_manifest_validation,
            validate_manifest_entries=validate_manifest_entries,
            write_manifest_file=write_manifest_file,
            validate_manifest_writeback=validate_manifest_writeback,
            prompt_continue_with_reports=prompt_continue_with_reports,
            open_folder_fn=open_folder,
            meta_manifest_entry_count=META_MANIFEST_ENTRY_COUNT,
            meta_manifest_source_match_count=META_MANIFEST_SOURCE_MATCH_COUNT,
            meta_manifest_validation_stats=META_MANIFEST_VALIDATION_STATS,
            debug_enabled_fn=_debug_enabled,
            log_fn=_LOG,
        )
        _handle_stage_outcome(pack_project_result)
        stage_artifacts = pack_project_result.artifacts
    else:
        trace_zip_result = deps.run_trace_zip_stage(
            context=context,
            logger=logger,
            report=report,
            shorten_path_fn=shorten_path,
            format_size_fn=_format_size,
            trace_dependencies=trace_dependencies,
            compute_project_root=compute_project_root,
            prompt_continue_with_reports=prompt_continue_with_reports,
            open_folder_fn=open_folder,
            generate_test_report=generate_test_report,
            safe_input_fn=_safe_input,
        )
        _handle_stage_outcome(trace_zip_result)

        pack_zip_result = deps.run_pack_zip_stage(
            context=context,
            trace_result=trace_zip_result,
            logger=logger,
            report=report,
            pack_blend=pack_blend,
            norm_abs_for_detection_fn=_norm_abs_for_detection,
        )
        _handle_stage_outcome(pack_zip_result)
        stage_artifacts = pack_zip_result.artifacts

    if stage_artifacts is None:
        logger.fatal("Internal error: trace stage produced no artifacts.")
        sys.exit(1)

    project_root_str = stage_artifacts.project_root_str
    common_path = stage_artifacts.common_path
    rel_manifest = stage_artifacts.rel_manifest
    main_blend_s3 = stage_artifacts.main_blend_s3
    required_storage = stage_artifacts.required_storage
    dependency_total_size = stage_artifacts.dependency_total_size

    no_submit_flow = deps.handle_no_submit_mode(
        context=context,
        artifacts=stage_artifacts,
        logger=logger,
        safe_input_fn=_safe_input,
    )
    if no_submit_flow.should_exit:
        sys.exit(int(no_submit_flow.exit_code or 0))

    upload_result = deps.run_upload_stage(
        data=data,
        session=session,
        headers=headers,
        logger=logger,
        report=report,
        use_project=use_project,
        blend_path=blend_path,
        zip_file=zip_file,
        filelist=filelist,
        job_id=job_id,
        project_name=project_name,
        common_path=common_path,
        rel_manifest=rel_manifest,
        main_blend_s3=main_blend_s3,
        dependency_total_size=dependency_total_size,
        required_storage=required_storage,
        rclone_bin=rclone_bin,
        build_base_fn=deps.build_base,
        cloudflare_r2_domain=deps.cloudflare_r2_domain,
        run_rclone=deps.run_rclone,
        debug_enabled_fn=_debug_enabled,
        log_fn=_LOG,
        format_size_fn=_format_size,
        rclone_bytes_fn=_rclone_bytes,
        rclone_stats_fn=_rclone_stats,
        is_empty_upload_fn=_is_empty_upload,
        get_rclone_tail_fn=_get_rclone_tail,
        log_upload_result_fn=_log_upload_result,
        check_rclone_errors_fn=_check_rclone_errors,
        is_filesystem_root_fn=_is_filesystem_root,
        split_manifest_by_first_dir=deps.split_manifest_by_first_dir,
        record_manifest_touch_mismatch=deps.record_manifest_touch_mismatch,
        upload_touched_lt_manifest=UPLOAD_TOUCHED_LT_MANIFEST,
        clean_key_fn=_s3key_clean,
        normalize_nfc_fn=_nfc,
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
