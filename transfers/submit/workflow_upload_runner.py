"""Stage 3 upload orchestration for submit workflow."""

from __future__ import annotations

import shutil
from typing import Any, Dict

from .workflow_types import StageArtifacts, SubmitRunContext, UploadDeps, UploadResult
from .workflow_upload_project_runner import run_upload_project_stage
from .workflow_upload_zip_runner import run_upload_zip_stage


def _cleanup_packed_addons(data: Dict[str, Any]) -> None:
    packed_addons_path = data.get("packed_addons_path")
    if not packed_addons_path:
        return
    try:
        # Best-effort temporary directory cleanup after upload phase.
        shutil.rmtree(packed_addons_path, ignore_errors=True)
    except (OSError, TypeError):
        pass


def run_upload_stage(
    *,
    context: SubmitRunContext,
    artifacts: StageArtifacts,
    session,
    headers: Dict[str, str],
    logger,
    report,
    rclone_bin: str,
    deps: UploadDeps,
) -> UploadResult:
    data: Dict[str, Any] = context.data

    build_base_fn = deps.build_base_fn
    cloudflare_r2_domain = deps.cloudflare_r2_domain

    logger.stage_header(3, "Uploading", "Transferring data to farm storage")
    report.start_stage("upload")

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
        report.set_status("failed")
        return UploadResult(
            fatal_error=(
                "Couldn't get storage credentials. Check your connection and try again.\n"
                f"Details: {exc}"
            )
        )

    base_cmd = build_base_fn(rclone_bin, f"https://{cloudflare_r2_domain}", s3info)
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

    try:
        if context.use_project:
            result = run_upload_project_stage(
                context=context,
                artifacts=artifacts,
                logger=logger,
                report=report,
                bucket=bucket,
                base_cmd=base_cmd,
                rclone_settings=rclone_settings,
                deps=deps,
            )
        else:
            result = run_upload_zip_stage(
                context=context,
                artifacts=artifacts,
                logger=logger,
                report=report,
                bucket=bucket,
                base_cmd=base_cmd,
                rclone_settings=rclone_settings,
                deps=deps,
            )

        if result.fatal_error:
            report.set_status("failed")
            return result
        report.complete_stage("upload")
        return result
    except RuntimeError as exc:
        report.set_status("failed")
        return UploadResult(
            fatal_error=(
                "Upload stopped. Check your connection and try again.\n"
                f"Details: {exc}"
            )
        )
    finally:
        _cleanup_packed_addons(data)
