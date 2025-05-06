from __future__ import annotations


import json
import sys
import tempfile
import uuid
from pathlib import Path
from .check_file_outputs import gather_render_outputs
from .worker_utils import launch_in_terminal
import bpy  


class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submit the current .blend file to the Superluminal Render Farm
       by spawning an external worker process.
    """

    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal (external)"

    def execute(self, context):  
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__package__].preferences

        if not bpy.data.filepath:
            self.report({"ERROR"}, "Please save your .blend file first.")
            return {"CANCELLED"}
        
        outputs = gather_render_outputs(scene)["outputs"]
        layers = outputs[0]["layers"]
        print(layers)
        

        
        job_id = uuid.uuid4()
        handoff = {
            "addon_dir": str(Path(__file__).resolve().parent),
            "job_id": str(job_id),
            "blend_path": bpy.data.filepath,
            "temp_blend_path": str(Path(tempfile.gettempdir()) / bpy.path.basename(bpy.context.blend_data.filepath)),
            "use_project_upload": bool(props.use_upload_project),
            "job_name": (
                Path(bpy.data.filepath).stem
                if props.use_file_name
                else props.job_name
            ),
            "render_passes": layers,
            "render_format": (
                scene.render.image_settings.file_format
                if props.use_scene_render_format
                else props.render_format
            ),
            "start_frame": (
                scene.frame_start if props.use_scene_frame_range else props.frame_start
            ),
            "end_frame": (
                scene.frame_end if props.use_scene_frame_range else props.frame_end
            ),
            "render_engine": scene.render.engine.upper(),
            "blender_version": props.blender_version,
            "ignore_errors": props.ignore_errors,
            "pocketbase_url": prefs.pocketbase_url,
            "user_token": prefs.user_token,
            "selected_project_id": prefs.project_list,
        }
        bpy.ops.wm.save_as_mainfile(filepath=handoff["temp_blend_path"], compress=True, copy=True, relative_remap=False)
        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_{job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        worker = Path(__file__).with_name("submit_worker.py")
        launch_in_terminal([sys.executable, "-u", str(worker), str(tmp_json)])

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}



classes = (SUPERLUMINAL_OT_SubmitJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
