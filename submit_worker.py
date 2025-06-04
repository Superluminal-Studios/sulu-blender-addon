"""
submit_worker.py – Superluminal Submit worker (robust, with retries).
Business logic only; all generic helpers live in submit_utils.py.
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

# ─── third-party ────────────────────────────────────────────────
import requests  # type: ignore


# ╭────────────────────  read hand-off  ─────────────────────╮

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

shorten_path = importlib.import_module(f"{pkg_name}.worker_utils").shorten_path
bat_utils = importlib.import_module(f"{pkg_name}.bat_utils")
pack_blend = bat_utils.pack_blend
rclone = importlib.import_module(f"{pkg_name}.rclone")
run_rclone = rclone.run_rclone
rclone_url = rclone.get_rclone_url
ensure_rclone = rclone.ensure_rclone

# ─── internal utils ────────────────────────────────────────────

worker_utils = importlib.import_module(f"{pkg_name}.worker_utils")
_log = worker_utils.logger
_build_base = worker_utils._build_base
is_blend_saved = worker_utils.is_blend_saved
requests_retry_session = worker_utils.requests_retry_session
CLOUDFLARE_R2_DOMAIN = worker_utils.CLOUDFLARE_R2_DOMAIN


# ╭───────────────────────  main  ───────────────────────────────╮
def main() -> None:
    # Single resilient session for *all* HTTP traffic
    session = requests_retry_session()

    try:
        github_response = session.get(f"https://api.github.com/repos/Superluminal-Studios/sulu-blender-addon/releases/latest")
        if github_response.status_code == 200:
            latest_version = github_response.json().get("tag_name")
            if latest_version:
                latest_version = tuple(int(i) for i in latest_version.split('.'))
                if latest_version > tuple(data["addon_version"]):
                    answer = input(f"A new version of the Superluminal Render Farm addon is available, would you like to update? (y/n)")
                    if answer.lower() == "y":
                        webbrowser.open("https://superlumin.al/blender-addon")
                        print("\nhttps://superlumin.al/blender-addon")
                        _log("\nInstructions: \n    📥 Download the latest addon zip from the link above.\n    🔧 Install the latest version of the addon in Blender.\n    ❌ Close this window.\n    🔄 Restart Blender.")
                        input("\nPress ENTER to close this window…")

    except SystemExit:
        sys.exit(0)

    except:
        _log("❌ Failed to check for addon updates, continuing with job submission…")

    headers = {"Authorization": data["user_token"]} 

    try:
        rclone_bin = ensure_rclone(logger=_log)
        
    except Exception as e:
        _log(f"❌  Failed to download rclone: {e}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    # ─────── fetch project meta ──────────────────────────────
    try:
        proj_resp = session.get(
            f"{data['pocketbase_url']}/api/collections/projects/records",
            headers=headers,
            params={"filter": f"(id='{data['selected_project_id']}')"},
            timeout=30,
        )
        if proj_resp.status_code != 200:
            _log(f"❌  Failed to fetch project record: {proj_resp.json()}")
            _log("⚠️  Check that your project is selected, and that you are logged in. You can also try logging out and back in again.")
            input("\nPress ENTER to close this window…")
            sys.exit(1)

        proj = proj_resp.json()["items"][0]

    except requests.RequestException as exc:
        _log(f"❌  Could not retrieve project record: {exc}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    # ─────── verify farm availability ───────────────────────
    try:
        farm_status = session.get(
            f"{data['pocketbase_url']}/api/farm_status/{proj['organization_id']}",
            headers=headers,
            timeout=30,
        )
        if farm_status.status_code != 200:
            _log(f"❌  Failed to fetch farm status: {farm_status.json()}")
            _log("⚠️  Check that your project is selected, and that you are logged in. You can also try logging out and back in again.")
            input("\nPress ENTER to close this window…")
            sys.exit(1)

    except Exception as exc:
        _log(f"❌  Failed to fetch farm status: {exc}")
        _log("⚠️  Check that your project is selected, and that you are logged in. You can also try logging out and back in again.")
        input("\nPress ENTER to close this window…")
        sys.exit(1)



    # ─────── local paths / settings ──────────────────────────
    blend_path: str = data["blend_path"]
    project_path = blend_path.replace("\\", "/").split("/")[0] + "/"
    use_project: bool = bool(data["use_project_upload"])
    automatic_project_path: bool = bool(data["automatic_project_path"])
    custom_project_path: str = data["custom_project_path"]
    job_id: str = data["job_id"]
    tmp_blend: str = data["temp_blend_path"]

    zip_file = Path(tempfile.gettempdir()) / f"{job_id}.zip"
    filelist = Path(tempfile.gettempdir()) / f"{job_id}.txt"

    org_id = proj["organization_id"]
    project_sqid = proj["sqid"]
    project_name = proj["name"]

    # ─────── wait until .blend is fully written ──────────────
    is_blend_saved(blend_path)


    # ─────── PACK ASSETS ─────────────────────────────────────
    if use_project:
        _log("🔍  Finding dependencies…")
        fmap: Dict[Path, Path] = pack_blend(
            blend_path,
            target="",
            method="PROJECT",
            project_path=project_path,
        )

        required_storage = 0
        file_list = [str(f).replace("\\", "/") for f in fmap.keys()]
        main_blend_s3 = file_list.pop(0)

        # Auto-detect base folder unless overridden
        same_disk = True
        for idx, f in enumerate(list(file_list)):
            path = os.path.abspath(os.path.join(project_path, f))

            if os.path.splitdrive(main_blend_s3)[0] == os.path.splitdrive(path)[0]:
                if os.path.isfile(path):
                    _log(f"✅  [{idx}/{len(file_list) - 1}] adding {shorten_path(path)}")
                    required_storage += os.path.getsize(path)
                else:
                    _log(f"❌  [{idx}/{len(file_list) - 1}] File not found {shorten_path(path)}")
                    file_list.remove(f)

            else:
                same_disk = False
                if os.path.isfile(path):
                    _log(f"❌  [{idx}/{len(file_list) - 1}] Off disk {shorten_path(path)}")
                    file_list.remove(f) 
                else:
                    _log(f"❌  [{idx}/{len(file_list) - 1}] File not found {shorten_path(path)}")
                    file_list.remove(f)

        if same_disk:
            _log("✅  All files are on the same disk")
        else:
            _log("⚠️  Files are on different disks")

        if automatic_project_path:
            if len(file_list) == 0:
                common_path = os.path.dirname(main_blend_s3)
            else:
                common_path = os.path.commonpath(file_list).replace("\\", "/")
        else:
            common_path = custom_project_path

        main_blend_s3 = main_blend_s3.replace(common_path + "/", "")

        packed_file_list = [f.replace(common_path + "/", "") for f in file_list]

        if len(file_list) == 0:
            _log("⚠️  No dependencies found, if this project is not a single blend file, check project path and try again.")

        with filelist.open("w", encoding="utf-8") as fp:
            fp.writelines(f"{f}\n" for f in packed_file_list)



    else:
        _log("📦  Creating .zip archive…")
        pack_blend(blend_path, str(zip_file), method="ZIP")
        required_storage = zip_file.stat().st_size

    # ─────── R2 credentials ──────────────────────────────────
    _log("🔑  Fetching R2 credentials…")
    try:
        s3_response = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={
                "filter": f"(project_id='{data['selected_project_id']}' && bucket_name~'render-')"
            },
            timeout=30,
        )
        s3_response.raise_for_status()
        if s3_response.status_code != 200:
            _log(f"❌  Failed to obtain bucket credentials: {s3_response.json()}")
            _log("⚠️  Check that your project is selected, and that you are logged in. You can also try logging out and back in again.")
            input("\nPress ENTER to close this window…")
            sys.exit(1)

        s3info = s3_response.json()["items"][0]
        bucket = s3info["bucket_name"]

    except (IndexError, requests.RequestException) as exc:
        _log(f"❌  Failed to obtain bucket credentials: {exc}")
        _log("⚠️  Check that your project is selected, and that you are logged in. You can also try logging out and back in again.")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    # ─────── rclone uploads ──────────────────────────────────
    
    base_cmd = _build_base(
        rclone_bin,
        f"https://{CLOUDFLARE_R2_DOMAIN}",
        s3info,
    )
    _log("🚀  Uploading assets…")

    try:
        if not use_project:
            run_rclone(base_cmd, "copy", str(zip_file), f":s3:{bucket}/", [])
        else:
            if len(file_list) > 0:
                # 1) Copy project files
                _log(f"\n📤  Uploading dependencies…")
                run_rclone(
                    base_cmd,
                    "copy",
                    str(common_path),
                    f":s3:{bucket}/{project_name}/",
                    ["--files-from", str(filelist), "--checksum"],
                )

            # 2) Upload the manifest so the worker knows what to grab
            with filelist.open("a", encoding="utf-8") as fp:
                fp.write(main_blend_s3.replace("\\", "/"))

            _log(f"\n📤  Uploading dependencies manifest…")
            run_rclone(
                base_cmd,
                "move",
                str(filelist),
                f":s3:{bucket}/{project_name}/",
                ["--checksum"],
            )

            # 3) Move the temp blend into place (fast, server-side)
            _log(f"\n📤  Uploading main blend…")
            move_to_path = f"{project_name}/{main_blend_s3}".lstrip("/")
            run_rclone(
                base_cmd,
                "moveto",
                str(tmp_blend),
                f":s3:{bucket}/{move_to_path}",
                ["--checksum", "--ignore-times"],
            )

        # Always move packed add-ons
        if data["packed_addons"]:
            _log(f"\n📤  Uploading packed add-ons…")
            run_rclone(
                base_cmd,
                "moveto",
                data["packed_addons_path"],
                f":s3:{bucket}/{job_id}/addons/",
                ["--checksum", "--ignore-times"],
            )
    except RuntimeError as exc:
        _log(f"\n❌  rclone failed: {exc}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)
    finally:
        # Clean up local temp artefacts if possible
        for p in (data["packed_addons_path"], os.path.dirname(str(tmp_blend))):
            try:
                os.remove(p)
            except Exception:
                pass

    # ─────── register job ────────────────────────────────────
    _log("\n🗄️   Submitting job to Superluminal…")
    payload: Dict[str, object] = {
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
            "end": data["end_frame"],
            "frame_step": 1,
            "batch_size": 1,
            "render_passes": data["render_passes"],
            "image_format": data["image_format"],
            "use_scene_image_format": data["use_scene_image_format"],
            "render_engine": data["render_engine"],
            "version": "20241125",
            "blender_version": data["blender_version"],
            "required_storage": required_storage,
            "zip": not use_project,
            "ignore_errors": data["ignore_errors"],
            "use_bserver": data["use_bserver"],
            "use_async_upload": data["use_async_upload"],
            "defer_status": data["use_async_upload"],
            "tasks": list(range(data["start_frame"], data["end_frame"] + 1, data["frame_stepping_size"]))
        }
    }

    try:
        post_resp = session.post(
            f"{data['pocketbase_url']}/api/farm/{org_id}/jobs",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        post_resp.raise_for_status()
    except requests.RequestException as exc:
        _log(f"\n❌  Job submission failed: {exc}")
        input("\nPress ENTER to close this window…")
        sys.exit(1)

    elapsed = time.perf_counter() - t_start
    _log(f"✅  Job submitted successfully.")
    _log(f"🕒  Submission took {elapsed:.1f}s in total.")

    # ─────── optional browser open ───────────────────────────
    try:
        handoff_path.unlink(missing_ok=True)
    except Exception:
        pass

    selection = input(
        "\nOpen job in your browser? y/n, or just press ENTER to close…\n"
    )
    if selection.lower() == "y":
        web_url = f"https://superlumin.al/p/{project_sqid}/farm/jobs/{job_id}"
        webbrowser.open(web_url)
        _log(f"🌐  Opened {web_url} in your browser.")
        input("\nPress ENTER to close this window…")
        sys.exit(1)


# ╭──────────────────  entry  ───────────────────╮
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        _log(f"\n❌  Submission failed: {exc}")
        input("\nPress ENTER to close this window…")
