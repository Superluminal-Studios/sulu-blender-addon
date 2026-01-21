# operators/submit_job_operator.py
from __future__ import annotations

import bpy
import addon_utils
import json
import sys
import tempfile
import uuid
from pathlib import Path
from bpy.props import EnumProperty, IntProperty, BoolProperty
import os

# from ...utils.check_file_outputs import gather_render_outputs
from ...utils.worker_utils import launch_in_terminal
from .addon_packer import bundle_addons
from ...constants import POCKETBASE_URL, FARM_IP
from ...utils.version_utils import resolved_worker_blender_value
from ...storage import Storage
from ...utils.prefs import get_prefs, get_addon_dir
from ...utils.project_scan import quick_cross_drive_hint


def _blender_python_args() -> list[str]:
    """
    Blender's recommended Python flags (if available).
    """
    try:
        args = getattr(bpy.app, "python_args", ())
        return list(args) if args else []
    except Exception:
        return []


def addon_version(addon_name: str):
    addon_utils.modules(refresh=False)
    for mod in addon_utils.addons_fake_modules.values():
        name = mod.bl_info.get("name", "")
        if name == addon_name:
            return tuple(mod.bl_info.get("version"))


class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submit the current .blend file and all of its dependencies to Superluminal"""

    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal"

    # New: submission mode and still-frame popup controls
    mode: EnumProperty(
        name="Submission Mode",
        items=[
            ("STILL", "Still", "Render a single frame"),
            ("ANIMATION", "Animation", "Render a frame range"),
        ],
        default="ANIMATION",
    )
    use_current_scene_frame: BoolProperty(
        name="Use Current Scene Frame",
        description="If enabled, render the scene's current frame",
        default=True,
    )
    frame: IntProperty(
        name="Frame",
        description="Frame to render for a still submission",
        default=0,  # will be set from scene on invoke
        soft_min=-999999,
        soft_max=999999,
    )

    def invoke(self, context, event):
        # For still submissions, show a small dialog to pick the frame.
        if self.mode == "STILL":
            self.frame = context.scene.frame_current
            self.use_current_scene_frame = True
            return context.window_manager.invoke_props_dialog(self)
        # For animations, run immediately.
        return self.execute(context)

    def draw(self, context):
        # Only used for STILL popup
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "use_current_scene_frame", text="Use Current Scene Frame")

        sub = layout.column()
        if self.use_current_scene_frame:
            # Show the actual Scene frame in a disabled field
            sub.enabled = False
            sub.prop(context.scene, "frame_current", text="Frame")
        else:
            sub.prop(self, "frame", text="Frame")

    def execute(self, context):
        scene = context.scene
        props = scene.superluminal_settings
        prefs = get_prefs()
        addon_dir = get_addon_dir()

        if not bpy.data.filepath:
            self.report({"ERROR"}, "Please save your .blend file first.")
            return {"CANCELLED"}

        # Ensure we have a logged-in session with a project
        token = Storage.data.get("user_token")
        if not token:
            self.report({"ERROR"}, "You are not logged in.")
            return {"CANCELLED"}

        # Resolve project from Storage + prefs
        project = next(
            (
                p
                for p in Storage.data.get("projects", [])
                if p.get("id") == getattr(prefs, "project_id", None)
            ),
            None,
        )
        if not project:
            self.report(
                {"ERROR"},
                "No project selected or projects not loaded. Please log in and select a project.",
            )
            return {"CANCELLED"}

        # Gather outputs safely
        # outputs = gather_render_outputs(scene).get("outputs", [])
        # if not outputs:
        #     self.report({"ERROR"}, "No render outputs detected for this scene.")
        #     return {"CANCELLED"}
        # layers = outputs[0].get("layers", [])

        # Non-blocking heads-up if Project upload will ignore off-drive deps
        if props.upload_type == "PROJECT":
            try:
                has_cross, summary = quick_cross_drive_hint()
                if has_cross:
                    self.report(
                        {"WARNING"},
                        f"{summary.cross_drive_count()} dependencies are on a different drive and will be ignored in Project uploads. Consider switching to Zip.",
                    )
            except Exception:
                pass

        # Blender version (single source of truth)
        blender_version_payload = resolved_worker_blender_value(
            props.auto_determine_blender_version, props.blender_version
        )

        # Frame computation (mode-aware)
        if self.mode == "STILL":
            if self.use_current_scene_frame or self.frame == 0:
                start_frame = end_frame = scene.frame_current
            else:
                start_frame = end_frame = int(self.frame)
            frame_stepping_size = 1
        else:  # ANIMATION
            start_frame = (
                scene.frame_start if props.use_scene_frame_range else props.frame_start
            )
            end_frame = (
                scene.frame_end if props.use_scene_frame_range else props.frame_end
            )
            frame_stepping_size = (
                scene.frame_step
                if props.use_scene_frame_range
                else props.frame_stepping_size
            )

        # Image format selection (enum includes SCENE option)
        use_scene_image_format = props.image_format == "SCENE"
        image_format_val = (
            scene.render.image_settings.file_format
            if use_scene_image_format
            else props.image_format
        )

        job_id = uuid.uuid4()
        blend_path_anchor = Path(bpy.data.filepath).anchor
        handoff = {
            "addon_dir": str(addon_dir),
            "addon_version": addon_version("Superluminal Render Farm"),
            "packed_addons_path": tempfile.mkdtemp(prefix="blender_addons_"),
            "packed_addons": [],
            "job_id": str(job_id),
            "device_type": props.device_type,
            "blend_path": bpy.path.abspath(bpy.data.filepath).replace("\\", "/"),
            "temp_blend_path": str(
                Path(tempfile.gettempdir())
                / bpy.path.basename(bpy.context.blend_data.filepath)
            ),
            # project upload controls
            "use_project_upload": (props.upload_type == "PROJECT"),
            "automatic_project_path": bool(props.automatic_project_path),
            "custom_project_path": os.path.abspath(
                bpy.path.abspath(props.custom_project_path)
            ).replace("\\", "/"),
            "job_name": (
                Path(bpy.data.filepath).stem if props.use_file_name else props.job_name
            ),
            # "render_passes": layers,
            "image_format": image_format_val,
            # keep for backward compatibility with worker / API
            "use_scene_image_format": use_scene_image_format,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "frame_stepping_size": frame_stepping_size,
            "render_engine": scene.render.engine.upper(),
            "blender_version": blender_version_payload,  # <- single source of truth
            "ignore_errors": props.ignore_errors,
            "pocketbase_url": POCKETBASE_URL,
            "user_token": token,
            "project": project,
            "use_bserver": props.use_bserver,
            "use_async_upload": props.use_async_upload,
            "farm_url": f"{FARM_IP}/farm/{Storage.data.get('org_id', '')}/api/",
        }

        # bpy.ops.wm.save_as_mainfile(
        #     filepath=handoff["temp_blend_path"],
        #     compress=True,
        #     copy=True,
        #     relative_remap=False,
        # )

        worker = Path(__file__).with_name("submit_worker.py")

        handoff["packed_addons"] = bundle_addons(handoff["packed_addons_path"])
        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_{job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        # --- launch the worker with Blender's Python, in isolated mode ---
        # -I makes Python ignore PYTHON* env vars & user-site, preventing stdlib leakage.
        pybin = sys.executable
        pyargs = _blender_python_args()
        cmd = [pybin, *pyargs, "-I", "-u", str(worker), str(tmp_json)]

        try:
            launch_in_terminal(cmd)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to launch submission: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}


classes = (SUPERLUMINAL_OT_SubmitJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
