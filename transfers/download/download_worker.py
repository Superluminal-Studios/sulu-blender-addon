"""
download_worker.py – Superluminal Submit: asset-download helper
Relies on the generic utilities defined in submit_utils.py.
"""

from __future__ import annotations

# ─── stdlib ──────────────────────────────────────────────────────
import importlib
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import Dict, List
import traceback

# ───────────────────  third-party  ─────────────────────
import requests 


# ───────────────────  read hand-off  ─────────────────────
try:
    t_start = time.perf_counter()
    handoff_path = Path(sys.argv[1]).resolve(strict=True)
    data: Dict[str, object] = json.loads(handoff_path.read_text("utf-8"))

    # ────────────────  import add-on internals  ─────────────────
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")
    sys.path.insert(0, str(addon_dir.parent))
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    # ───────────────────  import helpers  ─────────────────────
    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone")
    run_rclone = rclone.run_rclone
    ensure_rclone = rclone.ensure_rclone
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")

    # ───────────────────  internal utils  ─────────────────────
    _log = worker_utils.logger
    _build_base = worker_utils._build_base
    is_blend_saved = worker_utils.is_blend_saved
    requests_retry_session = worker_utils.requests_retry_session
    CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN

except Exception as exc:
    print(f"❌  Failed to import helpers: {exc}")
    print(f"Error type: {type(exc)}")

    traceback.print_exc()
    input("\nPress ENTER to close this window…")
    sys.exit(1)


def single_downloader():
    base_cmd = _build_base(
        rclone_bin,
        f"https://{CLOUDFLARE_R2_DOMAIN}",
        s3info,
    )

    rclone_args = [
        "--exclude",
        "thumbnails/**",
        "--transfers",
        "16",
        "--checkers",
        "16",
    ]

    dest_dir = os.path.join(download_path, job_name)
    
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)
        rclone_args.extend(["--no-check-dest", "--ignore-times"])

    try:
        run_rclone(
            base_cmd,
            "copy",
            f":s3:{bucket}/{job_id}/output/",
            dest_dir + "/",
            rclone_args,
            logger=_log,
        )   
    except RuntimeError as exc:
        _log(f"❌  rclone failed: {exc}")
        sys.exit(1)


def auto_downloader():
    keep_running = True
    finished_frames = 0
    notification_sent = False

    while keep_running:
        response = session.get(f"{data['sarfis_url']}/api/job_details?job_id={job_id}", headers={"Auth-Token": data["sarfis_token"]})
        if response.status_code == 200:
            job_data = response.json().get("body", {})
            
            if not notification_sent:
                if job_data["status"] in ["running", "queued"]:
                    _log("\nℹ️  Keep this window open to automatically download frames as they finish.")
                    _log("🔄  Waiting for at least 10% of frames to be finished.")
                    notification_sent = True

            if (finished_frames + job_data["total_tasks"] // 10) < job_data["tasks"]["finished"] and (job_data["status"] in ["running", "queued"]):
                _log(f"\n🔄  {job_data['tasks']['finished'] - finished_frames} new frames since last download.")
                finished_frames = job_data["tasks"]["finished"]
                single_downloader()

            if job_data["status"] in ["finished", "paused", "error"]:
                _log("\n🔄  Downloading remaining frames.")
                single_downloader()
                keep_running = False

        else:
            _log(f"❌  Failed to get job data: {response.status_code}")

        time.sleep(1)




# ───────────────────  main  ───────────────────────────────
def main() -> None:
    global session
    global job_id
    global job_name
    global download_path
    global rclone_bin
    global s3info
    global bucket
    
    
    session = requests_retry_session()
    headers = {"Authorization": data["user_token"]}
    job_id = data["job_id"]
    job_name = data["job_name"]
    download_path = data["download_path"]
    rclone_bin = ensure_rclone(logger=_log)

    # ─────── obtain R2 credentials ───────────────────────────
    _log("🔑  Fetching R2 credentials…")
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
        s3info = s3_resp.json()["items"][0]
        bucket = s3info["bucket_name"]
    except (IndexError, requests.RequestException) as exc:
        _log(f"❌  Failed to obtain bucket credentials: {exc}")
        sys.exit(1)

    # ─────── rclone download ─────────────────────────────────
    
    
    # if data["download_type"] == "single":
    #     _log("🚀  Downloading render output…")
    #     single_downloader()
    #     elapsed = time.perf_counter() - t_start
    #     _log("🎉  Download complete!")
    #     _log(f"🕒  Took {elapsed:.1f}s in total.")
    #     input("\nPress ENTER to close this window…")

    # elif data["download_type"] == "auto":
    #     _log("🔄  Waiting for frames to download…")
    #     auto_downloader()
    #     elapsed = time.perf_counter() - t_start
    #     _log("🎉  Download complete!")
    #     input("\nPress ENTER to close this window…")
    try:
        
        auto_downloader()
        _log("✅  Download complete!")
        input("\nPress ENTER to close this window…")
    except Exception as exc:
        _log(f"❌  Download failed: {exc}")
        input("\nPress ENTER to close this window…")


# ───────────────────  entry  ─────────────────────
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        _log(f"\n❌  Download failed: {exc}")
        input("\nPress ENTER to close this window…")
