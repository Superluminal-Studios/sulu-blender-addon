import bpy

class SUPERLUMINAL_PT_RenderPanel(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_RenderPanel"
    bl_label = "Superluminal Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    # ------------------------------------------------------------------
    #  UI helpers
    # ------------------------------------------------------------------
    @staticmethod
    def draw_toggle_row(col, toggle_prop, content_prop, *,
                        toggle_text="", content_text="",
                        invert=False):
        """
        Adds a checkbox row, followed by a row that shows the related
        property but is disabled while the toggle is (un)checked.
        """
        row = col.row(align=True)
        row.prop(toggle_prop[0], toggle_prop[1], text=toggle_text)

        row = col.row(align=True)
        row.prop(content_prop[0], content_prop[1], text=content_text)
        row.enabled = (toggle_prop[0].path_resolve(toggle_prop[1]) ^ invert)

    # ------------------------------------------------------------------
    #  Draw
    # ------------------------------------------------------------------
    def draw(self, context):
        layout = self.layout
        scene   = context.scene
        props   = scene.superluminal_settings
        prefs   = context.preferences.addons[__package__].preferences

        # --------------------------------------------------------------
        #  Project selector + refresh button
        # --------------------------------------------------------------
        row = layout.row(align=True)
        row.prop(prefs, "project_list", text="Project")
        row.operator("superluminal.fetch_projects",
                     text="",
                     icon="FILE_REFRESH")

        # --------------------------------------------------------------
        #  Job settings
        # --------------------------------------------------------------
        box = layout.box()
        box.label(text="Job Settings", icon="SCENE_DATA")
        col = box.column(align=True)

        # Upload project
        self.draw_toggle_row(
            col,
            (props, "use_upload_project"),
            (props, "project_path"),
            toggle_text="Upload Project",
            content_text="Project Path"
        )
        col.separator()                 # <— NEW: adds vertical gap

        # Job name
        self.draw_toggle_row(
            col,
            (props, "use_file_name"),
            (props, "job_name"),
            toggle_text="Use File Name",
            content_text="Job Name",
            invert=True,
        )
        col.separator()                 # <— NEW

        # Render format
        self.draw_toggle_row(
            col,
            (props, "use_scene_render_format"),
            (props, "render_format"),
            toggle_text="Use Scene Format",
            content_text="Render Format",
            invert=True,
        )
        col.separator()                 # <— NEW

        # Render type selector
        col.prop(props, "render_type", text="Type")

        # --------------------------------------------------------------
        #  Frame range / current frame
        # --------------------------------------------------------------
        box = layout.box()
        box.label(text="Frame Range", icon="TIME")
        col = box.column(align=True)

        use_scene_label = (
            "Use Current Frame" if props.render_type == "IMAGE"
            else "Use Scene Range"
        )
        col.prop(props, "use_scene_frame_range", text=use_scene_label)

        if props.render_type == "IMAGE":
            row = col.row(align=True)
            row.prop(props, "frame_start", text="Frame")
            row.enabled = not props.use_scene_frame_range
        else:
            row = col.row(align=True)
            row.prop(props, "frame_start", text="Start")
            row.prop(props, "frame_end",   text="End")
            row.enabled = not props.use_scene_frame_range

        # --------------------------------------------------------------
        #  Misc
        # --------------------------------------------------------------
        layout.prop(props, "blender_version", text="Blender Version")
        layout.separator()
        layout.operator("superluminal.submit_job",
                        text="Submit Render Job",
                        icon="RENDER_STILL")
        layout.separator()
        layout.operator("superluminal.download_output",
                        text="Download Render Output",
                        icon="FILE_FOLDER")

# --------------------------------------------------------------------
#  Registration
# --------------------------------------------------------------------
classes = (SUPERLUMINAL_PT_RenderPanel,)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
