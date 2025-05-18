from __future__ import annotations


import json
import sys
import tempfile
import uuid
from pathlib import Path
from .check_file_outputs import gather_render_outputs
from .worker_utils import launch_in_terminal
from .addon_packer import bundle_addons
from .properties import blender_version_items
import bpy  
from .constants import POCKETBASE_URL
# Build a lookup:  40 → "BLENDER40", 41 → "BLENDER41", …
_enum_by_number = {
    int(code.replace("BLENDER", "")): code
    for code, *_ in blender_version_items
}
_enum_numbers_sorted = sorted(_enum_by_number)     # e.g. [40, 41, 42, 43, 44]

def enum_from_bpy_version(bpy_version: tuple[int, int, int]) -> str:
    """
    Return the enum key that best matches the running Blender version.

    • If the build is *newer* than anything in the list → return the
      **highest** enum we have.
    • If it’s *older* than anything in the list → return the **lowest**.
    • Otherwise pick the exact match or, if the minor revision isn’t
      represented, the nearest lower entry (4.2.3 maps to 4.2).
    """
    major, minor, _ = bpy_version
    numeric = major * 10 + minor     # 4.3 → 43

    # Clamp to list boundaries
    if numeric <= _enum_numbers_sorted[0]:
        return _enum_by_number[_enum_numbers_sorted[0]]
    if numeric >= _enum_numbers_sorted[-1]:
        return _enum_by_number[_enum_numbers_sorted[-1]]

    # Inside the known range – find the closest lower-or-equal entry
    for n in reversed(_enum_numbers_sorted):
        if n <= numeric:
            return _enum_by_number[n]

    # Fallback (shouldn’t be reached)
    return blender_version_items[0][0]

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

        if props.auto_determine_blender_version:
            blender_version = enum_from_bpy_version(bpy.app.version)
        else:
            blender_version = props.blender_version

        job_id = uuid.uuid4()
        handoff = {
            "addon_dir": str(Path(__file__).resolve().parent),
            "packed_addons_path": tempfile.mkdtemp(prefix="blender_addons_"),
            "packed_addons": [],
            "job_id": str(job_id),
            "blend_path": bpy.data.filepath,
            "temp_blend_path": str(Path(tempfile.gettempdir()) / bpy.path.basename(bpy.context.blend_data.filepath)),
            "use_project_upload": not bool(props.upload_project_as_zip),
            "automatic_project_path": bool(props.automatic_project_path),
            "custom_project_path": props.custom_project_path,
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
            "blender_version": blender_version,
            "ignore_errors": props.ignore_errors,
            "pocketbase_url": POCKETBASE_URL,
            "user_token": prefs.user_token,
            "selected_project_id": prefs.project_list,
            "use_bserver": props.use_bserver,
        }
        
        bpy.ops.wm.save_as_mainfile(filepath=handoff["temp_blend_path"], compress=True, copy=True, relative_remap=False)

        worker = Path(__file__).with_name("submit_worker.py")

        # try:
        handoff["packed_addons"] = bundle_addons(handoff["packed_addons_path"])
        # except Exception as e:
            # self.report({"ERROR"}, f"Failed to pack addons: {e}")


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
