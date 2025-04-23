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
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List

# third‑party
import requests  # type: ignore

# ╭────────────────────  read hand‑off  ─────────────────────╮
if len(sys.argv) != 2:
    print("Usage: submit_worker.py <handoff.json>")
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

bat_utils = importlib.import_module(f"{pkg_name}.bat_utils")
pack_blend = bat_utils.pack_blend
rclone_plat = importlib.import_module(f"{pkg_name}.rclone_platforms")
RCLONE_VERSION = rclone_plat.RCLONE_VERSION
get_platform_suffix = rclone_plat.get_platform_suffix
get_rclone_platform_dir = rclone_plat.get_rclone_platform_dir
rclone_install_directory = rclone_plat.rclone_install_directory

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

def _download_with_bar(url: str, dest: Path) -> None:
    _log("⬇️  Downloading rclone")
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("Content-Length", 0))
    done = 0
    bar = 40
    with dest.open("wb") as fp:
        for chunk in resp.iter_content(8192):
            fp.write(chunk)
            done += len(chunk)
            if total:
                filled = int(bar * done / total)
                print(f"\r    |{'█'*filled}{'-'*(bar-filled)}| {done*100/total:5.1f}% ",
                      end="", flush=True)
    if total:
        print()

def _ensure_rclone() -> Path:
    suf = get_platform_suffix()
    bin_name = "rclone.exe" if suf.startswith("windows") else "rclone"
    rclone_bin = get_rclone_platform_dir(suf) / bin_name
    if rclone_bin.exists():
        return rclone_bin
    tmp_zip = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"
    url = f"https://downloads.rclone.org/{RCLONE_VERSION}/rclone-{RCLONE_VERSION}-{suf}.zip"
    _download_with_bar(url, tmp_zip)
    _log("📦  Extracting rclone…")
    with zipfile.ZipFile(tmp_zip) as zf:
        for m in zf.infolist():
            if m.filename.lower().endswith(("rclone.exe", "rclone")):
                m.filename = os.path.basename(m.filename)
                zf.extract(m, rclone_bin.parent)
                (rclone_bin.parent / m.filename).rename(rclone_bin)
                break
    if not suf.startswith("windows"):
        rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)
    tmp_zip.unlink(missing_ok=True)
    return rclone_bin

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
    blend_path   = str(data["blend_path"])
    project_path = Path(data["project_path"])
    use_project  = bool(data["use_project_upload"])
    job_id       = data["job_id"]

    tmp_blend = Path(tempfile.gettempdir()) / f"{job_id}.blend"
    zip_file  = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist  = Path(tempfile.gettempdir()) / f"{job_id}.txt"
    tmp_blend.write_bytes(Path(blend_path).read_bytes())

    # ───── pack assets ─────
    if use_project:
        _log("🔍  Finding dependencies…")
        fmap = pack_blend(blend_path, target="", method="PROJECT", project_path=project_path)
        main_blend_s3 = str(fmap[Path(blend_path)])
        required_storage = 0
        with filelist.open("w", encoding="utf-8") as fp:
            for idx, (src, packed) in enumerate(fmap.items(), 1):
                if src == Path(blend_path):
                    continue
                required_storage += os.path.getsize(src)
                _log(f"    [{idx}/{len(fmap)-1}] writing {packed}")
                fp.write(str(packed).replace("\\", "/") + "\n")
    else:
        _log("📦  Creating .zip archive…")
        pack_blend(blend_path, str(zip_file), method="ZIP")
        required_storage = zip_file.stat().st_size

    # ───── credentials ─────
    _log("🔑  Fetching R2 credentials…")
    hdr = {"Authorization": data["user_token"]}
    url = f"{data['pocketbase_url']}/api/collections/project_storage/records"
    params = {"filter": f"(project_id='{data['selected_project_id']}' && bucket_name~'render-')"}
    s3info = requests.get(url, headers=hdr, params=params, timeout=30).json()["items"][0]
    bucket = s3info["bucket_name"]

    # ───── rclone uploads ─────
    rclone_bin = _ensure_rclone()
    base = _build_base(rclone_bin, f"https://{CLOUDFLARE_R2_DOMAIN}", s3info)
    _log("🚀  Uploading assets…")

    if not use_project:
        _run_rclone(base, "copy", str(zip_file), f":s3:{bucket}/", [])
    else:
        _run_rclone(
            base, "copy",
            str(project_path),
            f":s3:{bucket}/{project_path.stem}",
            ["--files-from", str(filelist), "--checksum"],
        )

        # append main .blend path so worker downloads it
        with filelist.open("a", encoding="utf-8") as fp:
            fp.write(main_blend_s3.replace("\\", "/"))

        _run_rclone(
            base, "move",
            str(filelist),
            f":s3:{bucket}/{project_path.stem}",
            ["--checksum"],
        )
        _run_rclone(
            base, "moveto",
            str(tmp_blend),
            f":s3:{bucket}/{project_path.stem}/{main_blend_s3}",
            ["--checksum", "--ignore-times"],
        )

    # ───── register job ─────
    _log("🗄️   Submitting job to Superluminal…")
    proj = requests.get(
        f"{data['pocketbase_url']}/api/collections/projects/records",
        headers=hdr,
        params={"filter": f"(id='{data['selected_project_id']}')"},
        timeout=30,
    ).json()["items"][0]
    org_id = proj["organization_id"]

    payload = {
        "job_data": {
            "id": job_id,
            "project_id": data["selected_project_id"],
            "organization_id": org_id,
            "main_file": Path(blend_path).name if not use_project else main_blend_s3,
            "project_path": project_path.stem,
            "name": data["job_name"],
            "status": "queued",
            "start": data["start_frame"],
            "end":   data["end_frame"],
            "frame_step": 1,
            "batch_size": 1,
            "render_passes": data["render_passes"],
            "render_format": data["render_format"],
            "render_engine": data["render_engine"],
            "version": "20241125",
            "blender_version": data["blender_version"],
            "required_storage": required_storage,
            "zip": (not use_project),
        }
    }
    post_url = f"{data['pocketbase_url']}/api/farm/{org_id}/jobs"
    requests.post(
        post_url,
        headers={**hdr, "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=30,
    ).raise_for_status()

    elapsed = time.perf_counter() - t_start
    _log(f"✅  Job submitted successfully.\n🕒  Submission took {elapsed:.1f}s in total.")
    # input("\nPress ENTER to close this window…")
    handoff_path.unlink(missing_ok=True)

# ╭──────────────────  entry  ───────────────────╮
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\n❌  Submission failed: {exc}")
        input("\nPress ENTER to close this window…")
