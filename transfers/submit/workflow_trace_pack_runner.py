"""Compatibility orchestration wrapper for trace+pack stages.

This module remains as a transition shim. New code should call:
- workflow_trace_project_runner.run_trace_project_stage
- workflow_trace_zip_runner.run_trace_zip_stage
- workflow_pack_project_runner.run_pack_project_stage
- workflow_pack_zip_runner.run_pack_zip_stage
"""

from __future__ import annotations

from .workflow_pack_project_runner import run_pack_project_stage
from .workflow_pack_zip_runner import run_pack_zip_stage
from .workflow_trace_project_runner import run_trace_project_stage
from .workflow_trace_zip_runner import run_trace_zip_stage
from .workflow_types import (
    PackProjectDeps,
    PackZipDeps,
    SubmitRunContext,
    TracePackResult,
    TraceProjectDeps,
    TraceZipDeps,
)


def run_trace_and_pack_stage(
    *,
    context: SubmitRunContext,
    logger,
    report,
    shorten_path_fn,
    format_size_fn,
    is_filesystem_root_fn,
    debug_enabled_fn,
    log_fn,
    is_mac: bool,
    mac_permission_help_fn,
    trace_dependencies,
    compute_project_root,
    classify_out_of_root_ok_files,
    apply_project_validation,
    validate_project_upload,
    meta_project_validation_version: str,
    meta_project_validation_stats: str,
    default_project_validation_version: str,
    prompt_continue_with_reports,
    open_folder_fn,
    pack_blend,
    norm_abs_for_detection_fn,
    build_project_manifest_from_map,
    samepath_fn,
    relpath_safe_fn,
    clean_key_fn,
    normalize_nfc_fn,
    apply_manifest_validation,
    validate_manifest_entries,
    write_manifest_file,
    validate_manifest_writeback,
    meta_manifest_entry_count: str,
    meta_manifest_source_match_count: str,
    meta_manifest_validation_stats: str,
    generate_test_report,
    safe_input_fn,
) -> TracePackResult:
    if context.use_project:
        trace_project_deps = TraceProjectDeps(
            shorten_path_fn=shorten_path_fn,
            format_size_fn=format_size_fn,
            is_filesystem_root_fn=is_filesystem_root_fn,
            debug_enabled_fn=debug_enabled_fn,
            log_fn=log_fn,
            mac_permission_help_fn=mac_permission_help_fn,
            trace_dependencies=trace_dependencies,
            compute_project_root=compute_project_root,
            classify_out_of_root_ok_files=classify_out_of_root_ok_files,
            apply_project_validation=apply_project_validation,
            validate_project_upload=validate_project_upload,
            prompt_continue_with_reports=prompt_continue_with_reports,
            open_folder_fn=open_folder_fn,
            generate_test_report=generate_test_report,
            safe_input_fn=safe_input_fn,
            meta_project_validation_version=meta_project_validation_version,
            meta_project_validation_stats=meta_project_validation_stats,
            default_project_validation_version=default_project_validation_version,
        )
        trace_result = run_trace_project_stage(
            context=context,
            logger=logger,
            report=report,
            deps=trace_project_deps,
            is_mac=is_mac,
        )
        if trace_result.fatal_error or trace_result.flow.should_exit:
            return TracePackResult(
                flow=trace_result.flow,
                fatal_error=trace_result.fatal_error,
            )

        pack_project_deps = PackProjectDeps(
            pack_blend=pack_blend,
            norm_abs_for_detection_fn=norm_abs_for_detection_fn,
            build_project_manifest_from_map=build_project_manifest_from_map,
            samepath_fn=samepath_fn,
            relpath_safe_fn=relpath_safe_fn,
            clean_key_fn=clean_key_fn,
            normalize_nfc_fn=normalize_nfc_fn,
            apply_manifest_validation=apply_manifest_validation,
            validate_manifest_entries=validate_manifest_entries,
            write_manifest_file=write_manifest_file,
            validate_manifest_writeback=validate_manifest_writeback,
            prompt_continue_with_reports=prompt_continue_with_reports,
            open_folder_fn=open_folder_fn,
            meta_manifest_entry_count=meta_manifest_entry_count,
            meta_manifest_source_match_count=meta_manifest_source_match_count,
            meta_manifest_validation_stats=meta_manifest_validation_stats,
            debug_enabled_fn=debug_enabled_fn,
            log_fn=log_fn,
        )
        pack_result = run_pack_project_stage(
            context=context,
            trace_result=trace_result,
            logger=logger,
            report=report,
            deps=pack_project_deps,
        )
        return TracePackResult(
            artifacts=pack_result.artifacts,
            flow=pack_result.flow,
            fatal_error=pack_result.fatal_error,
        )

    trace_zip_deps = TraceZipDeps(
        shorten_path_fn=shorten_path_fn,
        format_size_fn=format_size_fn,
        trace_dependencies=trace_dependencies,
        compute_project_root=compute_project_root,
        prompt_continue_with_reports=prompt_continue_with_reports,
        open_folder_fn=open_folder_fn,
        generate_test_report=generate_test_report,
        safe_input_fn=safe_input_fn,
    )
    trace_result = run_trace_zip_stage(
        context=context,
        logger=logger,
        report=report,
        deps=trace_zip_deps,
    )
    if trace_result.fatal_error or trace_result.flow.should_exit:
        return TracePackResult(
            flow=trace_result.flow,
            fatal_error=trace_result.fatal_error,
        )

    pack_zip_deps = PackZipDeps(
        pack_blend=pack_blend,
        norm_abs_for_detection_fn=norm_abs_for_detection_fn,
    )
    pack_result = run_pack_zip_stage(
        context=context,
        trace_result=trace_result,
        logger=logger,
        report=report,
        deps=pack_zip_deps,
    )
    return TracePackResult(
        artifacts=pack_result.artifacts,
        flow=pack_result.flow,
        fatal_error=pack_result.fatal_error,
    )
