"""Transfer stage runners for download workflow."""

from __future__ import annotations

import time
from typing import Optional, Tuple

from .workflow_context import count_existing_files, ensure_dir
from .workflow_types import DownloadDispatchResult, DownloadRunContext


def fetch_job_details(
    *,
    session,
    job_id: str,
    sarfis_url: Optional[str],
    sarfis_token: Optional[str],
    logger,
) -> Tuple[str, int, int]:
    """
    Returns (status, finished, total) with safe defaults.
    If sarfis_url/token are not configured, returns ('unknown', 0, 0).
    """
    if not sarfis_url or not sarfis_token:
        return ("unknown", 0, 0)

    try:
        response = session.get(
            f"{sarfis_url}/api/job_details",
            params={"job_id": job_id},
            headers={"Auth-Token": sarfis_token},
            timeout=20,
        )
        if response.status_code != 200:
            logger.warning(f"Job status check returned {response.status_code}")
            return ("unknown", 0, 0)

        body = (
            response.json().get("body", {})
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        status = str(body.get("status", "unknown")).lower()
        tasks = body.get("tasks", {}) or {}
        finished = int(tasks.get("finished", 0) or 0)
        total = int(body.get("total_tasks", tasks.get("total", 0) or 0) or 0)
        return (status, finished, total)
    except Exception as exc:
        logger.warning(f"Job status check failed: {exc}")
        return ("unknown", 0, 0)


def rclone_copy_output(
    *,
    base_cmd,
    run_rclone,
    bucket: str,
    job_id: str,
    dest_dir: str,
    logger,
) -> bool:
    """
    Copy job output from remote to dest_dir.
    Returns True if copy succeeded (even if nothing new), False if remote likely doesn't exist yet.
    """
    rclone_args = [
        "--exclude",
        "thumbnails/**",
        "--transfers",
        "8",
        "--checkers",
        "8",
        "--size-only",
        "--retries",
        "10",
        "--low-level-retries",
        "20",
        "--retries-sleep",
        "5s",
    ]

    remote = f":s3:{bucket}/{job_id}/output/"
    local = dest_dir.rstrip("/") + "/"

    try:
        run_rclone(
            base_cmd,
            "copy",
            remote,
            local,
            rclone_args,
            logger=logger,
        )
        return True
    except RuntimeError as exc:
        msg = str(exc).lower()
        hints = (
            "directory not found",
            "no such key",
            "404",
            "not exist",
            "cannot find",
        )
        if any(h in msg for h in hints):
            logger.info("No frames available yet")
            return False
        logger.error(f"Download stopped: {exc}")
        raise


def single_downloader(
    *,
    dest_dir: str,
    logger,
    copy_output_fn,
) -> None:
    ensure_dir(dest_dir)

    existing = count_existing_files(dest_dir)
    if existing > 0:
        logger.resume_info(existing)

    logger.transfer_start("Downloading")
    ok = copy_output_fn(dest_dir)
    if ok:
        logger.transfer_complete("Downloaded")
    else:
        logger.warning("No frames ready yet. Run again later to download.")


def auto_downloader(
    *,
    context: DownloadRunContext,
    logger,
    fetch_job_details_fn,
    copy_output_fn,
    poll_seconds: int = 5,
    sleep_fn=time.sleep,
) -> None:
    """Poll for new frames and download as they become available."""
    dest_dir = context.dest_dir
    ensure_dir(dest_dir)

    existing = count_existing_files(dest_dir)
    if existing > 0:
        logger.resume_info(existing)

    last_downloaded = 0
    last_refresh = 0.0
    refresh_interval = 60
    shown_waiting = False

    logger.auto_mode_info()

    while True:
        job_status, finished, _ = fetch_job_details_fn()

        new_count = finished - last_downloaded
        time_to_refresh = (time.monotonic() - last_refresh) >= refresh_interval
        should_download = new_count > 0 or time_to_refresh or last_downloaded == 0

        if should_download and finished > 0:
            if new_count > 0 and last_downloaded > 0:
                logger.transfer_start(f"{new_count} new frames")
            else:
                logger.transfer_start(f"{finished} frames")

            last_refresh = time.monotonic()
            ok = copy_output_fn(dest_dir)
            if ok:
                logger.transfer_complete("Downloaded")
                last_downloaded = finished
        elif finished == 0 and not shown_waiting:
            logger.info("Waiting for first frame")
            shown_waiting = True

        if job_status in {"finished", "paused", "error"}:
            copy_output_fn(dest_dir)

            if job_status == "finished":
                logger.success(f"{finished} frames downloaded")
            elif job_status == "paused":
                logger.warning(f"Job paused. {finished} frames saved.")
            else:
                logger.warning(f"Job stopped with errors. {finished} frames saved.")
            break

        sleep_fn(max(1, int(poll_seconds)))


def run_download_dispatch(
    *,
    context: DownloadRunContext,
    logger,
    session,
    run_rclone,
    base_cmd,
    bucket: str,
) -> DownloadDispatchResult:
    def _fetch():
        return fetch_job_details(
            session=session,
            job_id=context.job_id,
            sarfis_url=context.sarfis_url,
            sarfis_token=context.sarfis_token,
            logger=logger,
        )

    def _copy(dest_dir: str) -> bool:
        return rclone_copy_output(
            base_cmd=base_cmd,
            run_rclone=run_rclone,
            bucket=bucket,
            job_id=context.job_id,
            dest_dir=dest_dir,
            logger=logger,
        )

    job_data = _fetch()
    if context.download_type == "single" or job_data[0] in ["finished", "paused", "error"]:
        single_downloader(dest_dir=context.dest_dir, logger=logger, copy_output_fn=_copy)
    else:
        if not context.sarfis_url or not context.sarfis_token:
            logger.warning("Can't track job progress. Downloading available frames only.")
            single_downloader(dest_dir=context.dest_dir, logger=logger, copy_output_fn=_copy)
        else:
            auto_downloader(
                context=context,
                logger=logger,
                fetch_job_details_fn=_fetch,
                copy_output_fn=_copy,
                poll_seconds=5,
            )

    return DownloadDispatchResult()
