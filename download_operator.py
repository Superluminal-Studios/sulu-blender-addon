from __future__ import annotations


import json
import sys
import tempfile
from pathlib import Path
import bpy  
from .worker_utils import launch_in_terminal

class SUPERLUMINAL_OT_DownloadJob(bpy.types.Operator):
    """Download frames from the selected job
       by spawning an external worker process.
    """

    bl_idname = "superluminal.download_job"
    bl_label = "Download Job Frames"

    def execute(self, context):  
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__package__].preferences
        job_id = None
        
        handoff = {
            "download_path": "/tmp/download_test/",
            "selected_project_id": prefs.project_list,
            "job_id": None,
            "pocketbase_url": prefs.pocketbase_url,
            "user_token": prefs.user_token,
        }

        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_download_{job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        worker = Path(__file__).with_name("download_worker.py")
        launch_in_terminal([sys.executable, "-u", str(worker), str(tmp_json)])

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}



classes = (SUPERLUMINAL_OT_DownloadJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
