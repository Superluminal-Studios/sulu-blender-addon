# properties.py (scene & WM properties)
from __future__ import annotations
import bpy

from .utils.prefs import get_prefs
from .utils.version_utils import (
    get_blender_version_string,
    blender_version_items,
    enum_from_bpy_version,
)
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
            "When on, the project root is determined automatically from your "
            "blend file's dependencies. Only used with Project upload type."
        ),
    )
    custom_project_path: bpy.props.StringProperty(
        name="Custom Project Path",
        default="",
        description=(
            "Specify the project root manually. "
            "Only used with Project upload type when automatic path is off."
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
            "a custom name."
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
        description="Use the scene's start and end frame range instead of custom values.",
    )

    # ------------------------------------------------------------
    #  Farm Blender version (single source of truth via utils.version_utils)
    # ------------------------------------------------------------
    blender_version: bpy.props.EnumProperty(
        name="Blender Version",
        items=blender_version_items,
        default=enum_from_bpy_version(),  # dynamic default that matches the running Blender
        description=(
            "Specify which Blender build the render farm should run. "
            "Make sure your scene is compatible with the chosen version."
        ),
    )
    auto_determine_blender_version: bpy.props.BoolProperty(
        name="Auto Determine Blender Version",
        default=True,
        description=(
            "Match the farm's Blender version to yours. "
            f"You're currently using Blender {get_blender_version_string()}."
        ),
    )

    # device_type: bpy.props.EnumProperty(
    #     name="Device Type",
    #     items=[
    #         ("GPU", "GPU", "Use GPU for rendering"),
    #         ("CPU", "CPU", "Use CPU for rendering"),
    #     ],
    #     default="GPU",
    #     description=(
    #         "Specify which device type the render farm should use. "
    #     ),
    # )

    device_type: bpy.props.EnumProperty(
        name="Device Type",
        items=[
            ("1x-RTX4090-8CPU-32RAM", "RTX 4090, 8 Cores, 32GB RAM", "RTX 4090, 8 Cores, 32GB RAM"),
            ("0x-None-16CPU-32RAM", "16 Cores, 32GB RAM", "16 Cores, 32GB RAM"),
            ("0x-None-16CPU-64RAM", "16 Cores, 64GB RAM", "16 Cores, 64GB RAM"),
            ("0x-None-16CPU-128RAM", "16 Cores, 128GB RAM", "16 Cores, 128GB RAM"),
        ],
        default="1x-RTX4090-8CPU-32RAM",
        description=(
            "Specify which device the render farm should use. "
        ),
    )



    # ------------------------------------------------------------
    #  Ignore errors
    # ------------------------------------------------------------
    ignore_errors: bpy.props.BoolProperty(
        name="Finish Frame On Error",
        default=False,
        description=(
            "Mark a frame as finished even if the render process stops unexpectedly. "
            "Useful when Blender quits after the output file is already saved."
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
        default=True,
        description=(
            "The Persistence Engine keeps Blender running between frames. "
            "This ensures memory is kept around, which can significantly speed "
            "up your renders, especially if you have persistent data enabled."
        ),
    )
    use_async_upload: bpy.props.BoolProperty(
        name="Async Frame Upload",
        default=True,
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
#  3. WindowManager-scoped (runtime-only) auth props
#      — not saved in .blend or user preferences
# ────────────────────────────────────────────────────────────────
class SuluWMProperties(bpy.types.PropertyGroup):
    username: bpy.props.StringProperty(
        name="Email",
        description="Your Superluminal account email/username"
    )
    password: bpy.props.StringProperty(
        name="Password",
        subtype="PASSWORD",
        description="Your Superluminal password (not persisted)"
    )


# ────────────────────────────────────────────────────────────────
#  Registration helpers
# ────────────────────────────────────────────────────────────────
_classes = (
    SuperluminalSceneProperties,
    SuluWMSceneProperties,
    SuluWMProperties,
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
    # Runtime-only credentials holder (non-persistent)
    bpy.types.WindowManager.sulu_wm = bpy.props.PointerProperty(
        type=SuluWMProperties
    )


def unregister() -> None:  # pylint: disable=missing-function-docstring
    # Remove pointers first
    if hasattr(bpy.types.WindowManager, "sulu_wm"):
        del bpy.types.WindowManager.sulu_wm
    if hasattr(bpy.types.Scene, "sulu_wm_settings"):
        del bpy.types.Scene.sulu_wm_settings
    if hasattr(bpy.types.Scene, "superluminal_settings"):
        del bpy.types.Scene.superluminal_settings

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
