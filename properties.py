# properties.py
"""
Superluminal – per-scene settings kept inside the .blend file.

This version removes fake foldout flags (show_* / upload_settings / show_addon_list).
Use real Blender sub-panels (via bl_parent_id) to get persistent, non-dirty
open/closed UI state.

Property groups here remain focused on actual render settings that *should*
live in the .blend (e.g., output format, frame range, included add-ons, etc.).
"""

from __future__ import annotations
import bpy

from .utils.prefs import get_prefs
from .utils.version_utils import get_blender_version_string
from .utils.request_utils import fetch_jobs
from .storage import Storage


# ────────────────────────────────────────────────────────────────
#  Enum items (dynamic for image format to reflect current scene)
# ────────────────────────────────────────────────────────────────
def image_format_items_cb(self, context):
    current = "Unknown"
    try:
        if context and context.scene:
            current = context.scene.render.image_settings.file_format
    except Exception:
        pass

    # (identifier, name, description)
    return [
        ("SCENE", f"Scene Image Format [{current}]", "Use Blender's current Output > File Format."),
        ("PNG",   "PNG",                      "Save each frame as a PNG image."),
        ("JPEG",  "JPEG",                     "Save each frame as JPEG image."),
        ("EXR",   "OpenEXR",                  "Save OpenEXR files."),
        ("EXR_LOSSY", "OpenEXR Lossy",        "Save lossy OpenEXR files."),
        ("EXR_MULTILAYER", "OpenEXR Multilayer", "Save multilayer OpenEXR files."),
        ("EXR_MULTILAYER_LOSSY", "OpenEXR Multilayer Lossy", "Save lossy multilayer OpenEXR files."),
    ]


blender_version_items = [
    ("BLENDER40", "Blender 4.0", "Use Blender 4.0 on the farm"),
    ("BLENDER41", "Blender 4.1", "Use Blender 4.1 on the farm"),
    ("BLENDER42", "Blender 4.2", "Use Blender 4.2 on the farm"),
    ("BLENDER43", "Blender 4.3", "Use Blender 4.3 on the farm"),
    ("BLENDER44", "Blender 4.4", "Use Blender 4.4 on the farm"),
    ("BLENDER45", "Blender 4.5", "Use Blender 4.5 on the farm"),
]

render_type_items = [
    ("IMAGE",     "Image",     "Render only a single frame"),
    ("ANIMATION", "Animation", "Render a sequence of frames"),
]


# ────────────────────────────────────────────────────────────────
#  Live-job-update callback (used by SuluWMSceneProperties)
# ────────────────────────────────────────────────────────────────
def live_job_update(self, context):
    prefs = get_prefs()
    if self.live_job_updates:
        fetch_jobs(
            Storage.data["org_id"],
            Storage.data["user_key"],
            prefs.project_id,
            True
        )
    else:
        Storage.enable_job_thread = False


# ────────────────────────────────────────────────────────────────
#  1. Main Superluminal scene properties
# ────────────────────────────────────────────────────────────────
class SuperluminalSceneProperties(bpy.types.PropertyGroup):
    # ------------------------------------------------------------
    #  Project packaging
    # ------------------------------------------------------------
    upload_type: bpy.props.EnumProperty(
        name="Upload Type",
        items=[
            ("ZIP",     "Zip",     "Upload this .blend and its dependencies as a single ZIP archive."),
            ("PROJECT", "Project", "Upload files to a project folder; subsequent uploads send only files that changed."),
        ],
        default="ZIP",
        description=(
            "Choose how to package and upload your scene:\n"
            "• Zip — upload this .blend and its dependencies as a single ZIP archive.\n"
            "• Project — upload files into a project folder; subsequent uploads only send changed files."
        ),
    )
    automatic_project_path: bpy.props.BoolProperty(
        name="Automatic Project Path",
        default=True,
        description=(
            "When enabled, the root of your project is automatically determined "
            "based on the paths of the individual files this blend file has as "
            "dependencies. (Only used if Upload Type is 'Project'.)"
        ),
    )
    custom_project_path: bpy.props.StringProperty(
        name="Custom Project Path",
        default="",
        description=(
            "Specify the root of your project manually. "
            "(Only used if Upload Type is 'Project' and Automatic Project Path is disabled.)"
        ),
        subtype="DIR_PATH",
    )

    # ------------------------------------------------------------
    #  Job naming
    # ------------------------------------------------------------
    job_name: bpy.props.StringProperty(
        name="Job Name",
        default="My Render Job",
        description="Custom render job name.",
    )
    use_file_name: bpy.props.BoolProperty(
        name="Use File Name",
        default=True,
        description=(
            "Use the current .blend file name as the render job name instead of "
            "the custom name below."
        ),
    )

    # ------------------------------------------------------------
    #  Output format (enum includes a 'Scene Image Format' option)
    #  NOTE: because items=callback, default MUST be an integer index.
    #        0 -> "SCENE" entry above.
    # ------------------------------------------------------------
    image_format: bpy.props.EnumProperty(
        name="Image Format",
        items=image_format_items_cb,
        default=0,  # <- important for dynamic enums
        description=(
            "Choose an image format preset or pick 'Scene Image Format' to use "
            "the current Output > File Format from your Blender scene."
        ),
    )

    # ------------------------------------------------------------
    #  Render type
    # ------------------------------------------------------------
    render_type: bpy.props.EnumProperty(
        name="Render Type",
        items=render_type_items,
        default="ANIMATION",
        description="Choose whether to render the current frame only or the whole frame range.",
    )

    # ------------------------------------------------------------
    #  Frame range overrides
    # ------------------------------------------------------------
    frame_start: bpy.props.IntProperty(
        name="Start Frame",
        default=1,
        description="First frame to render when overriding the scene range.",
    )
    frame_end: bpy.props.IntProperty(
        name="End Frame",
        default=250,
        description="Last frame to render when overriding the scene range.",
    )
    frame_stepping_size: bpy.props.IntProperty(
        name="Stepping",
        default=1,
        description="Stepping size for the frame range.",
    )
    use_scene_frame_range: bpy.props.BoolProperty(
        name="Use Scene Frame Range",
        default=True,
        description="Use the scene's start/end frame range instead of the values below.",
    )

    # ------------------------------------------------------------
    #  Farm Blender version
    # ------------------------------------------------------------
    blender_version: bpy.props.EnumProperty(
        name="Blender Version",
        items=blender_version_items,
        default="BLENDER44",
        description=(
            "Specify which Blender build the render farm should run. "
            "Make sure your scene is compatible with the chosen version."
        ),
    )
    auto_determine_blender_version: bpy.props.BoolProperty(
        name="Auto Determine Blender Version",
        default=True,
        description=(
            "Determine the Blender version to use on the farm based on the one "
            f"you're currently using. Right now you're using "
            f"Blender {get_blender_version_string()}."
        ),
    )

    # ------------------------------------------------------------
    #  Ignore errors
    # ------------------------------------------------------------
    ignore_errors: bpy.props.BoolProperty(
        name="Finish Frame When Errored",
        default=False,
        description=(
            "Consider a frame finished even if the render process errors on the "
            "farm. This can be useful if you find that Blender often crashes after "
            "the output file has already been written."
        ),
    )

    # ------------------------------------------------------------
    #  Download / persistence options
    # ------------------------------------------------------------
    download_path: bpy.props.StringProperty(
        name="Download Path",
        default="/tmp/",
        description="Path to download the rendered frames to.",
        subtype="DIR_PATH",
    )
    use_bserver: bpy.props.BoolProperty(
        name="Persistence Engine",
        default=False,
        description=(
            "The Persistence Engine keeps Blender running between frames. "
            "This ensures memory is kept around, which can significantly speed "
            "up your renders, especially if you have persistent data enabled."
        ),
    )
    use_async_upload: bpy.props.BoolProperty(
        name="Async Frame Upload",
        default=False,
        description=(
            "Upload frames asynchronously to the farm. Frames are uploaded while "
            "the next frame is already rendering. This makes the cost needed to "
            "upload the render results to the server essentially free if the "
            "render is slower than the upload, which is the case for most renders."
        ),
    )

    included_addons: bpy.props.StringProperty(
        name="Included Add-ons",
        description=(
            "Semicolon-separated list of Python module names that should be "
            "packed and uploaded with the job"
        ),
        default="",
        options={'HIDDEN'},  # user never edits this directly; UI lives in a sub-panel
    )


# ────────────────────────────────────────────────────────────────
#  2. Sulu WM scene properties (live things)
# ────────────────────────────────────────────────────────────────
class SuluWMSceneProperties(bpy.types.PropertyGroup):
    live_job_updates: bpy.props.BoolProperty(
        name="Live Job Updates",
        default=False,
        description="Update the job list in real time.",
        update=live_job_update,
    )


# ────────────────────────────────────────────────────────────────
#  Registration helpers
# ────────────────────────────────────────────────────────────────
_classes = (
    SuperluminalSceneProperties,
    SuluWMSceneProperties,
)


def register() -> None:  # pylint: disable=missing-function-docstring
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.superluminal_settings = bpy.props.PointerProperty(
        type=SuperluminalSceneProperties
    )
    bpy.types.Scene.sulu_wm_settings = bpy.props.PointerProperty(
        type=SuluWMSceneProperties
    )


def unregister() -> None:  # pylint: disable=missing-function-docstring
    del bpy.types.Scene.sulu_wm_settings
    del bpy.types.Scene.superluminal_settings

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
