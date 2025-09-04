"""
download_worker.py – Superluminal: asset downloader
Relies on generic helpers defined in submit_utils.py.

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

    #import add-on internals
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    #import helpers
    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    clear_console = importlib.import_module(f"{pkg_name}.utils.worker_utils").clear_console
    clear_console()
    
    #internal utils
    _log = worker_utils.logger
    _build_base = worker_utils._build_base
    requests_retry_session = worker_utils.requests_retry_session
    CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN

except Exception as exc:
    print(f"❌  Failed to initialize downloader: {exc}")
    print(f"Error type: {type(exc)}")
    traceback.print_exc()
    input("\nPress ENTER to close this window…")
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


#helpers
def _safe_dir_name(name: str, fallback: str) -> str:
    """Make a filesystem-safe folder name (cross-platform)."""
    n = re.sub(r"[\\/:*?\"<>|]+", "_", str(name)).strip()
    return n or fallback

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

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
            _log(f"ℹ️  Job status check returned {resp.status_code}. will retry.")
            return ("unknown", 0, 0)
        body = resp.json().get("body", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
        status = str(body.get("status", "unknown")).lower()
        tasks = body.get("tasks", {}) or {}
        finished = int(tasks.get("finished", 0) or 0)
        total = int(body.get("total_tasks", tasks.get("total", 0) or 0) or 0)
        return (status, finished, total)
    except Exception as exc:
        _log(f"ℹ️  Job status check failed ({exc}); will retry.")
        return ("unknown", 0, 0)

def _rclone_copy_output(dest_dir: str) -> bool:
    """
    Copy job output from remote to dest_dir.
    Returns True if copy succeeded (even if nothing new), False if remote likely doesn't exist yet.
    """
    # Base args tuned for incremental pulls without thrashing:
    # - exclude thumbnails
    # - parallelism modest to keep UI responsive
    # - size-only to avoid Cloudflare multipart etag pitfalls
    rclone_args = [
        "--exclude", "thumbnails/**",
        "--transfers", "16",
        "--checkers", "16",
        "--size-only",
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
            logger=_log,
        )
        return True
    except RuntimeError as exc:
        # If the path doesn't exist yet, treat as "nothing yet"
        msg = str(exc).lower()
        hints = ("directory not found", "no such key", "404", "not exist", "cannot find")
        if any(h in msg for h in hints):
            _log("ℹ️  Output not available yet (no files found). Will try again.")
            return False
        _log(f"❌  Download error: {exc}")
        raise

def _print_first_run_hint():
    _log("\nℹ️  Tip:")
    _log("   • Keep this window open to auto download frames as they finish.")
    _log("   • You can close this window anytime. rerun the download later to resume.")

def single_downloader():
    safe_job_dir = _safe_dir_name(job_name, f"job_{job_id}")
    dest_dir = os.path.join(download_path, safe_job_dir)
    _ensure_dir(dest_dir)

    _log("🚀  Downloading render output…")
    ok = _rclone_copy_output(dest_dir)
    if ok:
        elapsed = time.perf_counter() - t_start
        _log(f"✅  Download complete. Saved to: {dest_dir}")
        _log(f"🕒  Took {elapsed:.1f}s in total.")
    else:
        _log("ℹ️  No outputs found yet. Try again later or use Auto mode to wait for frames.")


def auto_downloader(poll_seconds: int = 5, min_delta_frames: int = 1, min_percent: float = 0.10):
    """
    Periodically checks job progress and pulls new frames when:
      - finished increased by at least `min_delta_frames`, or
      - overall finished >= min_percent of total (first meaningful batch), or
      - a periodic refresh timer fires (in case the job API lags behind).
    """
    safe_job_dir = _safe_dir_name(job_name, f"job_{job_id}")
    dest_dir = os.path.join(download_path, safe_job_dir)
    _ensure_dir(dest_dir)

    last_finished = 0
    first_notice_shown = False
    periodic_refresh_every = 60  # seconds
    last_refresh = time.monotonic() - periodic_refresh_every  # force a refresh on first loop

    _log("🔄  Auto mode: will download new frames as they become available.")
    _print_first_run_hint()

    while True:
        status, finished, total = _fetch_job_details()

        # Friendly status line
        if total > 0:
            pct = (finished / max(total, 1)) * 100.0
            _log(f"\nℹ️  Status: {status or 'unknown'} | {finished}/{total} frames ({pct:.1f}%)")
        else:
            _log(f"\nℹ️  Status: {status or 'unknown'} | finished frames: {finished}")

        # Show first-notice only once
        if not first_notice_shown and status in {"running", "queued", "unknown"}:
            _log("⏳  Waiting for frames to appear on storage...")
            first_notice_shown = True

        # Trigger conditions
        enough_progress = (total > 0 and finished >= max(int(total * min_percent), min_delta_frames))
        new_frames = (finished > last_finished)
        refresh_due = (time.monotonic() - last_refresh) >= periodic_refresh_every

        if new_frames or enough_progress or refresh_due:
            if new_frames:
                _log(f"📥  Detected {finished - last_finished} new frame(s). Pulling…")
            elif enough_progress:
                _log("📥  Pulling initial batch of frames...")
            else:
                _log("📥  Periodic refresh...")
            last_refresh = time.monotonic()
            ok = _rclone_copy_output(dest_dir)
            if ok:
                last_finished = finished

        # Exit conditions
        if status in {"finished", "paused", "error"}:
            _log("\n🔄  Finalizing download (one last pass)...")
            try:
                _rclone_copy_output(dest_dir)
            except Exception:
                # already logged
                pass
            if status == "finished":
                _log("✅  All frames downloaded.")
            elif status == "paused":
                _log("⏸️  Job paused. Current frames are downloaded. You can resume later.")
            else:
                _log("⚠️  Job ended with errors. Current frames are downloaded. You can rerun later to pick up more if retried.")
            break

        time.sleep(max(1, int(poll_seconds)))


def main() -> None:
    global session, job_id, job_name, download_path
    global rclone_bin, s3info, bucket, base_cmd
    global download_type, sarfis_url, sarfis_token

    session = requests_retry_session()
    headers = {"Authorization": data["user_token"]}
    job_id = str(data.get("job_id", "") or "").strip()
    job_name = str(data.get("job_name", "") or f"job_{job_id}").strip() or f"job_{job_id}"
    download_path = str(data.get("download_path", "") or "").strip() or os.getcwd()

    #determine mode
    sarfis_url = data.get("sarfis_url")
    sarfis_token = data.get("sarfis_token")
    requested_mode = str(data.get("download_type", "") or "").lower()
    if requested_mode in {"single", "auto"}:
        download_type = requested_mode
    else:
        #default: auto if we have a status endpoint; otherwise single
        download_type = "auto" if sarfis_url and sarfis_token else "single"

    # rclone
    try:
        rclone_bin = ensure_rclone(logger=_log)
    except Exception as exc:
        _log(f"❌  Could not prepare the downloader (rclone): {exc}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    #obtain R2 credentials
    _log("🔑  Fetching storage credentials…")
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
        _log(f"❌  Failed to obtain bucket credentials: {exc}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    # Build rclone base once
    base_cmd = _build_rclone_base()

    # Make sure the target directory exists
    _ensure_dir(download_path)

    # ─────── run selected mode ─────────────────────────────────
    try:
        if download_type == "single":
            single_downloader()
            input("\nPress ENTER to close this window…")
        else:
            if not sarfis_url or not sarfis_token:
                _log("ℹ️  Auto mode requested but no job status endpoint was provided. Falling back to single download.")
                single_downloader()
                input("\nPress ENTER to close this window...")
            else:
                _log(f"ℹ️  Mode: Auto (polling every 5s). Destination: {download_path}")
                auto_downloader(poll_seconds=5)
                elapsed = time.perf_counter() - t_start
                _log(f"🎉  Download session finished. Elapsed: {elapsed:.1f}s")
                input("\nPress ENTER to close this window...")
    except KeyboardInterrupt:
        _log("\n⏹️  Download interrupted by user. You can rerun this later to resume.")
        input("\nPress ENTER to close this window...")
    except Exception as exc:
        _log(f"\n❌  Download failed: {exc}")
        traceback.print_exc()
        input("\nPress ENTER to close this window...")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        _log(f"\n❌  Download failed before start: {exc}")
        input("\nPress ENTER to close this window...")
