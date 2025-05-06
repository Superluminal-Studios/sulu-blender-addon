"""
submit_worker.py – external helper for Superluminal Submit.
"""

from __future__ import annotations

# ─── stdlib ──────────────────────────────────────────────────────
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Dict, List
import webbrowser

# third‑party
import requests  # type: ignore

# ╭────────────────────  read hand‑off  ─────────────────────╮
if len(sys.argv) != 2:
    print("Usage: download_worker.py <handoff.json>")
    sys.exit(1)

t_start = time.perf_counter()
handoff_path = Path(sys.argv[1]).resolve(strict=True)
data: Dict[str, object] = json.loads(handoff_path.read_text("utf-8"))

# ╭─────────────────  import add‑on internals  ─────────────────╮
addon_dir = Path(data["addon_dir"]).resolve()
pkg_name = addon_dir.name.replace("-", "_")
sys.path.insert(0, str(addon_dir.parent))
pkg = types.ModuleType(pkg_name)
pkg.__path__ = [str(addon_dir)]
sys.modules[pkg_name] = pkg

rclone = importlib.import_module(f"{pkg_name}.rclone")
rclone_url = rclone.get_rclone_url
ensure_rclone = rclone.ensure_rclone


# ╭────────────────────  constants  ───────────────────────────╮
CLOUDFLARE_ACCOUNT_ID = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
COMMON_RCLONE_FLAGS = [
    "--s3-provider", "Cloudflare",
    "--s3-env-auth",
    "--s3-region", "auto",
    "--s3-no-check-bucket",
]

# ╭───────────────────  helpers  ──────────────────────────────╮
def _log(msg: str) -> None:
    print(msg, flush=True)

def _short(p: str) -> str:
    return p if p.startswith(":s3:") else Path(p).name



def _build_base(rclone_bin: Path, endpoint: str, s3: Dict[str, str]) -> List[str]:
    return [
        str(rclone_bin),
        "--s3-endpoint", endpoint,
        "--s3-access-key-id",     s3["access_key_id"],
        "--s3-secret-access-key", s3["secret_access_key"],
        "--s3-session-token",     s3["session_token"],
        "--s3-region", "auto",
        *COMMON_RCLONE_FLAGS,
    ]

def _run_rclone(base: List[str], verb: str, src: str, dst: str, extra: list[str]) -> None:
    _log(f"{verb.capitalize():9} {_short(src)}  →  {_short(dst)}")
    cmd = [base[0], verb, src, dst, *extra, "--stats=1s", "--progress", *base[1:]]
    subprocess.run(cmd, check=True)

# ╭───────────────────────  main  ───────────────────────────────╮
def main() -> None:
    hdr = {"Authorization": data["user_token"]}

    proj = requests.get(
    f"{data['pocketbase_url']}/api/collections/projects/records",
    headers=hdr,
    params={"filter": f"(id='{data['selected_project_id']}')"},
    timeout=30,
    ).json()["items"][0]

    
    project_name = proj["name"]

    job_id = data["job_id"]
    download_path = data["download_path"]

    
    # ───── credentials ─────
    _log("🔑  Fetching R2 credentials…")
    s3_request_url = f"{data['pocketbase_url']}/api/collections/project_storage/records"
    s3_request = {"filter": f"(project_id='{data['selected_project_id']}' && bucket_name~'render-')"}
    s3_response = requests.get(s3_request_url, headers=hdr, params=s3_request, timeout=30).json()["items"]
    s3info = s3_response[0]
    bucket = s3info["bucket_name"]

    # ───── rclone downloads ─────
    rclone_bin = ensure_rclone(logger=_log)
    base = _build_base(rclone_bin, f"https://{CLOUDFLARE_R2_DOMAIN}", s3info)
    _log("🚀  Uploading assets…")

    _run_rclone(
        base, "copy",
        f":s3:{bucket}/{project_name}/{job_id}/",
        download_path,
        ["--checksum"],
    )

# ╭──────────────────  entry  ───────────────────╮
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\n❌  Submission failed: {exc}")
        input("\nPress ENTER to close this window…")
