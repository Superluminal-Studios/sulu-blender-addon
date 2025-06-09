from __future__ import annotations


import bpy
import json
import sys
import tempfile
from pathlib import Path
from ...utils.worker_utils import launch_in_terminal
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
        if self.job_id == "":
            self.report({"ERROR"}, "No job selected")
            return {"CANCELLED"}
        
        scene = context.scene
        props = scene.superluminal_settings
        prefs = get_prefs()

        selected_project =  [p for p in Storage.data["projects"] if p["id"] == prefs.project_id][0]

        handoff = {
            "addon_dir": str(get_addon_dir()),
            "download_path": props.download_path,
            "project": selected_project,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "pocketbase_url": POCKETBASE_URL,
            "user_token": Storage.data["user_token"],
        }

        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_download_{self.job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        worker = Path(__file__).with_name("download_worker.py")
        launch_in_terminal([sys.executable, "-u", str(worker), str(tmp_json)])
        # subprocess.run([sys.executable, "-u", str(worker), str(tmp_json)])

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}



classes = (SUPERLUMINAL_OT_DownloadJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
