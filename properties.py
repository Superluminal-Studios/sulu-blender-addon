"""
Superluminal ‑ per‑scene settings kept inside the .blend file.

Every property now has a concise, user‑facing *description* so the
tooltip in Blender’s UI clearly explains what the option does.
"""

from __future__ import annotations
import bpy

from .preferences import get_job_items
from .utils.version_utils import get_blender_version_string
# -------------------------------------------------------------------
#  Enum items
# -------------------------------------------------------------------
image_format_items = [
    ("PNG",      "PNG",      "Save each frame as a PNG image"),
    ("JPEG",     "JPEG",     "Save each frame as JPEG image"),
    ("EXR", "OpenEXR",  "Save multilayer OpenEXR files."),
    ("EXR_LOSSY", "OpenEXR Lossy", "Save lossy OpenEXR files."),
    ("EXR_MULTILAYER", "OpenEXR Multilayer", "Save multilayer OpenEXR files."),
    ("EXR_MULTILAYER_LOSSY", "OpenEXR Multilayer Lossy", "Save lossy multilayer OpenEXR files."),
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
        description=(
            "When enabled, this blend file together with all of its dependencies"
            " is uploaded as a single ZIP archive. When disabled, each file is "
            "uploaded to a project folder on the render farm, and subsequent "
            "uploads send only files that have changed. Disabling this option can eliminate most of the upload time."
        ),
    )

    automatic_project_path: bpy.props.BoolProperty(
        name="Automatic Project Path",
        default=True,
        description="When enabled, the root of your project is automatically determined based on the paths of the individual files this blend file has as dependencies. When disabled, you can manually specify the project root path below. (Only used if 'Upload Project As Zip' is disabled.)",
    )
    custom_project_path: bpy.props.StringProperty(
        name="Custom Project Path",
        default="",
        description="Specify the root of your project manually. (Only used if 'Upload Project As Zip' is disabled and 'Automatic Project Path' is disabled.)",
        subtype="DIR_PATH",
    )

    # ────────────────────────────────────────────────────────────────
    #  Job naming
    # ────────────────────────────────────────────────────────────────
    job_name: bpy.props.StringProperty(
        name="Job Name",
        default="My Render Job",
        description="Custom render job name.",
    )
    use_file_name: bpy.props.BoolProperty(
        name="Use File Name",
        default=True,
        description='Use the current .blend file name as the render job name instead of the custom name below.',
    )

    # ────────────────────────────────────────────────────────────────
    #  Output format
    # ────────────────────────────────────────────────────────────────
    image_format: bpy.props.EnumProperty(
        name="Image Format",
        items=image_format_items,
        default="PNG",
        description='Preset image formats to use when rendering if "Use Scene Image Format" is disabled. (Uses reasonable defaults for each format, enable "Use Scene Image Format" for more fine-grained control.)',
    )
    use_scene_image_format: bpy.props.BoolProperty(
        name="Use Scene Format",
        default=True,
        description="Use the image format settings selected in Blender's render output settings instead of the preset image formats below.",
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
        description="Use the scene's start/end frame range instead of the values below.",
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
        description=f"Determine the Blender version to use on the farm based on the one you're currently using. Right now you're using Blender {get_blender_version_string()}.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Ignore errors
    # ────────────────────────────────────────────────────────────────
    ignore_errors: bpy.props.BoolProperty(
        name="Finish Frame When Errored",
        default=False,
        description="Consider a frame finished even if the render process errors on the farm. This can be useful if you find that blender often crashes after the output file has already been written.",
    )

    # ────────────────────────────────────────────────────────────────
    #  Download stuff
    # ────────────────────────────────────────────────────────────────

    download_path: bpy.props.StringProperty(
        name="Download Path",
        default="/tmp/",
        description="Path to download the rendered frames to.",
        subtype="DIR_PATH",
    )

    use_bserver: bpy.props.BoolProperty(
        name="Persistence Engine",
        default=False,
        description="The Persistence Engine keeps Blender running between frames. This ensures memory is kept around, which can significantly speed up your renders, especially if you have persistent data enabled.",
    )

    use_async_upload: bpy.props.BoolProperty(
        name="Async Frame Upload",
        default=False,
        description="Upload frames asynchronously to the farm. Frames are uploaded while the next frame is already rendering. This makes the cost needed to upload the render results to the server essentially free if the render is slower than the upload, which is the case for most renders.",
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