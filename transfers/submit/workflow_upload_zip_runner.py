"""Zip-mode upload stage runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from .workflow_types import StageArtifacts, SubmitRunContext, UploadDeps, UploadResult
from .workflow_runtime_helpers import (
    check_rclone_errors,
    log_upload_result,
    rclone_bytes,
    rclone_stats,
)
from .workflow_upload import run_addons_upload_step


def run_upload_zip_stage(
    *,
    context: SubmitRunContext,
    artifacts: StageArtifacts,
    logger,
    report,
    bucket: str,
    base_cmd: List[str],
    rclone_settings: List[str],
    deps: UploadDeps,
) -> UploadResult:
    data = context.data
    zip_file: Path = context.zip_file
    job_id = context.job_id

    required_storage = artifacts.required_storage

    run_rclone = deps.run_rclone
    debug_enabled_fn = deps.debug_enabled_fn
    log_fn = deps.log_fn
    format_size_fn = deps.format_size_fn

    def _log_upload_result(
        result: Any,
        *,
        expected_bytes: int = 0,
        label: str = "",
    ) -> None:
        log_upload_result(
            result,
            expected_bytes=expected_bytes,
            label=label,
            debug_enabled_fn=debug_enabled_fn,
            format_size_fn=format_size_fn,
            log_fn=log_fn,
        )

    def _check_rclone_errors(result: Any, *, label: str = "") -> None:
        check_rclone_errors(
            result,
            label=label,
            debug_enabled_fn=debug_enabled_fn,
            log_fn=log_fn,
        )

    has_addons = data.get("packed_addons") and len(data["packed_addons"]) > 0
    total_steps = 2 if has_addons else 1
    step = 1
    logger.upload_start(total_steps)

    logger.upload_step(step, total_steps, "Uploading archive")
    report.start_upload_step(
        step,
        total_steps,
        "Uploading archive",
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
    _log_upload_result(
        rclone_result,
        expected_bytes=required_storage,
        label="Archive: ",
    )
    _check_rclone_errors(rclone_result, label="Archive")
    report.complete_upload_step(
        bytes_transferred=rclone_bytes(rclone_result),
        rclone_stats=rclone_stats(rclone_result),
    )
    step += 1

    if has_addons:
        run_addons_upload_step(
            data=data,
            job_id=job_id,
            step=step,
            total_steps=total_steps,
            bucket=bucket,
            base_cmd=base_cmd,
            rclone_settings=rclone_settings,
            run_rclone=run_rclone,
            rclone_bytes_fn=rclone_bytes,
            rclone_stats_fn=rclone_stats,
            log_upload_result_fn=_log_upload_result,
            check_rclone_errors_fn=_check_rclone_errors,
            logger=logger,
            report=report,
        )

    return UploadResult()
