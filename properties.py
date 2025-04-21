import bpy

# -------------------------------------------------------------------
#  Enums for UI
# -------------------------------------------------------------------
render_format_items = [
    ("PNG", "PNG", "PNG format"),
    ("JPEG", "JPEG", "JPEG format"),
    ("OPEN_EXR", "OpenEXR", "OpenEXR format"),
]

blender_version_items = [
    ("BLENDER42", "Blender 4.2", ""),
    ("BLENDER35", "Blender 3.5", ""),
    ("BLENDER34", "Blender 3.4", ""),
]

render_type_items = [
    ("IMAGE", "Image", "Still image render"),
    ("ANIMATION", "Animation", "Animated frames"),
]


# -------------------------------------------------------------------
#  Scene Properties for Superluminal
# -------------------------------------------------------------------
class SuperluminalSceneProperties(bpy.types.PropertyGroup):
    project_path: bpy.props.StringProperty(name="Project Path", default="", subtype="FILE_PATH")
    use_upload_project: bpy.props.BoolProperty(name="Upload Project", default=False)

    job_name: bpy.props.StringProperty(name="Job Name", default="My Render Job")
    use_scene_job_name: bpy.props.BoolProperty(name="Use Scene Name", default=False)

    render_format: bpy.props.EnumProperty(
        name="Render Format",
        items=render_format_items,
        default="PNG",
    )
    use_scene_render_format: bpy.props.BoolProperty(
        name="Use Scene Format", default=False
    )

    render_type: bpy.props.EnumProperty(
        name="Render Type", items=render_type_items, default="IMAGE"
    )

    frame_start: bpy.props.IntProperty(name="Start Frame", default=1)
    frame_end: bpy.props.IntProperty(name="End Frame", default=250)
    use_scene_frame_range: bpy.props.BoolProperty(
        name="Use Scene Frame Range", default=False
    )

    frame_step: bpy.props.IntProperty(name="Frame Step", default=1)
    use_scene_frame_step: bpy.props.BoolProperty(
        name="Use Scene Frame Step", default=False
    )

    batch_size: bpy.props.IntProperty(name="Batch Size", default=1, min=1)
    use_scene_batch_size: bpy.props.BoolProperty(
        name="Use Default/Scene Logic", default=False
    )

    blender_version: bpy.props.EnumProperty(
        name="Blender Version",
        items=blender_version_items,
        default="BLENDER42",
    )


def register():
    bpy.utils.register_class(SuperluminalSceneProperties)
    bpy.types.Scene.superluminal_settings = bpy.props.PointerProperty(
        type=SuperluminalSceneProperties
    )


def unregister():
    del bpy.types.Scene.superluminal_settings
    bpy.utils.unregister_class(SuperluminalSceneProperties)
