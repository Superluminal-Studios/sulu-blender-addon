"""
panels.py – Superluminal Render UI

• “Included Add-ons” lives inside Advanced ▸ Included Add-ons (collapsible).
• Selection is persisted per scene in
      Scene.superluminal_settings.included_addons  (semicolon-separated).
• Added extra spacing before warning/info labels so they don’t hug the buttons.
"""

from __future__ import annotations

# ─── Blender / stdlib ─────────────────────────────────────────
import bpy
import addon_utils
import sys
from bpy.types import UILayout

# ─── Local helpers -------------------------------------------
from .preferences import (
    get_job_items,
)
from .utils.version_utils import get_blender_version_string
from .constants import DEFAULT_ADDONS
from .storage import Storage
from .preferences import refresh_jobs_collection, draw_header_row
from .icons import preview_collections

# ╭──────────────────  Global runtime list  ───────────────────╮
addons_to_send: list[str] = []          # filled from scene property


def _read_addons_from_scene(scene: bpy.types.Scene) -> None:
    """Refresh the in-memory list from the scene property (read-only)."""
    props = scene.superluminal_settings
    addons_to_send.clear()
    addons_to_send.extend([m for m in props.included_addons.split(";") if m])


# ------------------------------------------------------------------
#  Operators
# ------------------------------------------------------------------
class ToggleAddonSelectionOperator(bpy.types.Operator):
    """Tick / untick an add-on for inclusion in the upload zip"""
    bl_idname = "superluminal.toggle_addon_selection"
    bl_label  = "Toggle Add-on Selection"

    addon_name: bpy.props.StringProperty()

    def execute(self, context):
        if self.addon_name in addons_to_send:
            addons_to_send.remove(self.addon_name)
        else:
            addons_to_send.append(self.addon_name)

        # write back to .blend (allowed in operator context)
        context.scene.superluminal_settings.included_addons = ";".join(addons_to_send)
        context.area.tag_redraw()
        return {"FINISHED"}


# ------------------------------------------------------------------
#  UI helpers
# ------------------------------------------------------------------
def _addon_row(layout: UILayout, mod_name: str, pretty_name: str) -> None:
    enabled = mod_name in addons_to_send
    row = layout.row(align=True)
    row.operator(
        ToggleAddonSelectionOperator.bl_idname,
        text="",
        icon="CHECKBOX_HLT" if enabled else "CHECKBOX_DEHLT",
        emboss=False,
    ).addon_name = mod_name
    row.label(text=pretty_name)


# ------------------------------------------------------------------
#  Main panel
# ------------------------------------------------------------------
class SUPERLUMINAL_PT_RenderPanel(bpy.types.Panel):
    bl_idname      = "SUPERLUMINAL_PT_RenderPanel"
    bl_label       = "Superluminal Render"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"

    # ── little UI helpers ─────────────────────────────────────
    @staticmethod
    def _toggle_row(col, toggle_prop, content_prop, *,
                    toggle_text="", content_text="", invert=False):
        toggle_row = col.row(align=True)
        toggle_row.prop(toggle_prop[0], toggle_prop[1], text=toggle_text)

        content_row = col.row(align=True)
        content_row.prop(content_prop[0], content_prop[1], text=content_text)
        content_row.enabled = (toggle_prop[0].path_resolve(toggle_prop[1]) ^ invert)

    @staticmethod
    def _section_header(box, owner, prop_name, text):
        header_row = box.row(align=True)
        expanded   = owner.path_resolve(prop_name)
        header_row.prop(
            owner, prop_name,
            icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
            text="", emboss=False
        )
        header_row.label(text=text)
        return expanded
    
    def draw_header(self, context):
        self.layout.label(
            text="", icon_value=preview_collections["main"].get("SULU").icon_id
        )

    # ── draw ─────────────────────────────────────────────────
    def draw(self, context):
        scene  = context.scene
        _read_addons_from_scene(scene)            # refresh list (read-only)

        layout = self.layout
        layout.use_property_split   = True
        layout.use_property_decorate = False

        props  = scene.superluminal_settings
        wm_props = scene.sulu_wm_settings
        prefs  = context.preferences.addons[__package__].preferences

        refresh_jobs_collection(prefs)

        logged_in   = bool(Storage.data["user_token"])
        projects_ok = len(Storage.data["projects"]) > 0
        jobs_ok     = len(Storage.data["jobs"]) > 0

        # --------------------------------------------------  Project selector
        project_row_container = layout.row(align=True)
        project_selection_row = project_row_container.row(align=True)
        project_selection_row.enabled = logged_in and projects_ok
        project_selection_row.prop(prefs, "project_id", text="Project")
        project_row_container.operator(
            "superluminal.fetch_projects", text="", icon="FILE_REFRESH"
        )

        if not logged_in:
            layout.separator()
            layout.label(
                text="Login in the preferences to enable uploads and downloads.",
                icon='ERROR'
            )

        # --------------------------------------------------  Project upload settings
        upload_settings_box = layout.box()
        if self._section_header(upload_settings_box, props,
                                "upload_settings", "Upload Settings"):

            col = upload_settings_box.column(align=True)
            col.prop(props, "upload_project_as_zip")

            col = upload_settings_box.column(align=True)
            col.prop(props, "automatic_project_path")

            manual_project_path_col = col.column(align=True)
            manual_project_path_col.active = not props.automatic_project_path
            manual_project_path_col.prop(props, "custom_project_path")

            col.enabled = not props.upload_project_as_zip

            # ---- Included Add-ons (collapsible) ----
            col = upload_settings_box.column(align=True)
            addons_box = col.box()
            if self._section_header(
                addons_box, props, "show_addon_list", "Include Enabled Addons"
            ):
                addons_column = addons_box.column(align=True)
                enabled_addons: list[tuple[str, str]] = []

                for addon in bpy.context.preferences.addons:
                    mod_name = addon.module
                    if mod_name == __package__:
                        continue
                    if mod_name in DEFAULT_ADDONS:
                        continue

                    mod = None
                    mod = [m for m in addon_utils.modules() if m.__name__ == mod_name][0]

                    if mod:
                        pretty_name = addon_utils.module_bl_info(mod).get("name", mod_name)
                        enabled_addons.append((mod_name, pretty_name))

                if not enabled_addons:
                    addons_column.label(text="No Add-ons Enabled", icon="INFO")
                else:
                    for mod_name, pretty in enabled_addons:
                        _addon_row(addons_column, mod_name, pretty)

        # --------------------------------------------------  Upload section
        submission_box = layout.box()
        if self._section_header(submission_box, props,
                                "show_upload", "Job Submission"):

            col = submission_box.column(align=True)
            self._toggle_row(
                col,
                (props, "use_file_name"), (props, "job_name"),
                toggle_text="Use File Name as Job Name",
                content_text="Job Name",
                invert=True
            )
            col.separator()

            self._toggle_row(
                col,
                (props, "use_scene_image_format"), (props, "image_format"),
                toggle_text="Use Scene Image Format",
                content_text="Image Format",
                invert=True
            )
            col.separator()

            col.prop(props, "render_type")
            col.separator()

            frame_column = col.column(align=True)
            frame_toggle_label = (
                "Use Current Frame" if props.render_type == "IMAGE"
                else "Use Scene Frame Range"
            )
            frame_column.prop(props, "use_scene_frame_range", text=frame_toggle_label)

            custom_frame_column = frame_column.column(align=True)
            custom_frame_column.active = not props.use_scene_frame_range

            if props.render_type == "IMAGE":
                custom_frame_column.prop(props, "frame_start", text="Frame")
            else:
                custom_frame_column.prop(props, "frame_start", text="Start")
                custom_frame_column.prop(props, "frame_end",   text="End")
                custom_frame_column.prop(
                    props, "frame_stepping_size", text="Stepping"
                )

            col.separator()

            submit_row = col.row()
            using_video_format = (
                bpy.context.scene.render.image_settings.file_format
                in ["FFMPEG", "AVI_JPEG", "AVI_RAW"]
            )
            submit_row.enabled = (
                logged_in and projects_ok
                and not (using_video_format and props.use_scene_image_format)
            )
            submit_row.operator(
                "superluminal.submit_job",
                text="Submit Render Job",
                icon="RENDER_STILL"
            )

            if using_video_format and props.use_scene_image_format:
                col.separator()
                col.label(
                    text=(
                        "Video formats are not supported for rendering. "
                        f"Output is set to "
                        f"{bpy.context.scene.render.image_settings.file_format}."
                    ),
                    icon="ERROR"
                )

            if bpy.data.is_dirty:
                warning_row = col.row()
                warning_row.label(
                    text=(
                        "You have unsaved changes. "
                        "Some changes may not be included in the render job."
                    ),
                    icon="ERROR"
                )

            # ---- spacing before warnings ----
            if not logged_in:
                col.separator()
                col.label(text="Log in first.", icon='ERROR')
            elif not projects_ok:
                col.separator()
                col.label(
                    text="Refresh project list and select a project.", icon='INFO'
                )


        # --------------------------------------------------  Advanced section (+ add-ons)
        advanced_box = layout.box()
        if self._section_header(advanced_box, props,
                                "show_advanced", "Advanced"):

            col = advanced_box.column(align=True)
            self._toggle_row(
                col,
                (props, "auto_determine_blender_version"), (props, "blender_version"),
                toggle_text=f"Use Current Blender Version [{get_blender_version_string()}]",
                content_text="Blender Version",
                invert=True
            )
            col.separator()

            col = advanced_box.column(align=True)
            col.label(text="Experimental Features:", icon="EXPERIMENTAL")
            col.prop(props, "ignore_errors")
            col.prop(props, "use_bserver")
            col.prop(props, "use_async_upload")


        # --------------------------------------------------  Download section
        download_box = layout.box()
        if self._section_header(download_box, props,
                                "show_download", "Render Jobs"):

            # ── Header row ────────────────────────────────────────────
            hdr = download_box.row()                # one horizontal strip

            # Left-hand group
            left = hdr.row(align=True)
            left.prop(
                wm_props, "live_job_updates",
                text="", toggle=True,
                icon="RECORD_ON" if wm_props.live_job_updates else "RECORD_OFF"
            )
            left.label(text="Live Job Updates")

            # Right-hand group (aligned hard-right)
            right = hdr.row(align=True)
            right.alignment = 'RIGHT'               # pushes this sub-row to the edge
            right.operator("superluminal.fetch_project_jobs",
                        text="",
                        icon='FILE_REFRESH')
            right.menu("SUPERLUMINAL_MT_job_columns",
                    text="",
                    icon='DOWNARROW_HLT')

            # ── The list itself (unchanged) ───────────────────────────
            list_col = download_box.column()
            list_col.enabled = logged_in and jobs_ok

            draw_header_row(list_col, prefs)
            list_col.template_list(
                "SUPERLUMINAL_UL_job_items", "",
                prefs, "jobs",
                prefs, "active_job_index",
                rows=3
            )

            job_info_row = download_box.row(align=True)

            projects = Storage.data.get("projects", [])              # always a list

            selected_project = next(                                 # None if not found / empty
                (p for p in projects if p.get("id") == prefs.project_id),
                None
            )

            # Collect jobs only if we actually have a project
            selected_project_jobs = (
                [j for j in Storage.data.get("jobs", {}).values()
                if j.get("project_id") == selected_project.get("id")]
                if selected_project else []
            )

            job_id, job_name = "", ""
            if selected_project_jobs and prefs.active_job_index < len(selected_project_jobs):
                sel_job = selected_project_jobs[prefs.active_job_index]
                job_id   = sel_job.get("id", "")
                job_name = sel_job.get("name", "")

            job_info_row.label(text=str(job_name))
            browser_button = job_info_row.operator(
                "superluminal.open_browser",
                text="Open in Browser",
                icon="URL"
            )   

            browser_button.job_id = job_id
            browser_button.project_id = prefs.project_id

        
            download_box.prop(props, "download_path")

            download_button_row = download_box.row()
            download_operator = download_button_row.operator(
                "superluminal.download_job",
                text="Download Job Output",
                icon="SORT_ASC"
            )

            download_operator.job_id = job_id
            download_operator.job_name = job_name

            enable_job_actions = (
                logged_in and jobs_ok and bool(job_name) and job_id != ""
            )

            download_button_row.enabled = enable_job_actions
            job_info_row.enabled = enable_job_actions


            if not logged_in:
                download_box.separator()
                download_box.label(text="Log in first.", icon='ERROR')
            elif not jobs_ok:
                download_box.separator()
                download_box.label(
                    text="Refresh job list and select a job.", icon='INFO'
                )

# ------------------------------------------------------------------
#  Registration
# ------------------------------------------------------------------
classes = (
    ToggleAddonSelectionOperator,
    SUPERLUMINAL_PT_RenderPanel,
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

def unregister():
    from bpy.utils import unregister_class
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
