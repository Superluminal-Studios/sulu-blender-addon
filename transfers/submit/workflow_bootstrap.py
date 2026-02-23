"""Bootstrap dependency resolver for submit worker."""

from __future__ import annotations

import importlib

from .workflow_types import (
    BootstrapDeps,
    PackProjectDeps,
    PackZipDeps,
    TraceProjectDeps,
    TraceZipDeps,
    UploadDeps,
)


def resolve_bootstrap_deps(*, pkg_name: str, set_logger_fn, log_fn) -> BootstrapDeps:
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")

    set_logger_fn(worker_utils.logger)

    def _safe_input_wrapper(prompt: str, default: str = "") -> str:
        return worker_utils.safe_input(prompt, default, log_fn=log_fn)

    bat_utils = importlib.import_module(f"{pkg_name}.utils.bat_utils")
    project_upload_validator = importlib.import_module(
        f"{pkg_name}.utils.project_upload_validator"
    )
    diagnostic_schema = importlib.import_module(f"{pkg_name}.utils.diagnostic_schema")

    workflow_prompts = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_prompts"
    )
    workflow_manifest = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_manifest"
    )
    workflow_submit = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_submit"
    )
    workflow_trace = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_trace"
    )
    workflow_preflight = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_preflight"
    )
    workflow_trace_project_runner = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_trace_project_runner"
    )
    workflow_trace_zip_runner = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_trace_zip_runner"
    )
    workflow_pack_project_runner = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_pack_project_runner"
    )
    workflow_pack_zip_runner = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_pack_zip_runner"
    )
    workflow_upload_runner = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_upload_runner"
    )
    workflow_runtime_helpers = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_runtime_helpers"
    )
    workflow_no_submit = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_no_submit"
    )
    workflow_finalize = importlib.import_module(
        f"{pkg_name}.transfers.submit.workflow_finalize"
    )

    submit_logger = importlib.import_module(f"{pkg_name}.utils.submit_logger")
    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone_utils")
    diagnostic_report_mod = importlib.import_module(
        f"{pkg_name}.utils.diagnostic_report"
    )

    trace_project_deps = TraceProjectDeps(
        shorten_path_fn=worker_utils.shorten_path,
        format_size_fn=worker_utils.format_size,
        is_filesystem_root_fn=workflow_runtime_helpers.is_filesystem_root,
        debug_enabled_fn=worker_utils.debug_enabled,
        log_fn=log_fn,
        mac_permission_help_fn=worker_utils.mac_permission_help,
        trace_dependencies=bat_utils.trace_dependencies,
        compute_project_root=bat_utils.compute_project_root,
        classify_out_of_root_ok_files=bat_utils.classify_out_of_root_ok_files,
        apply_project_validation=workflow_trace.apply_project_validation,
        validate_project_upload=project_upload_validator.validate_project_upload,
        prompt_continue_with_reports=workflow_prompts.prompt_continue_with_reports,
        open_folder_fn=worker_utils.open_folder,
        generate_test_report=diagnostic_report_mod.generate_test_report,
        safe_input_fn=_safe_input_wrapper,
        meta_project_validation_version=diagnostic_schema.META_PROJECT_VALIDATION_VERSION,
        meta_project_validation_stats=diagnostic_schema.META_PROJECT_VALIDATION_STATS,
        default_project_validation_version=diagnostic_schema.DEFAULT_PROJECT_VALIDATION_VERSION,
    )
    trace_zip_deps = TraceZipDeps(
        shorten_path_fn=worker_utils.shorten_path,
        format_size_fn=worker_utils.format_size,
        trace_dependencies=bat_utils.trace_dependencies,
        compute_project_root=bat_utils.compute_project_root,
        prompt_continue_with_reports=workflow_prompts.prompt_continue_with_reports,
        open_folder_fn=worker_utils.open_folder,
        generate_test_report=diagnostic_report_mod.generate_test_report,
        safe_input_fn=_safe_input_wrapper,
    )
    pack_project_deps = PackProjectDeps(
        pack_blend=bat_utils.pack_blend,
        norm_abs_for_detection_fn=worker_utils.norm_abs_for_detection,
        build_project_manifest_from_map=workflow_manifest.build_project_manifest_from_map,
        samepath_fn=worker_utils.samepath,
        relpath_safe_fn=worker_utils.relpath_safe,
        clean_key_fn=worker_utils.s3key_clean,
        normalize_nfc_fn=worker_utils.normalize_nfc,
        apply_manifest_validation=workflow_manifest.apply_manifest_validation,
        validate_manifest_entries=project_upload_validator.validate_manifest_entries,
        write_manifest_file=workflow_manifest.write_manifest_file,
        validate_manifest_writeback=workflow_manifest.validate_manifest_writeback,
        prompt_continue_with_reports=workflow_prompts.prompt_continue_with_reports,
        open_folder_fn=worker_utils.open_folder,
        meta_manifest_entry_count=diagnostic_schema.META_MANIFEST_ENTRY_COUNT,
        meta_manifest_source_match_count=diagnostic_schema.META_MANIFEST_SOURCE_MATCH_COUNT,
        meta_manifest_validation_stats=diagnostic_schema.META_MANIFEST_VALIDATION_STATS,
        debug_enabled_fn=worker_utils.debug_enabled,
        log_fn=log_fn,
    )
    pack_zip_deps = PackZipDeps(
        pack_blend=bat_utils.pack_blend,
        norm_abs_for_detection_fn=worker_utils.norm_abs_for_detection,
    )
    upload_deps = UploadDeps(
        build_base_fn=worker_utils._build_base,
        cloudflare_r2_domain=worker_utils.CLOUDFLARE_R2_DOMAIN,
        run_rclone=rclone.run_rclone,
        debug_enabled_fn=worker_utils.debug_enabled,
        log_fn=log_fn,
        format_size_fn=worker_utils.format_size,
        upload_touched_lt_manifest=diagnostic_schema.UPLOAD_TOUCHED_LT_MANIFEST,
        clean_key_fn=worker_utils.s3key_clean,
        normalize_nfc_fn=worker_utils.normalize_nfc,
    )

    return BootstrapDeps(
        pkg_name=pkg_name,
        worker_utils=worker_utils,
        safe_input=_safe_input_wrapper,
        clear_console=worker_utils.clear_console,
        is_blend_saved=worker_utils.is_blend_saved,
        requests_retry_session=worker_utils.requests_retry_session,
        open_folder=worker_utils.open_folder,
        build_job_payload=workflow_submit.build_job_payload,
        create_logger=submit_logger.create_logger,
        ensure_rclone=rclone.ensure_rclone,
        diagnostic_report_class=diagnostic_report_mod.DiagnosticReport,
        trace_project_deps=trace_project_deps,
        trace_zip_deps=trace_zip_deps,
        pack_project_deps=pack_project_deps,
        pack_zip_deps=pack_zip_deps,
        upload_deps=upload_deps,
        run_preflight_phase=workflow_preflight.run_preflight_phase,
        run_trace_project_stage=workflow_trace_project_runner.run_trace_project_stage,
        run_trace_zip_stage=workflow_trace_zip_runner.run_trace_zip_stage,
        run_pack_project_stage=workflow_pack_project_runner.run_pack_project_stage,
        run_pack_zip_stage=workflow_pack_zip_runner.run_pack_zip_stage,
        run_upload_stage=workflow_upload_runner.run_upload_stage,
        handle_no_submit_mode=workflow_no_submit.handle_no_submit_mode,
        finalize_submission=workflow_finalize.finalize_submission,
    )
