"""Project-mode pack stage for submit workflow."""

from __future__ import annotations

import os

from .workflow_types import (
    FlowControl,
    PackProjectResult,
    StageArtifacts,
    SubmitRunContext,
    TraceProjectResult,
)


def run_pack_project_stage(
    *,
    context: SubmitRunContext,
    trace_result: TraceProjectResult,
    logger,
    report,
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
    prompt_continue_with_reports,
    open_folder_fn,
    meta_manifest_entry_count: str,
    meta_manifest_source_match_count: str,
    meta_manifest_validation_stats: str,
    debug_enabled_fn,
    log_fn,
) -> PackProjectResult:
    blend_path = context.blend_path
    filelist = context.filelist

    common_path = trace_result.project_root_str

    logger.stage_header(
        2,
        "Building manifest",
        "Mapping dependencies into the project structure",
    )
    report.start_stage("pack")

    fmap, _pack_report = pack_blend(
        blend_path,
        target="",
        method="PROJECT",
        project_path=common_path,
        return_report=True,
        pre_traced_deps=list(trace_result.ok_files_set),
    )

    abs_blend = norm_abs_for_detection_fn(blend_path)
    logger.pack_start()
    manifest_build = build_project_manifest_from_map(
        fmap=fmap,
        abs_blend=abs_blend,
        common_path=common_path,
        ok_files_cache=trace_result.ok_files_cache,
        logger=logger,
        report=report,
        samepath_fn=samepath_fn,
        relpath_safe_fn=relpath_safe_fn,
        clean_key_fn=clean_key_fn,
    )
    rel_manifest = manifest_build.rel_manifest
    manifest_source_map = manifest_build.manifest_source_map
    dependency_total_size = manifest_build.dependency_total_size

    required_storage = dependency_total_size
    try:
        required_storage += os.path.getsize(blend_path)
    except Exception:
        pass

    rel_manifest, keep_going = apply_manifest_validation(
        rel_manifest=rel_manifest,
        common_path=common_path,
        manifest_source_map=manifest_source_map,
        validate_manifest_entries=validate_manifest_entries,
        logger=logger,
        report=report,
        prompt_continue_with_reports=prompt_continue_with_reports,
        open_folder_fn=open_folder_fn,
        clean_key_fn=clean_key_fn,
        metadata_manifest_entry_count=meta_manifest_entry_count,
        metadata_manifest_source_match_count=meta_manifest_source_match_count,
        metadata_manifest_validation_stats=meta_manifest_validation_stats,
    )
    if not keep_going:
        return PackProjectResult(
            flow=FlowControl.exit_flow(1, "manifest_validation_cancelled")
        )

    write_manifest_file(filelist, rel_manifest)
    validate_manifest_writeback(
        filelist_path=filelist,
        expected_count=len(rel_manifest),
        report=report,
        debug_enabled_fn=debug_enabled_fn,
        log_fn=log_fn,
    )

    blend_rel = relpath_safe_fn(abs_blend, common_path)
    main_blend_s3 = normalize_nfc_fn(clean_key_fn(blend_rel) or os.path.basename(abs_blend))

    logger.pack_end(
        ok_count=manifest_build.ok_count,
        total_size=required_storage,
        title="Manifest complete",
    )
    report.set_pack_dependency_size(dependency_total_size)
    report.complete_stage("pack")

    return PackProjectResult(
        artifacts=StageArtifacts(
            project_root_str=common_path,
            common_path=common_path,
            rel_manifest=rel_manifest,
            main_blend_s3=main_blend_s3,
            required_storage=required_storage,
            dependency_total_size=dependency_total_size,
        )
    )
