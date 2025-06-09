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

# ─── third-party ────────────────────────────────────────────────
import requests  # type: ignore


# ╭────────────────────  read hand-off  ─────────────────────╮
if len(sys.argv) != 2:
    _log("Usage: download_worker.py <handoff.json>")
    sys.exit(1)

t_start = time.perf_counter()
handoff_path = Path(sys.argv[1]).resolve(strict=True)
data: Dict[str, object] = json.loads(handoff_path.read_text("utf-8"))

# ╭─────────────────  import add-on internals  ─────────────────╮
addon_dir = Path(data["addon_dir"]).resolve()
pkg_name = addon_dir.name.replace("-", "_")
sys.path.insert(0, str(addon_dir.parent))
pkg = types.ModuleType(pkg_name)
pkg.__path__ = [str(addon_dir)]
sys.modules[pkg_name] = pkg

# Import rclone helpers from the shipped add-on
rclone = importlib.import_module(f"{pkg_name}.transfers.rclone")
run_rclone = rclone.run_rclone
ensure_rclone = rclone.ensure_rclone

worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")

# ─── internal utils ────────────────────────────────────────────
_log = worker_utils.logger
_build_base = worker_utils._build_base
_short = worker_utils._short
is_blend_saved = worker_utils.is_blend_saved
requests_retry_session = worker_utils.requests_retry_session
CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN

# ╭───────────────────────  main  ───────────────────────────────╮
def main() -> None:
    # Use the resilient, retry-enabled session for *all* HTTP calls
    session = requests_retry_session()
    headers = {"Authorization": data["user_token"]}

    job_id: str = data["job_id"]
    job_name: str = data["job_name"]
    download_path: str = data["download_path"]

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
    rclone_bin = ensure_rclone(logger=_log)
    base_cmd: List[str] = _build_base(
        rclone_bin,
        f"https://{CLOUDFLARE_R2_DOMAIN}",
        s3info,
    )

    # Build rclone arguments
    rclone_args: list[str] = [
        "--exclude",
        "thumbnails/**",
        "--transfers",
        "16",
        "--checkers",
        "16",
        "--stats=1s",
    ]
    if not os.path.exists(download_path):
        rclone_args.extend(["--no-check-dest", "--ignore-times"])

    # Ensure destination directory exists
    dest_dir = os.path.join(download_path, job_name)
    os.makedirs(dest_dir, exist_ok=True)

    _log("🚀  Downloading render output…")
    try:
        run_rclone(
            base_cmd,
            "copy",
            f":s3:{bucket}/{job_id}/output/",
            dest_dir + "/",
            rclone_args,
        )
    except RuntimeError as exc:
        _log(f"❌  rclone failed: {exc}")
        sys.exit(1)

    elapsed = time.perf_counter() - t_start
    _log("🎉  Download complete!")
    _log(f"🕒  Took {elapsed:.1f}s in total.")
    input("\nPress ENTER to close this window…")


# ╭──────────────────  entry  ───────────────────╮
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        _log(f"\n❌  Download failed: {exc}")
        input("\nPress ENTER to close this window…")
