from __future__ import annotations

# ─────────────────────────  Standard library  ──────────────────────────
import json
import os
import shlex
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List

# ───────────────────────────  Third‑party  ────────────────────────────
import requests  # type: ignore

# ────────────────────────────  Blender  ───────────────────────────────
import bpy  # type: ignore

# ───────────────────────────  Local modules  ──────────────────────────
from .bat_utils import pack_blend
from .check_file_outputs import gather_render_outputs
from .rclone_platforms import (
    RCLONE_VERSION,
    get_platform_suffix,
    get_rclone_platform_dir,
    rclone_install_directory,
)

# ───────────────────────────  Configuration  ──────────────────────────
CLOUDFLARE_ACCOUNT_ID: str = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN: str = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

COMMON_RCLONE_FLAGS: List[str] = [
    "--s3-provider",
    "Cloudflare",
    "--s3-env-auth",
    "--s3-region",
    "auto",
    "--s3-no-check-bucket",
]

# ╭────────────────────────────  Utils  ───────────────────────────────╮
def _log(msg: str) -> None:
    """Thin wrapper around *print* that always flushes."""
    print(msg, flush=True)


def download_file_with_progress(url: str, dest_path: Path) -> None:
    """Download *url* to *dest_path*, showing a percentage bar."""
    _log(f"⬇️  Downloading {url}")
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()

    total_length = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    bar_length = 40

    with dest_path.open("wb") as fp:
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            fp.write(chunk)
            downloaded += len(chunk)

            if total_length:
                filled = int(bar_length * downloaded / total_length)
                bar = "█" * filled + "-" * (bar_length - filled)
                percent = (downloaded / total_length) * 100
                print(f"\r    |{bar}| {percent:5.1f}% ", end="", flush=True)

    if total_length:
        print()  # newline


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

    download_file_with_progress(download_url, zip_temp_path)

    _log("📦  Extracting rclone…")
    with zipfile.ZipFile(zip_temp_path) as zf:
        for member in zf.infolist():
            if member.filename.lower().endswith(("rclone.exe", "rclone")):
                member.filename = os.path.basename(member.filename)
                zf.extract(member, plat_dir)
                extracted = plat_dir / member.filename
                if extracted.name != bin_name:
                    extracted.rename(rclone_bin)
                break

    zip_temp_path.unlink(missing_ok=True)

    if not suffix.startswith("windows"):
        rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)

    return rclone_bin


def _shorten(path_or_remote: str) -> str:
    """Return only the filename or remote bucket path for pretty output."""
    if path_or_remote.startswith(":s3:"):
        # keep bucket and trailing path
        return path_or_remote
    # local path -> basename
    return Path(path_or_remote).name

def run_rclone(cmd: List[str]) -> None:
    """
    Execute *rclone* with live progress and a concise status line.

    Examples of what the user will see:
        Copying    my_scene.zip  →  :s3:render-bucket/
        Moving     deps.txt      →  :s3:render-bucket/project/
    """
    extra = ["--stats=1s", "--progress"]
    full_cmd = [*cmd, *extra]

    # ── Extract human‑friendly info (verb, src, dst) ──────────────────
    #   cmd structure: [rclone_bin, verb, *args_before_flags, --flag …]
    verb = None
    positional: List[str] = []
    for token in full_cmd[1:]:      # skip binary
        if token.startswith("--"):
            break                   # flags begin; stop collecting
        positional.append(token)

    if positional:
        verb = positional[0].capitalize()
    if len(positional) >= 3:
        # copy/move/moveto src dst [opts]
        src = _shorten(positional[-2])
        dst = _shorten(positional[-1])
        print(f"{verb:9} {src}  →  {dst}", flush=True)
    else:
        # Fallback (rare)
        print(f"{verb or 'Rclone'} …", flush=True)

    # ── Run rclone, inheriting stdout/stderr so progress is live ───────
    try:
        subprocess.run(full_cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"rclone failed (exit {exc.returncode})") from None


# ╭────────────────────────────  Helper  ──────────────────────────────╮
def _choose(use_scene_value: bool, scene_val, prop_val):
    """Return *scene_val* if *use_scene_value* else *prop_val*."""
    return scene_val if use_scene_value else prop_val


# ╭─────────────────────  Blender Operator  ───────────────────────────╮
class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submit the current .blend file to the Superluminal Render Farm."""

    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal"

    def execute(self, context):  # noqa: C901
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__package__].preferences
        job_id = uuid.uuid4()

        # ─────────────────────  Resolve settings  ─────────────────────
        job_name = _choose(props.use_file_name, Path(bpy.data.filepath).stem, props.job_name)
        render_format = _choose(
            props.use_scene_render_format, scene.render.image_settings.file_format, props.render_format
        )
        start_frame = _choose(props.use_scene_frame_range, scene.frame_start, props.frame_start)
        end_frame = _choose(props.use_scene_frame_range, scene.frame_end, props.frame_end)

        start_frame = start_frame if (props.render_type == "ANIMATION" and props.use_scene_frame_range) else scene.frame_current
        end_frame = end_frame if props.render_type == "ANIMATION" else start_frame

        render_engine = scene.render.engine.upper()
        blender_version = props.blender_version

        # ───────────────────────  File paths  ─────────────────────────
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

        # ─────────────  Decide packaging method & gather files ─────────────
        method = "PROJECT" if props.use_upload_project else "ZIP"
        project_path = Path(bpy.path.abspath(props.project_path)).resolve()
        required_storage = 0

        if method == "PROJECT":
            _log("🔍  Finding dependencies…")
            file_map = pack_blend(blend_path, target="", method=method, project_path=project_path)
            dep_count = len(file_map) - 1  # minus main blend
            _log(f"📄  Found {dep_count} dependencies")

            main_blend_s3_path = str(file_map[Path(blend_path)])
            with filelist_filename.open("w", encoding="utf-8") as fp:
                for idx, (file_path, packed_path) in enumerate(file_map.items(), 1):
                    required_storage += os.path.getsize(file_path)
                    if str(file_path) == str(blend_path):
                        continue
                    _log(f"    [{idx}/{dep_count}] writing {packed_path}")
                    fp.write(str(packed_path).replace("\\", "/") + "\n")

        else:  # ZIP
            _log("📦  Creating .zip archive of the project…")
            pack_blend(blend_path, str(zip_filename), method=method)
            if not zip_filename.exists():
                self.report({"ERROR"}, "Zipping the blend file failed.")
                return {"CANCELLED"}
            required_storage = zip_filename.stat().st_size

        if method == "PROJECT" and not filelist_filename.exists():
            self.report({"ERROR"}, "Packing the blend file failed.")
            return {"CANCELLED"}

        # ────────────────────────  Job metadata  ───────────────────────
        selected_project_id = prefs.project_list
        if selected_project_id == "NONE":
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        job_payload: Dict[str, Dict[str, object]] = {
            "job_data": {
                "id": str(job_id),
                "project_id": selected_project_id,
                "main_file": Path(blend_path).name if method == "ZIP" else str(main_blend_s3_path),
                "project_path": str(project_path.stem),
                "name": job_name,
                "status": "queued",
                "start": start_frame,
                "end": end_frame,
                "render_passes": {},
                "render_format": render_format,
                "render_engine": render_engine,
                "blender_version": blender_version,
                "required_storage": required_storage,
                "zip": method == "ZIP",
            }
        }

        # ────────────────  Retrieve S3 credentials  ───────────────────
        _log("🔑  Fetching R2 access credentials…")
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
            return [
                str(rclone_bin),
                *subcmd,
                "--s3-endpoint",
                endpoint_url,
                "--s3-access-key-id",
                s3_info["access_key_id"],
                "--s3-secret-access-key",
                s3_info["secret_access_key"],
                "--s3-session-token",
                s3_info["session_token"],
                "--s3-region",
                "auto",
                *COMMON_RCLONE_FLAGS,
            ]

        # ─────────────────────────  Upload  ───────────────────────────
        _log("🚀  Uploading assets to R2…")
        if method == "ZIP":
            run_rclone(build_rclone_cmd("copy", str(zip_filename), f":s3:{bucket_name}/"))
        else:  # PROJECT upload
            _log("📤  Uploading project files…")
            run_rclone(
                build_rclone_cmd(
                    "copy",
                    f"--files-from={filelist_filename}",
                    str(project_path),
                    f":s3:{bucket_name}/{project_path.stem}",
                    "--checksum",
                )
            )

            with filelist_filename.open("a", encoding="utf-8") as fp:
                fp.write(main_blend_s3_path.replace("\\", "/"))

            _log("📤  Uploading dependency list…")
            run_rclone(
                build_rclone_cmd(
                    "move",
                    str(filelist_filename),
                    f":s3:{bucket_name}/{project_path.stem}",
                    "--checksum",
                )
            )

            dest_remote = f":s3:{bucket_name}/{project_path.stem}/{main_blend_s3_path}"
            _log("📤  Uploading main .blend…")
            run_rclone(
                build_rclone_cmd(
                    "moveto",
                    str(tmp_blend_path),
                    dest_remote,
                    "--checksum",
                    "--ignore-times",
                )
            )

        # ─────────────────────  Post job metadata  ────────────────────
        _log("🗄️   Registering job in PocketBase…")
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
            submit_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {prefs.user_token}",
            }
            requests.post(
                submit_url, headers=submit_headers, data=json.dumps(job_payload), timeout=30
            ).raise_for_status()
        except Exception as exc:
            self.report({"ERROR"}, f"Error submitting job data: {exc}")
            return {"CANCELLED"}

        _log("✅  Job submitted successfully.")
        self.report({"INFO"}, "Job submitted successfully.")
        return {"FINISHED"}


# ╭────────────────────────  Blender hooks  ──────────────────────────╮
classes = (SUPERLUMINAL_OT_SubmitJob,)


def register() -> None:  # pylint: disable=invalid-name
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:  # pylint: disable=invalid-name
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
