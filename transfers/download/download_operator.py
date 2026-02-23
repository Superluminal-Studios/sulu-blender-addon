# operators/download_job_operator.py
from __future__ import annotations

import bpy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from ...utils.worker_utils import launch_in_terminal
from ...constants import POCKETBASE_URL
from ...utils.prefs import get_prefs, get_addon_dir
from ...storage import Storage


# ---- helpers to guarantee isolated Blender Python for the worker ----

def _blender_python_args() -> list[str]:
    """
    Blender's recommended Python flags (if available).
    """
    try:
        args = getattr(bpy.app, "python_args", ())
        return list(args) if args else []
    except Exception:
        return []


_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_relative_ui_path(path: str) -> bool:
    value = str(path or "").strip()
    if not value:
        return True
    if value.startswith("//"):
        return True
    if value.startswith("\\\\"):
        return False
    if _WINDOWS_ABS_PATH_RE.match(value):
        return False
    return not os.path.isabs(value)


def _download_base_dir() -> str:
    blend_path = str(getattr(bpy.data, "filepath", "") or "").strip()
    if blend_path:
        blend_abs = bpy.path.abspath(blend_path)
        return os.path.abspath(str(Path(blend_abs).parent))
    return os.path.abspath(tempfile.gettempdir())


class SUPERLUMINAL_OT_DownloadJob(bpy.types.Operator):
    """Download the rendered frames from the selected job."""

    bl_idname = "superluminal.download_job"
    bl_label = "Download Job Frames"

    job_id: bpy.props.StringProperty(name="Job ID")
    job_name: bpy.props.StringProperty(name="Job Name")

    def execute(self, context):
        if not self.job_id:
            self.report({"ERROR"}, "No job selected")
            return {"CANCELLED"}

        scene = context.scene
        props = scene.superluminal_settings
        prefs = get_prefs()
        raw_download_path = str(props.download_path or "").strip()
        blend_saved = bool(str(getattr(bpy.data, "filepath", "") or "").strip())
        download_base_dir = _download_base_dir()

        if not blend_saved and _is_relative_ui_path(raw_download_path):
            self.report(
                {"WARNING"},
                (
                    "Blend file is unsaved. Relative download path will use the "
                    f"temporary folder: {download_base_dir}"
                ),
            )

        # Find the currently selected project
        selected_project = next(
            (p for p in Storage.data.get("projects", []) if p.get("id") == prefs.project_id),
            None,
        )
        if not selected_project:
            self.report({"ERROR"}, "Selected project is unavailable. Refresh projects and try again.")
            return {"CANCELLED"}

        handoff = {
            "addon_dir": str(get_addon_dir()),
            "download_path": raw_download_path,
            "download_base_dir": download_base_dir,
            "project": selected_project,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "pocketbase_url": POCKETBASE_URL,
            "sarfis_url": f"https://api.superlumin.al/farm/{Storage.data['org_id']}",
            "user_token": Storage.data["user_token"],
            "sarfis_token": Storage.data["user_key"],
        }

        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_download_{self.job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        worker = Path(__file__).with_name("download_worker.py")

        # Launch the worker with Blender's Python in isolated mode (-I)
        pybin = sys.executable
        pyargs = _blender_python_args()
        cmd = [pybin, *pyargs, "-I", "-u", str(worker), str(tmp_json)]

        try:
            launch_in_terminal(cmd)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start download: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Download started in external window.")
        return {"FINISHED"}


classes = (SUPERLUMINAL_OT_DownloadJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
