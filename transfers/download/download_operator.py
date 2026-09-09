from __future__ import annotations

import bpy
import sys
from pathlib import Path

from ...utils.worker_utils import launch_worker_secure
from ...environment import environment_handoff_values
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

        try:
            auth_context = Storage.auth_context()
            if not auth_context[2]:
                raise ValueError("Missing Sulu session")
            environment_values = environment_handoff_values(
                auth_context[0],
                selected_project.get("organization_id")
            )
        except ValueError:
            self.report(
                {"ERROR"},
                "Selected project metadata is incomplete. Refresh projects and try again.",
            )
            return {"CANCELLED"}

        handoff = {
            **environment_values,
            "addon_dir": str(get_addon_dir()),
            "download_path": bpy.path.abspath(props.download_path),
            "project": selected_project,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "job": job_snapshot,
            "user_token": auth_context[2],
            "render_coordinator": True,
            "download_type": "auto",
            "debug_mode": bool(getattr(prefs, "debug_mode", False)),
        }

        worker = Path(__file__).with_name("download_worker.py")

        if not Storage.auth_context_matches(
            auth_context[0], auth_context[1], auth_context[2]
        ):
            self.report(
                {"ERROR"},
                "Your Sulu session or environment changed. Download again.",
            )
            return {"CANCELLED"}
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
