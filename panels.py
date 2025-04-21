import bpy

class SUPERLUMINAL_PT_RenderPanel(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_RenderPanel"
    bl_label = "Superluminal Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.superluminal_settings

        box = layout.box()
        row = box.row()
        row.label(text="Job Settings")

        row = box.row()
        row.prop(props, "use_upload_project", text="Upload Project")
        if props.use_upload_project:
            row.prop(props, "project_path", text="Project Path")

        row = box.row()
        row.prop(props, "use_scene_job_name", text="Use Scene Name")
        if not props.use_scene_job_name:
            row.prop(props, "job_name", text="")

        row = box.row()
        row.prop(props, "use_scene_render_format", text="Use Scene Format")
        if not props.use_scene_render_format:
            row.prop(props, "render_format", text="")

        row = box.row()
        row.prop(props, "render_type", text="Type")

        box2 = layout.box()
        row = box2.row()
        row.label(text="Frame Range")
        row = box2.row()
        row.prop(props, "use_scene_frame_range", text="Use Scene Range")
        if not props.use_scene_frame_range:
            row.prop(props, "frame_start", text="Start")
            row.prop(props, "frame_end", text="End")

        row = box2.row()
        row.prop(props, "use_scene_frame_step", text="Use Scene Step")
        if not props.use_scene_frame_step:
            row.prop(props, "frame_step", text="Step")

        row = layout.row()
        row.prop(props, "use_scene_batch_size", text="Use Scene/Default Batch")
        if not props.use_scene_batch_size:
            row.prop(props, "batch_size", text="Batch Size")

        row = layout.row()
        row.prop(props, "blender_version", text="Blender Version")

        layout.separator()

        row = layout.row()
        row.operator(
            "superluminal.submit_job", text="Submit Render Job", icon="RENDER_STILL"
        )


def register():
    bpy.utils.register_class(SUPERLUMINAL_PT_RenderPanel)


def unregister():
    bpy.utils.unregister_class(SUPERLUMINAL_PT_RenderPanel)
