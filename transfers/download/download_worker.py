"""
download_worker.py – Superluminal: asset downloader
Relies on generic helpers defined in worker_utils.py.

Modes:
- "single": one-time download of everything currently available
- "auto"  : periodically pulls new/updated frames as they appear
"""

from __future__ import annotations

# ─── stdlib ──────────────────────────────────────────────────────
import importlib
import json
import os
import re
import sys
import time
import types
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import traceback
import requests

try:
    t_start = time.perf_counter()
    handoff_path = Path(sys.argv[1]).resolve(strict=True)
    data: Dict[str, object] = json.loads(handoff_path.read_text("utf-8"))

    # Import add-on internals
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    # Import helpers
    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone_utils")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    clear_console = worker_utils.clear_console
    open_folder = worker_utils.open_folder

    # Import download logger
    download_logger_mod = importlib.import_module(f"{pkg_name}.utils.download_logger")
    DownloadLogger = download_logger_mod.DownloadLogger

    clear_console()

    # Internal utils
    _build_base = worker_utils._build_base
    requests_retry_session = worker_utils.requests_retry_session
    CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN

except Exception as exc:
    print(f"Couldn't start downloader: {exc}")
    traceback.print_exc()
    input("\nPress Enter to close.")
    sys.exit(1)


# ───────────────────  globals set in main()  ─────────────────────
session: requests.Session
job_id: str
job_name: str
download_path: str
rclone_bin: str
s3info: Dict[str, object]
bucket: str
base_cmd: List[str]
download_type: str
sarfis_url: Optional[str]
sarfis_token: Optional[str]
logger: DownloadLogger


# Helpers
def _safe_dir_name(name: str, fallback: str) -> str:
    """Make a filesystem-safe folder name (cross-platform)."""
    n = re.sub(r"[\\/:*?\"<>|]+", "_", str(name)).strip()
    return n or fallback


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _count_existing_files(path: str) -> int:
    """Count files already in destination (for resume detection)."""
    if not os.path.isdir(path):
        return 0
    count = 0
    for root, _, files in os.walk(path):
        count += len(files)
    return count


def _build_rclone_base() -> List[str]:
    return _build_base(
        rclone_bin,
        f"https://{CLOUDFLARE_R2_DOMAIN}",
        s3info,
    )


def _fetch_job_details() -> Tuple[str, int, int]:
    """
    Returns (status, finished, total) with safe defaults.
    If sarfis_url/token not configured, returns ('unknown', 0, 0).
    """
    if not sarfis_url or not sarfis_token:
        return ("unknown", 0, 0)

    try:
        resp = session.get(
            f"{sarfis_url}/api/job_details",
            params={"job_id": job_id},
            headers={"Auth-Token": sarfis_token},
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning(f"Job status check returned {resp.status_code}")
            return ("unknown", 0, 0)
        body = (
            resp.json().get("body", {})
            if resp.headers.get("content-type", "").startswith("application/json")
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


def _rclone_copy_output(dest_dir: str) -> bool:
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


def single_downloader(dest_dir: str) -> None:
    _ensure_dir(dest_dir)

    # Check for existing files (resuming previous download)
    existing = _count_existing_files(dest_dir)
    if existing > 0:
        logger.resume_info(existing)

    logger.transfer_start("Downloading")
    ok = _rclone_copy_output(dest_dir)
    if ok:
        logger.transfer_complete("Downloaded")
    else:
        logger.warning("No frames ready yet. Run again later to download.")


def auto_downloader(dest_dir: str, poll_seconds: int = 5) -> None:
    """Poll for new frames and download as they become available."""
    _ensure_dir(dest_dir)

    # Check for existing files (resuming previous download)
    existing = _count_existing_files(dest_dir)
    if existing > 0:
        logger.resume_info(existing)

    last_downloaded = 0
    last_refresh = 0.0
    refresh_interval = 60  # Check storage every 60s even if API shows no change
    shown_waiting = False

    logger.auto_mode_info()

    while True:
        job_status, finished, total = _fetch_job_details()

        # Download if: new frames available, or periodic refresh, or first run
        new_count = finished - last_downloaded
        time_to_refresh = (time.monotonic() - last_refresh) >= refresh_interval
        should_download = new_count > 0 or time_to_refresh or last_downloaded == 0

        if should_download and finished > 0:
            if new_count > 0 and last_downloaded > 0:
                logger.transfer_start(f"{new_count} new frames")
            else:
                logger.transfer_start(f"{finished} frames")

            last_refresh = time.monotonic()
            ok = _rclone_copy_output(dest_dir)
            if ok:
                logger.transfer_complete("Downloaded")
                last_downloaded = finished
        elif finished == 0 and not shown_waiting:
            logger.info("Waiting for first frame")
            shown_waiting = True

        # Job complete?
        if job_status in {"finished", "paused", "error"}:
            # One final sync
            _rclone_copy_output(dest_dir)

            if job_status == "finished":
                logger.success(f"{finished} frames downloaded")
            elif job_status == "paused":
                logger.warning(f"Job paused. {finished} frames saved.")
            else:
                logger.warning(f"Job stopped with errors. {finished} frames saved.")
            break

        time.sleep(max(1, int(poll_seconds)))


def main() -> None:
    global session, job_id, job_name, download_path
    global rclone_bin, s3info, bucket, base_cmd
    global download_type, sarfis_url, sarfis_token
    global logger

    # Create logger
    logger = DownloadLogger()

    session = requests_retry_session()
    headers = {"Authorization": data["user_token"]}
    job_id = str(data.get("job_id", "") or "").strip()
    job_name = (
        str(data.get("job_name", "") or f"job_{job_id}").strip() or f"job_{job_id}"
    )
    download_path = str(data.get("download_path", "") or "").strip() or os.getcwd()
    safe_job_dir = _safe_dir_name(job_name, f"job_{job_id}")
    dest_dir = os.path.abspath(os.path.join(download_path, safe_job_dir))

    # Show startup logo
    logger.logo_start(job_name=job_name, dest_dir=dest_dir)

    # ─── Preflight checks (run early so user knows quickly if something's wrong) ───
    # Import preflight utilities
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")
    preflight_mod = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    run_preflight_checks = preflight_mod.run_preflight_checks

    # Estimate download size - use 1 GB as reasonable default for render output
    # The actual size varies, but we want to ensure there's reasonable space
    estimated_download_size = 1024 * 1024 * 1024  # 1 GB minimum

    storage_checks = [
        (download_path, estimated_download_size, "Download folder"),
    ]

    preflight_ok, preflight_issues = run_preflight_checks(
        session=session,
        storage_checks=storage_checks,
    )

    if not preflight_ok and preflight_issues:
        for issue in preflight_issues:
            logger.warning(issue)
        # Don't block for downloads - just warn

    # Determine mode
    sarfis_url = data.get("sarfis_url")
    sarfis_token = data.get("sarfis_token")
    requested_mode = str(data.get("download_type", "") or "").lower()
    if requested_mode in {"single", "auto"}:
        download_type = requested_mode
    else:
        download_type = "auto" if sarfis_url and sarfis_token else "single"

    # Prepare rclone
    try:
        rclone_bin = ensure_rclone(logger=logger)
    except Exception as exc:
        logger.fatal(f"Couldn't set up transfer tool: {exc}")

    # Obtain R2 credentials
    try:
        s3_resp = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={
                "filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')"
            },
            timeout=30,
        )
        s3_resp.raise_for_status()
        payload = s3_resp.json()
        items = payload.get("items", [])
        if not items:
            raise IndexError("No storage records returned for this project.")
        s3info = items[0]
        bucket = s3info["bucket_name"]

    except (IndexError, requests.RequestException, KeyError) as exc:
        logger.fatal(f"Couldn't connect to storage: {exc}")

    # Build rclone base once
    base_cmd = _build_rclone_base()

    # Make sure the target directory exists
    _ensure_dir(download_path)

    # Run selected mode
    try:
        job_data = _fetch_job_details()
        if download_type == "single" or job_data[0] in ["finished", "paused", "error"]:
            single_downloader(dest_dir)
        else:
            if not sarfis_url or not sarfis_token:
                logger.warning(
                    "Can't track job progress. Downloading available frames only."
                )
                single_downloader(dest_dir)
            else:
                auto_downloader(dest_dir, poll_seconds=5)

        elapsed = time.perf_counter() - t_start

        # Show success screen
        choice = logger.logo_end(elapsed=elapsed, dest_dir=dest_dir)
        if choice == "o":
            open_folder(dest_dir)

    except KeyboardInterrupt:
        logger.warn_block(
            "Download interrupted. Run again to resume.", severity="warning"
        )
        try:
            input("\nPress Enter to close.")
        except Exception:
            pass
    except Exception as exc:
        logger.fatal(f"Download stopped: {exc}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        print(f"\nCouldn't start download: {exc}")
        input("\nPress Enter to close.")
