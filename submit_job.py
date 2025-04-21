from __future__ import annotations

# Standard library
import json
import os
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List

# Third‑party
import requests

# Blender
import bpy

# Local modules
from .bat_utils import pack_blend
from .check_file_outputs import gather_render_outputs
from .rclone_platforms import (
    RCLONE_VERSION,
    get_platform_suffix,
    get_rclone_platform_dir,
    rclone_install_directory,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLOUDFLARE_ACCOUNT_ID: str = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN: str = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

# rclone flags that never change
COMMON_RCLONE_FLAGS: List[str] = [
    "--s3-provider",
    "Cloudflare",
    "--s3-env-auth",
    "--s3-region",
    "auto",
    "--s3-no-check-bucket",
]

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def download_file_with_progress(url: str, dest_path: Path) -> None:
    """Download *url* to *dest_path*, showing progress when possible."""
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()

    total_length = resp.headers.get("Content-Length")
    if total_length is None:
        dest_path.write_bytes(resp.content)
        return

    total_length = int(total_length)
    downloaded = 0
    with dest_path.open("wb") as fp:
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            fp.write(chunk)
            downloaded += len(chunk)
            percent = int(downloaded * 100 / total_length)
            print(f"Downloading: {percent}% ({downloaded}/{total_length} bytes)", end="\r")
    print()  # ensure newline after completion


def ensure_rclone() -> Path:
    """Ensure a platform‑appropriate *rclone* binary exists and return its path."""
    rclone_dir = rclone_install_directory()
    rclone_dir.mkdir(parents=True, exist_ok=True)

    suffix = get_platform_suffix()
    plat_dir = get_rclone_platform_dir(suffix)
    plat_dir.mkdir(parents=True, exist_ok=True)

    bin_name = "rclone.exe" if suffix.startswith("windows") else "rclone"
    rclone_bin = plat_dir / bin_name

    if rclone_bin.exists():
        return rclone_bin

    zip_temp_path = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"
    download_url = (
        f"https://downloads.rclone.org/{RCLONE_VERSION}/"
        f"rclone-{RCLONE_VERSION}-{suffix}.zip"
    )

    try:
        download_file_with_progress(download_url, zip_temp_path)
        with zipfile.ZipFile(zip_temp_path) as zf:
            for member in zf.infolist():
                if member.filename.lower().endswith(("rclone.exe", "rclone")):
                    member.filename = os.path.basename(member.filename)
                    zf.extract(member, plat_dir)
                    extracted = plat_dir / member.filename
                    if extracted.name != bin_name:
                        extracted.rename(rclone_bin)
                    break
    finally:
        zip_temp_path.unlink(missing_ok=True)

    if not suffix.startswith("windows"):
        rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)

    return rclone_bin


def run_rclone(cmd: List[str]) -> None:
    """Run *rclone* with progress output forwarded to stdout."""
    extra = ["--stats=1s", "--verbose"]
    process = subprocess.Popen(
        [*cmd, *extra],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    stdout, stderr = process.communicate()
    print(stdout.decode())
    print(stderr.decode())

    if process.returncode:
        raise RuntimeError(f"rclone failed with exit code {process.returncode}")


# ---------------------------------------------------------------------------
# Blender Operator
# ---------------------------------------------------------------------------

def _choose(use_scene_value: bool, scene_val, prop_val):
    """Return *scene_val* if *use_scene_value* else *prop_val*."""
    return scene_val if use_scene_value else prop_val


class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submit the current .blend file to the Superluminal Render Farm."""

    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal"

    def execute(self, context):  # noqa: C901 — Blender callbacks tend to be lengthy
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__package__].preferences
        job_id = uuid.uuid4()

        # ------------------------------------------------------------------
        # Resolve settings (fall back to props when not using scene values)
        # ------------------------------------------------------------------
        job_name = _choose(props.use_scene_job_name, scene.name, props.job_name)
        render_format = _choose(
            props.use_scene_render_format, scene.render.image_settings.file_format, props.render_format
        )
        start_frame = _choose(props.use_scene_frame_range, scene.frame_start, props.frame_start)
        end_frame = _choose(props.use_scene_frame_range, scene.frame_end, props.frame_end)
        frame_step = _choose(props.use_scene_frame_step, scene.frame_step, props.frame_step)
        batch_size = _choose(props.use_scene_batch_size, 1, props.batch_size)
        render_engine = scene.render.engine.upper()
        blender_version = props.blender_version

        # ------------------------------------------------------------------
        # Prepare paths
        # ------------------------------------------------------------------
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({"ERROR"}, "Please save your .blend file before submitting.")
            return {"CANCELLED"}

        tmp_blend_path = Path(tempfile.gettempdir()) / f"{job_id}.blend"
        bpy.ops.wm.save_as_mainfile(
            filepath=str(tmp_blend_path), copy=True, compress=True, relative_remap=False
        )

        zip_filename = Path(tempfile.gettempdir()) / f"{job_id}.zip"
        filelist_filename = Path(tempfile.gettempdir()) / f"{job_id}.txt"

        # ------------------------------------------------------------------
        # Decide packaging method and gather files
        # ------------------------------------------------------------------
        method = "PROJECT" if props.use_upload_project else "ZIP"
        project_path = Path(bpy.path.abspath(props.project_path)).resolve()
        required_storage = 0

        if method == "PROJECT":
            file_map = pack_blend(blend_path, target="", method=method, project_path=project_path)
            main_blend_s3_path = str(file_map[Path(blend_path)])

            with filelist_filename.open("w", encoding="utf-8") as fp:
                for file_path, packed_path in file_map.items():
                    required_storage += os.path.getsize(file_path)
                    print(str(packed_path))
                    if str(file_path) != str(blend_path):
                        fp.write(str(packed_path).replace("\\", "/") + "\n")

        else:  # ZIP
            pack_blend(blend_path, str(zip_filename), method=method)
            if not zip_filename.exists():
                self.report({"ERROR"}, "Zipping the blend file failed.")
                return {"CANCELLED"}
            required_storage = zip_filename.stat().st_size

        if method == "PROJECT" and not filelist_filename.exists():
            self.report({"ERROR"}, "Packing the blend file failed.")
            return {"CANCELLED"}

        # ------------------------------------------------------------------
        # Build job metadata
        # ------------------------------------------------------------------
        selected_project_id = prefs.project_list
        if selected_project_id == "NONE":
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        job_payload = {
            "job_data": {
                "id": str(job_id),
                "project_id": selected_project_id,
                "main_file": Path(blend_path).name if method == "ZIP" else str(main_blend_s3_path),
                "project_path": str(project_path.stem),
                "name": job_name,
                "status": "queued",
                "start": start_frame,
                "end": end_frame,
                "frame_step": frame_step,
                "batch_size": batch_size,
                "render_passes": {},
                "render_format": render_format,
                "version": "20241125",
                "render_engine": render_engine,
                "blender_version": blender_version,
                "required_storage": required_storage,
                "zip": method == "ZIP",
            }
        }

        # ------------------------------------------------------------------
        # Retrieve S3 credentials for the project
        # ------------------------------------------------------------------
        storage_url = f"{prefs.pocketbase_url}/api/collections/project_storage/records"
        headers = {"Authorization": prefs.user_token}
        params = {"filter": f"(project_id='{selected_project_id}' && bucket_name~'render-')"}

        try:
            storage_resp = requests.get(storage_url, headers=headers, params=params, timeout=30)
            storage_resp.raise_for_status()
            storage_items = storage_resp.json().get("items") or []
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching project storage: {exc}")
            return {"CANCELLED"}

        if not storage_items:
            self.report({"ERROR"}, "No matching storage record found for the selected project.")
            return {"CANCELLED"}

        s3_info = storage_items[0]
        bucket_name = s3_info["bucket_name"]

        endpoint_url = f"https://{CLOUDFLARE_R2_DOMAIN}"
        rclone_bin = ensure_rclone()

        def build_rclone_cmd(*subcmd) -> List[str]:
            return [str(rclone_bin), *subcmd, "--s3-endpoint",
                    endpoint_url,
                    "--s3-access-key-id",
                    s3_info["access_key_id"],
                    "--s3-secret-access-key",
                    s3_info["secret_access_key"],
                    "--s3-session-token",
                    s3_info["session_token"],
                    "--s3-region",
                    "auto",
                    *COMMON_RCLONE_FLAGS]

        # ------------------------------------------------------------------
        # Upload assets via rclone
        # ------------------------------------------------------------------
        if method == "ZIP":
            run_rclone(build_rclone_cmd("copy", str(zip_filename), f":s3:{bucket_name}/"))
        else:  # PROJECT
            print("filelist", filelist_filename, "project_path", project_path, "bucket_name", bucket_name, "project_path", project_path.stem)

            with open(filelist_filename, "r", encoding="utf-8") as fp:
                print(fp.read())
                
            run_rclone(
                build_rclone_cmd(
                    "copy",
                    f"--files-from={filelist_filename}",
                    str(project_path),
                    f":s3:{bucket_name}/{project_path.stem}",
                    "--checksum",
                ),
            )

            with filelist_filename.open("a", encoding="utf-8") as fp:
                fp.write(main_blend_s3_path.replace("\\", "/"))

            run_rclone(
                build_rclone_cmd(
                    "move",
                    str(filelist_filename),
                    f":s3:{bucket_name}/{project_path.stem}",
                    "--checksum",
                ),
            )

            dest_remote = f":s3:{bucket_name}/{project_path.stem}/{main_blend_s3_path}"
            run_rclone(
                build_rclone_cmd(
                    "moveto",
                    str(tmp_blend_path), 
                    dest_remote,
                    "--checksum",
                    "--ignore-times",
                ),
            )

        # ------------------------------------------------------------------
        # Post job metadata to PocketBase
        # ------------------------------------------------------------------
        try:
            project_resp = requests.get(
                f"{prefs.pocketbase_url}/api/collections/projects/records",
                headers=headers,
                params={"filter": f"(id='{selected_project_id}')"},
                timeout=30,
            )
            project_resp.raise_for_status()
            org_id = project_resp.json()["items"][0]["organization_id"]
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching project data: {exc}")
            return {"CANCELLED"}

        job_payload["job_data"]["organization_id"] = org_id
        try:
            submit_url = f"{prefs.pocketbase_url}/api/farm/{org_id}/jobs"
            print(submit_url)
            submit_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {prefs.user_token}"}
            requests.post(submit_url, headers=submit_headers, data=json.dumps(job_payload), timeout=30).raise_for_status()
        except Exception as exc:
            self.report({"ERROR"}, f"Error submitting job data: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Job submitted successfully.")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Blender registration hooks
# ---------------------------------------------------------------------------
classes = (SUPERLUMINAL_OT_SubmitJob,)

def register() -> None:  # pylint: disable=invalid-name
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:  # pylint: disable=invalid-name
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
