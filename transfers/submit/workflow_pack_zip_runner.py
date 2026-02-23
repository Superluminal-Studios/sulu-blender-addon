"""Zip-mode pack stage for submit workflow."""

from __future__ import annotations

from .workflow_types import (
    PackZipDeps,
    PackZipResult,
    StageArtifacts,
    SubmitRunContext,
    TraceZipResult,
)


def run_pack_zip_stage(
    *,
    context: SubmitRunContext,
    trace_result: TraceZipResult,
    logger,
    report,
    deps: PackZipDeps,
) -> PackZipResult:
    pack_blend = deps.pack_blend
    norm_abs_for_detection_fn = deps.norm_abs_for_detection_fn

    blend_path = context.blend_path
    zip_file = context.zip_file
    project_root_str = trace_result.project_root_str

    logger.stage_header(
        2,
        "Packing",
        "Creating a compressed archive with all dependencies",
    )
    report.start_stage("pack")

    abs_blend_norm = norm_abs_for_detection_fn(blend_path)
    zip_started = False
    zip_dep_size = 0

    def _on_zip_entry(idx, total, arcname, size, method):
        nonlocal zip_started, zip_dep_size
        zip_dep_size += size
        if not zip_started:
            logger.zip_start(total, 0)
            zip_started = True
        logger.zip_entry(idx, total, arcname, size, method)
        report.add_pack_entry(arcname, arcname, file_size=size, status="ok")

    def _on_zip_done(zippath, total_files, total_bytes, elapsed):
        logger.zip_done(zippath, total_files, total_bytes, elapsed)

    def _noop_emit(msg):
        pass

    _zip_report = pack_blend(
        abs_blend_norm,
        str(zip_file),
        method="ZIP",
        project_path=project_root_str,
        return_report=True,
        pre_traced_deps=trace_result.raw_usages,
        zip_emit_fn=_noop_emit,
        zip_entry_cb=_on_zip_entry,
        zip_done_cb=_on_zip_done,
    )

    if not zip_file.exists():
        report.set_status("failed")
        return PackZipResult(
            fatal_error="Archive not created. Check disk space and permissions."
        )

    required_storage = zip_file.stat().st_size
    report.set_pack_dependency_size(zip_dep_size)
    report.complete_stage("pack")

    return PackZipResult(
        artifacts=StageArtifacts(
            project_root_str=project_root_str,
            common_path="",
            rel_manifest=[],
            main_blend_s3="",
            required_storage=required_storage,
            dependency_total_size=zip_dep_size,
        )
    )
