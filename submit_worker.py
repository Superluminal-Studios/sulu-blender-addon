"""
submit_worker.py – external helper for Superluminal Submit.
"""

from __future__ import annotations

# ─── stdlib ──────────────────────────────────────────────────────
import importlib
import json
import os
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
rclone = importlib.import_module(f"{pkg_name}.rclone")
run_rclone = rclone.run_rclone
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

def is_blend_saved(path):
    saving = True
    warned = False
    while saving:
        if not os.path.exists(path+"@"):
            saving = False
        else:
            if not warned:
                _log("⚠️  Warning: The primary blend is still being saved.\n")

                _log("This may be caused by Dropbox, Google Drive, OneDrive, or similar software.")
                _log("Please close any syncing software that may be trying to access your blend file. ")
                warned = True
            time.sleep(0.25)
    else:
        if warned:
            _log("✅  File is saved. Proceeding with submission.")


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

# ╭───────────────────────  main  ───────────────────────────────╮
def main() -> None:
    session = requests.Session()
    headers = {"Authorization": data["user_token"]}
    proj = session.get(
    f"{data['pocketbase_url']}/api/collections/projects/records",
    headers=headers,
    params={"filter": f"(id='{data['selected_project_id']}')"},
    timeout=30,
    ).json()["items"][0]

    farm_status = session.get(
        f"{data['pocketbase_url']}/api/farm_status/{proj['organization_id']}",
        headers=headers,
        timeout=30,
    ).json()

    print(json.dumps(farm_status, indent=4))


    blend_path   = str(data["blend_path"])
    project_path = blend_path.replace('\\', '/').split('/')[0] + '/'
    use_project  = bool(data["use_project_upload"])
    job_id       = data["job_id"]
    tmp_blend = data["temp_blend_path"]
    zip_file  = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist  = Path(tempfile.gettempdir()) / f"{job_id}.txt"
    org_id = proj["organization_id"]
    project_sqid = proj["sqid"]
    project_name = proj["name"]

    is_blend_saved(blend_path)

    # ───── pack assets ─────
    
    if use_project:
        _log("🔍  Finding dependencies…")
        fmap = pack_blend(blend_path, target="", method="PROJECT", project_path=project_path)
        required_storage = 0
        file_list = []

        for idx, (src, packed) in enumerate(fmap.items(), 1):
            if src == Path(blend_path):
                main_blend_s3 = str(src).replace("\\", "/")
            required_storage += os.path.getsize(src)
            _log(f"    [{idx}/{len(fmap)-1}] writing {src}")
            path = str(src).replace("\\", "/")
            file_list.append(path)

        project_path_base = os.path.commonpath([os.path.abspath(os.path.join(project_path, f)) for f in file_list]).replace("\\", "/")
        packed_file_list = [f.replace(project_path_base+"/", "") for f in file_list]
        main_blend_s3 = main_blend_s3.replace(project_path_base+"/", "")

        with filelist.open("w", encoding="utf-8") as fp:
            for f in packed_file_list:
                fp.write(f.replace("\\", "/") + "\n")

    else:
        _log("📦  Creating .zip archive…")
        pack_blend(blend_path, str(zip_file), method="ZIP")
        required_storage = zip_file.stat().st_size

    # ───── credentials ─────
    _log("🔑  Fetching R2 credentials…")
    s3_request_url = f"{data['pocketbase_url']}/api/collections/project_storage/records"
    s3_request = {"filter": f"(project_id='{data['selected_project_id']}' && bucket_name~'render-')"}
    s3_response = session.get(s3_request_url, headers=headers, params=s3_request, timeout=30).json()["items"]
    s3info = s3_response[0]
    bucket = s3info["bucket_name"]



    # ───── rclone uploads ─────
    rclone_bin = ensure_rclone(logger=_log)
    base = _build_base(rclone_bin, f"https://{CLOUDFLARE_R2_DOMAIN}", s3info)
    _log("🚀  Uploading assets…")

    if not use_project:
        run_rclone(base, "copy", str(zip_file), f":s3:{bucket}/", [])
    else:
        run_rclone(
            base, "copy",
            str(project_path_base),
            f":s3:{bucket}/{project_name}/",
            ["--files-from", str(filelist), "--checksum"],
        )

        # append main .blend path so worker downloads it

        with filelist.open("a", encoding="utf-8") as fp:
            fp.write(main_blend_s3.replace("\\", "/"))

        run_rclone(
            base, "move",
            str(filelist),
            f":s3:{bucket}/{project_name}/",
            ["--checksum"],
        )

        move_to_path = f"{project_name}/{main_blend_s3}"
        if move_to_path.startswith("/"):
            move_to_path = move_to_path[1:]
            
        run_rclone(
            base, "moveto",
            str(tmp_blend),
            f":s3:{bucket}/{move_to_path}",
            ["--checksum", "--ignore-times"],
        )

    run_rclone(
        base, "moveto",
        data["packed_addons_path"],
        f":s3:{bucket}/{job_id}/addons/",
        ["--checksum", "--ignore-times"],
    )

    try:
        os.remove(data["packed_addons_path"])
        os.remove(os.path.dirname(str(tmp_blend)))
    except:
        pass

    # ───── register job ─────
    _log("🗄️   Submitting job to Superluminal…")
    
    _log(f"packed_addons: {data['packed_addons']}")
    payload = {
        "job_data": {
            "id": job_id,
            "project_id": data["selected_project_id"],
            "packed_addons": data["packed_addons"],
            "organization_id": org_id,
            "main_file": Path(blend_path).name if not use_project else main_blend_s3,
            "project_path": project_name,
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
            "ignore_errors": data["ignore_errors"],
        }
    }

    post_url = f"{data['pocketbase_url']}/api/farm/{org_id}/jobs"
    session.post(
        post_url,
        headers={**headers, "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=30,
    ).raise_for_status()

    elapsed = time.perf_counter() - t_start
    _log(f"✅  Job submitted successfully.\n🕒  Submission took {elapsed:.1f}s in total.")
    
    handoff_path.unlink(missing_ok=True)
    selection = input("\nOpen job in your browser? y/n, Or just press ENTER to close this window…\n")
    if selection.lower() == "y":
        web_url = f"https://superlumin.al/p/{project_sqid}/farm/jobs/{job_id}"
        webbrowser.open(web_url)
        _log(f"🌐  Opened {web_url} in your browser.")
        input("\nPress ENTER to close this window…")

# ╭──────────────────  entry  ───────────────────╮
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\n❌  Submission failed: {exc}")
        input("\nPress ENTER to close this window…")
