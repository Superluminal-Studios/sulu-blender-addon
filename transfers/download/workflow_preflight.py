"""Preflight stage for download workflow."""

from __future__ import annotations

from .workflow_types import DownloadRunContext, PreflightResult


def run_preflight_phase(
    *,
    context: DownloadRunContext,
    session,
    logger,
    run_preflight_checks,
    ensure_rclone,
) -> PreflightResult:
    estimated_download_size = 1024 * 1024 * 1024
    storage_checks = [
        (context.download_path, estimated_download_size, "Download folder"),
    ]

    preflight_ok, preflight_issues = run_preflight_checks(
        session=session,
        storage_checks=storage_checks,
    )

    if not preflight_ok and preflight_issues:
        for issue in preflight_issues:
            logger.warning(issue)

    try:
        rclone_bin = str(ensure_rclone(logger=logger))
    except Exception as exc:
        return PreflightResult(
            preflight_ok=preflight_ok,
            preflight_issues=preflight_issues,
            rclone_bin="",
            fatal_error=f"Couldn't set up transfer tool: {exc}",
        )

    return PreflightResult(
        preflight_ok=preflight_ok,
        preflight_issues=preflight_issues,
        rclone_bin=rclone_bin,
    )
