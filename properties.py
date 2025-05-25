"""
Superluminal ‑ per‑scene settings kept inside the .blend file.

Every property now has a concise, user‑facing *description* so the
tooltip in Blender’s UI clearly explains what the option does.
"""

from __future__ import annotations
import bpy

from .preferences import get_job_items

# -------------------------------------------------------------------
#  Enum items
# -------------------------------------------------------------------
render_format_items = [
    ("PNG",      "PNG",      "Save each frame as a PNG image"),
    ("JPEG",     "JPEG",     "Save each frame as JPEG image"),
    ("OPEN_EXR", "OpenEXR",  "Save multilayer OpenEXR files."),
]

blender_version_items = [
    ("BLENDER40", "Blender 4.0", "Use Blender 4.0 on the farm"),
    ("BLENDER41", "Blender 4.1", "Use Blender 4.1 on the farm"),
    ("BLENDER42", "Blender 4.2", "Use Blender 4.2 on the farm"),
    ("BLENDER43", "Blender 4.3", "Use Blender 4.3 on the farm"),
    ("BLENDER44", "Blender 4.4", "Use Blender 4.4 on the farm"),
]

render_type_items = [
    ("IMAGE",     "Image",     "Render only a single frame"),
    ("ANIMATION", "Animation", "Render a sequence of frames"),
]

# -------------------------------------------------------------------
#  Scene Properties for Superluminal
# -------------------------------------------------------------------
class SuperluminalSceneProperties(bpy.types.PropertyGroup):
    # ────────────────────────────────────────────────────────────────
    #  Project packaging
    # ────────────────────────────────────────────────────────────────

    upload_project_as_zip: bpy.props.BoolProperty(
        name="Upload Project As Zip",
        default=True,
        description="Upload the entire project directory as a zip file.",
    )

    automatic_project_path: bpy.props.BoolProperty(
        name="Automatic Project Path",
        default=True,
        description="Automatically determine the project path based on all of the files in the project.",
    )
    custom_project_path: bpy.props.StringProperty(
        name="Custom Project Path",
        default="",
        description="Path to the project directory to upload. This is only used if Automatic Project Path is disabled.",
        subtype="DIR_PATH",
    )

    # ────────────────────────────────────────────────────────────────
    #  Job naming
    # ────────────────────────────────────────────────────────────────
    job_name: bpy.props.StringProperty(
        name="Job Name",
        default="My Render Job",
        description="Custom name shown in the Superluminal dashboard.",
    )
    use_file_name: bpy.props.BoolProperty(
        name="Use File Name",
        default=True,
        description="Ignore the custom job name and use the .blend filename.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Output format
    # ────────────────────────────────────────────────────────────────
    render_format: bpy.props.EnumProperty(
        name="Render Format",
        items=render_format_items,
        default="PNG",
        description="Image/sequence file format to use when overriding the "
                    "scene’s output settings.",
    )
    use_scene_render_format: bpy.props.BoolProperty(
        name="Use Scene Format",
        default=True,
        description="Keep whatever format is already set in the scene "
                    "and ignore the override above.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Render type
    # ────────────────────────────────────────────────────────────────
    render_type: bpy.props.EnumProperty(
        name="Render Type",
        items=render_type_items,
        default="ANIMATION",
        description="Choose whether to render the current frame only or "
                    "the whole frame range.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Frame range overrides
    # ────────────────────────────────────────────────────────────────
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
        description="Render the frame range already set in the Timeline "
                    "instead of the override above.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Farm Blender version
    # ────────────────────────────────────────────────────────────────
    blender_version: bpy.props.EnumProperty(
        name="Blender Version",
        items=blender_version_items,
        default="BLENDER44",
        description="Specify which Blender build the render farm should run. "
                    "Make sure your scene is compatible with the chosen version.",
    )

    auto_determine_blender_version: bpy.props.BoolProperty(
        name="Auto Determine Blender Version",
        default=True,
        description="Automatically determine the Blender version to use based on the scene.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Ignore errors
    # ────────────────────────────────────────────────────────────────
    ignore_errors: bpy.props.BoolProperty(
        name="Complete Job When Errored",
        default=False,
        description="Ignore errors and mark the job as completed.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Download stuff
    # ────────────────────────────────────────────────────────────────
    job_id: bpy.props.EnumProperty(
        name="Job",
        items=get_job_items,
        description="Select the job to render.",
    )

    download_path: bpy.props.StringProperty(
        name="Download Path",
        default="/tmp/",
        description="Path to download the rendered frames to.",
        subtype="DIR_PATH",
    )

    use_bserver: bpy.props.BoolProperty(
        name="Use B-Server",
        default=False,
        description="Use B-Server to render the job.",
    )

    use_async_upload: bpy.props.BoolProperty(
        name="Use Async Upload",
        default=False,
        description="Use async upload to render the job.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Show sections
    # ────────────────────────────────────────────────────────────────


    show_upload: bpy.props.BoolProperty(
        name="Show Upload Section",
        description="Expand/Collapse the upload section of the panel",
        default=True,
        options={'HIDDEN'},   # don’t clutter the sidebar with these flags
    )

    show_download: bpy.props.BoolProperty(
        name="Show Download Section",
        description="Expand/Collapse the download section of the panel",
        default=False,
        options={'HIDDEN'},
    )

    show_advanced: bpy.props.BoolProperty(
        name="Show Advanced Section",
        description="Expand/Collapse the advanced section of the panel",
        default=False,
        options={'HIDDEN'},
    )

    upload_settings: bpy.props.BoolProperty(
        name="Show Upload Settings",
        description="Expand/Collapse the upload settings section of the panel",
        default=False,
        options={'HIDDEN'},
    )

    show_addon_list: bpy.props.BoolProperty(
        name="Show Add-on List",
        description="Expand/Collapse the add-on list section of the panel",
        default=False,
        options={'HIDDEN'},
    )

    included_addons: bpy.props.StringProperty(
        name        = "Included Add-ons",
        description = "Semicolon-separated list of Python module names "
                      "that should be packed and uploaded with the job",
        default     = "",                 # e.g.  "mesh_tools;my_fancy_addon"
        options     = {'HIDDEN'},         # user never edits this directly
    )

# -------------------------------------------------------------------
#  Registration helpers
# -------------------------------------------------------------------
def register() -> None:
    bpy.utils.register_class(SuperluminalSceneProperties)
    bpy.types.Scene.superluminal_settings = bpy.props.PointerProperty(
        type=SuperluminalSceneProperties
    )

def unregister() -> None:
    del bpy.types.Scene.superluminal_settings
    bpy.utils.unregister_class(SuperluminalSceneProperties)
