from __future__ import annotations

import bpy
import sys
from pathlib import Path

from ...utils.worker_utils import launch_worker_secure
from ...constants import POCKETBASE_URL
from ...utils.prefs import get_prefs, get_addon_dir
from ...storage import Storage


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

        # Find the currently selected project
        selected_project = next(
            (
                project
                for project in Storage.data.get("projects", [])
                if project.get("id") == prefs.project_id
            ),
            None,
        )
        if selected_project is None:
            self.report(
                {"ERROR"},
                "Selected project not found. Refresh projects and try again.",
            )
            return {"CANCELLED"}
        job_snapshot = dict(Storage.data.get("jobs", {}).get(self.job_id, {}) or {})
        if job_snapshot and not job_snapshot.get("id"):
            job_snapshot["id"] = self.job_id

        handoff = {
            "addon_dir": str(get_addon_dir()),
            "download_path": props.download_path,
            "project": selected_project,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "job": job_snapshot,
            "pocketbase_url": POCKETBASE_URL,
            "sarfis_url": f"https://api.superlumin.al/farm/{Storage.data['org_id']}",
            "user_token": Storage.data["user_token"],
            "sarfis_token": Storage.data["user_key"],
            "debug_mode": bool(getattr(prefs, "debug_mode", False)),
        }

        worker = Path(__file__).with_name("download_worker.py")

        try:
            launch_worker_secure(
                worker,
                handoff,
                f"superluminal_download_{self.job_id}.json",
                python_executable=sys.executable,
                python_args=getattr(bpy.app, "python_args", ()),
            )
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
