from __future__ import annotations

import bpy
import addon_utils
import json
import sys
import tempfile
import uuid
from pathlib import Path
from ...utils.check_file_outputs import gather_render_outputs
from ...utils.worker_utils import launch_in_terminal
from .addon_packer import bundle_addons
from ...constants import POCKETBASE_URL
import os
from ...utils.version_utils import enum_from_bpy_version
from ...storage import Storage
from ...utils.prefs import get_prefs, get_addon_dir

def addon_version(addon_name: str):
    addon_utils.modules(refresh=False)
    for mod in addon_utils.addons_fake_modules.values():
        name = mod.bl_info.get("name", "")
        if name == addon_name:
            return tuple(mod.bl_info.get("version"))


class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submit the current .blend file and all of its dependencies to Superluminal"""

    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal (external)"

    def execute(self, context):  
        scene = context.scene
        props = scene.superluminal_settings
        prefs = get_prefs()
        addon_dir = get_addon_dir()
        print(addon_dir)
        if not bpy.data.filepath:
            self.report({"ERROR"}, "Please save your .blend file first.")
            return {"CANCELLED"}
        
        outputs = gather_render_outputs(scene)["outputs"]
        layers = outputs[0]["layers"]

        if props.auto_determine_blender_version:
            blender_version = enum_from_bpy_version()
        else:
            blender_version = props.blender_version

        # ---------------------------------------------
        # Frame range logic (handles IMAGE vs. ANIMATION)
        # ---------------------------------------------
        start_frame = (
            scene.frame_start if props.use_scene_frame_range else props.frame_start
        )
        end_frame = (
            scene.frame_end if props.use_scene_frame_range else props.frame_end
        )

        # If we are rendering a single image, ensure end_frame equals start_frame

        if props.render_type == "IMAGE":
            if props.use_scene_frame_range:
                start_frame = scene.frame_current
                end_frame = scene.frame_current
            else:
                start_frame = props.frame_start
                end_frame = props.frame_start

        job_id = uuid.uuid4()
        handoff = {
            "addon_dir": str(addon_dir),
            "addon_version": addon_version("Superluminal Render Farm"),
            "packed_addons_path": tempfile.mkdtemp(prefix="blender_addons_"),
            "packed_addons": [],
            "job_id": str(job_id),
            "blend_path": bpy.data.filepath,
            "temp_blend_path": str(Path(tempfile.gettempdir()) / bpy.path.basename(bpy.context.blend_data.filepath)),
            "use_project_upload": not bool(props.upload_project_as_zip),
            "automatic_project_path": bool(props.automatic_project_path),
            "custom_project_path": os.path.abspath(bpy.path.abspath(props.custom_project_path)).replace("\\", "/"),

            "job_name": (
                Path(bpy.data.filepath).stem
                if props.use_file_name
                else props.job_name
            ),
            "render_passes": layers,
            "image_format": (
                scene.render.image_settings.file_format
                if props.use_scene_image_format
                else props.image_format
            ),
            "use_scene_image_format": props.use_scene_image_format,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "frame_stepping_size": (
                scene.frame_step if props.use_scene_frame_range else props.frame_stepping_size
            ),
            "render_engine": scene.render.engine.upper(),
            "blender_version": blender_version.lower(),
            "ignore_errors": props.ignore_errors,
            "pocketbase_url": POCKETBASE_URL,
            "user_token": Storage.data["user_token"],
            "project": [p for p in Storage.data["projects"] if p["id"] == prefs.project_id][0],
            "use_bserver": props.use_bserver,
            "use_async_upload": props.use_async_upload,
        }

        bpy.ops.wm.save_as_mainfile(filepath=handoff["temp_blend_path"], compress=True, copy=True, relative_remap=False)

        worker = Path(__file__).with_name("submit_worker.py")

        handoff["packed_addons"] = bundle_addons(handoff["packed_addons_path"])
        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_{job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")


        try:
            launch_in_terminal([sys.executable, "-u", str(worker), str(tmp_json)])
        except Exception as e:
            self.report({"ERROR"}, f"Failed to launch submission: {e}")

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}



classes = (SUPERLUMINAL_OT_SubmitJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
