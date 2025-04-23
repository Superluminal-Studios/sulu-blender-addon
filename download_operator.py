# ---------------------------------------------------------------------------
#  Download-Job-Output operator
# ---------------------------------------------------------------------------
import bpy
from bpy.props import StringProperty, PointerProperty
from bpy_extras.io_utils import ImportHelper
from pathlib import Path
from typing import List
import requests
import subprocess
from .rclone_platforms import get_platform_suffix, get_rclone_platform_dir
import uuid
import zipfile
import os
import tempfile

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


class SUPERLUMINAL_OT_DownloadOutput(bpy.types.Operator, ImportHelper):
    """Download the rendered output .zip from the Superluminal farm."""
    bl_idname = "superluminal.download_output"
    bl_label  = "Download Job Output"

    # Pop-up fields ─────────────────────────────────────────────
    filename_ext = ".zip"
    filter_glob  : StringProperty(
        default="*.zip",
        options={'HIDDEN'},
    )
    job_id       : StringProperty(
        name="Job ID",
        description="ID of the render job whose output you want to download",
    )

    # Rename the “File Path” label to something clearer
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "job_id")
        # layout.prop(self, "filepath", text="Save As")

    # Core logic ───────────────────────────────────────────────
    def execute(self, context):

        prefs = context.preferences.addons[__package__].preferences
        selected_project_id = prefs.project_list
        if selected_project_id == "NONE":
            self.report({'ERROR'}, "No project selected.")
            return {'CANCELLED'}

        # --------- fetch bucket & creds (same as submit) --------
        storage_url = f"{prefs.pocketbase_url}/api/collections/project_storage/records"
        headers     = {"Authorization": prefs.user_token}
        params      = {
            "filter": f"(project_id='{selected_project_id}' && bucket_name~'render-')"
        }
        try:
            s3info = (
                requests.get(storage_url, headers=headers, params=params, timeout=30)
                .json()["items"][0]
            )
        except Exception as exc:
            self.report({'ERROR'}, f"Could not get project storage: {exc}")
            return {'CANCELLED'}

        bucket = s3info["bucket_name"]

        # --------- ensure rclone --------------------------------
        rclone_bin = _ensure_rclone()
        endpoint   = f"https://{CLOUDFLARE_R2_DOMAIN}"

        def cmd(*subcmd) -> List[str]:
            return [
                str(rclone_bin),
                *subcmd,
                "--s3-endpoint", endpoint,
                "--s3-access-key-id",     s3info["access_key_id"],
                "--s3-secret-access-key", s3info["secret_access_key"],
                "--s3-session-token",     s3info["session_token"],
                "--s3-region", "auto",
                *COMMON_RCLONE_FLAGS,
                "--stats=1s",
                "--progress",
            ]

        # --------- build paths ----------------------------------
        remote   = f":s3:{bucket}/{self.job_id}/output/"
        local    = str(Path(self.filepath))

        print(f"Copying  {remote}  →  {local}")
        subprocess.run(cmd("copy", remote, local), check=True)

        self.report({'INFO'}, "Output downloaded.")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Register with Blender
# ---------------------------------------------------------------------------
def register():
    bpy.utils.register_class(SUPERLUMINAL_OT_DownloadOutput)

def unregister():
    bpy.utils.unregister_class(SUPERLUMINAL_OT_DownloadOutput)
