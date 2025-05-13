import bpy
from .preferences import get_job_items


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
    def draw_toggle_row(col, toggle_prop, content_prop, *, toggle_text="", content_text="", invert=False):
        """Checkbox row followed by a property row that is disabled while
        the checkbox is (un)checked. Works nicely with property-split
        layouts because each row contains exactly one UI element.
        """
        checkbox_row = col.row(align=True)
        checkbox_row.prop(toggle_prop[0], toggle_prop[1], text=toggle_text)

        value_row = col.row(align=True)
        value_row.prop(content_prop[0], content_prop[1], text=content_text)
        value_row.enabled = (toggle_prop[0].path_resolve(toggle_prop[1]) ^ invert)

    @staticmethod
    def draw_section_header(box, prop_owner, prop_name, text):
        """Clickable header inside *box*. Returns *True* if expanded."""
        header = box.row(align=True)
        expanded = prop_owner.path_resolve(prop_name)
        icon = "TRIA_DOWN" if expanded else "TRIA_RIGHT"
        header.prop(prop_owner, prop_name, icon=icon, text="", emboss=False)
        header.label(text=text)
        return expanded

    # ------------------------------------------------------------------
    #  Draw
    # ------------------------------------------------------------------
    def draw(self, context):
        layout = self.layout
        # Match Blender’s built-in panels
        layout.use_property_split = True
        layout.use_property_decorate = False  # no anim-dots

        scene  = context.scene
        props  = scene.superluminal_settings
        prefs  = context.preferences.addons[__package__].preferences

        # --------------------------------------------------------------
        #  Project selector
        # --------------------------------------------------------------
        row = layout.row(align=True)
        row.prop(prefs, "project_list", text="Project")
        row.operator("superluminal.fetch_projects", text="", icon="FILE_REFRESH")

        # --------------------------------------------------------------
        #  Project uploads
        # --------------------------------------------------------------
        project_box = layout.box()
        if self.draw_section_header(project_box, props, "show_project_uploads", "Upload Settings"):
            col = project_box.column(align=True)

            # Upload entire project vs .blend-only ZIP
            col.prop(props, "upload_project_as_zip", text="Upload Project As Zip")

            # Custom project path override
            col = project_box.column(align=True)
            col.prop(props, "automatic_project_path", text="Automatic Project Path")
            sub = col.column(align=True)
            sub.active = not props.automatic_project_path
            sub.prop(props, "custom_project_path", text="Custom Project Path")

            col.enabled = not props.upload_project_as_zip

        # --------------------------------------------------------------
        #  Upload section
        # --------------------------------------------------------------
        upload_box = layout.box()
        if self.draw_section_header(upload_box, props, "show_upload", "Job Submission"):
            col = upload_box.column(align=True)

            # Job name override
            self.draw_toggle_row(
                col,
                (props, "use_file_name"),
                (props, "job_name"),
                toggle_text="Use File Name as Job Name",
                content_text="Job Name",
                invert=True,
            )
            col.separator()

            # Render format override
            self.draw_toggle_row(
                col,
                (props, "use_scene_render_format"),
                (props, "render_format"),
                toggle_text="Use Scene Render Format",
                content_text="Render Format",
                invert=True,
            )
            col.separator()

            col.prop(props, "render_type", text="Type")
            col.separator()

            # – Frame range – (no extra box, stacked Start/End)
            frame_col = col.column(align=True)

            use_scene_lbl = "Use Current Frame" if props.render_type == "IMAGE" else "Use Scene Range"
            frame_col.prop(props, "use_scene_frame_range", text=use_scene_lbl)

            # sub-column that becomes disabled when using scene range
            sub = frame_col.column(align=True)
            sub.active = not props.use_scene_frame_range

            if props.render_type == "IMAGE":
                sub.prop(props, "frame_start", text="Frame")
            else:
                sub.prop(props, "frame_start", text="Start")
                sub.prop(props, "frame_end",   text="End")

            col.separator()
            upload_box.operator("superluminal.submit_job", text="Submit Render Job", icon="RENDER_STILL")

        # --------------------------------------------------------------
        #  Download section
        # --------------------------------------------------------------
        download_box = layout.box()
        if self.draw_section_header(download_box, props, "show_download", "Download"):
            col = download_box.column(align=True)

            id_row = col.row(align=True)
            id_row.prop(props, "job_id", text="Job")
            id_row.operator("superluminal.fetch_project_jobs", text="", icon="FILE_REFRESH")
            col.separator()

            col.prop(props, "download_path", text="Download Path")
            col.separator()

            dl_row = col.row()
            dl_op  = dl_row.operator("superluminal.download_job", text="Download Job Output", icon="SORT_ASC")
            dl_op.job_id = props.job_id

            # Resolve job-name safely
            job_name = ""
            for item in (get_job_items(self, context) or []):
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                if item[0] == props.job_id:
                    job_name = item[1]
                    break
            dl_op.job_name = job_name
            if not job_name:
                dl_row.enabled = False

        # --------------------------------------------------------------
        #  Advanced section
        # --------------------------------------------------------------
        adv_box = layout.box()
        if self.draw_section_header(adv_box, props, "show_advanced", "Advanced"):
            col = adv_box.column(align=True)
            self.draw_toggle_row(
                col,
                (props, "auto_determine_blender_version"),
                (props, "blender_version"),
                toggle_text="Use Current Blender Version",
                content_text="Blender Version",
                invert=True,
            )
            col.separator()
            col.prop(props, "ignore_errors",  text="Complete on Error")


# --------------------------------------------------------------------
#  Registration helpers
# --------------------------------------------------------------------
classes = (SUPERLUMINAL_PT_RenderPanel,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
