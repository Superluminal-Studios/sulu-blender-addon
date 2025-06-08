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
import importlib
import sys
from bpy.types import UILayout

# ─── Local helpers -------------------------------------------
from .preferences import (
    get_job_items,
)
from .utils.version_utils import get_blender_version_string
from .constants import DEFAULT_ADDONS
from .storage import Storage
from .preferences import refresh_jobs_collection
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
    def _toggle_row(col, toggle_prop, content_prop, *, toggle_text="", content_text="", invert=False):
        r1 = col.row(align=True)
        r1.prop(toggle_prop[0], toggle_prop[1], text=toggle_text)
        r2 = col.row(align=True)
        r2.prop(content_prop[0], content_prop[1], text=content_text)
        r2.enabled = (toggle_prop[0].path_resolve(toggle_prop[1]) ^ invert)

    @staticmethod
    def _section_header(box, owner, prop_name, text):
        row      = box.row(align=True)
        expanded = owner.path_resolve(prop_name)
        row.prop(owner, prop_name,
                 icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
                 text="", emboss=False)
        row.label(text=text)
        return expanded

    # ── draw ─────────────────────────────────────────────────
    def draw(self, context):
        scene  = context.scene
        _read_addons_from_scene(scene)            # refresh list (read-only)

        layout = self.layout
        layout.use_property_split   = True
        layout.use_property_decorate = False

        props  = scene.superluminal_settings
        prefs  = context.preferences.addons[__package__].preferences

        refresh_jobs_collection(prefs)

        Storage.load()

        logged_in   = bool(Storage.data["user_token"])
        projects_ok = len(Storage.data["projects"]) > 0
        jobs_ok     = len(Storage.data["jobs"]) > 0

        # --------------------------------------------------  Project selector
        row = layout.row(align=True)
        pr  = row.row(align=True)
        pr.enabled = logged_in and projects_ok
        pr.prop(prefs, "project_id", text="Project")
        row.operator("superluminal.fetch_projects", text="", icon="FILE_REFRESH")

        if not logged_in:
            layout.separator()
            layout.label(text="Login in the preferences to enable uploads and downloads.", icon='ERROR')

        # --------------------------------------------------  Project upload settings

        pb = layout.box()
        if self._section_header(pb, props, "upload_settings", "Upload Settings"):
            col = pb.column(align=True)
            col.prop(props, "upload_project_as_zip")
            col = pb.column(align=True)
            col.prop(props, "automatic_project_path")
            sub = col.column(align=True)
            sub.active = not props.automatic_project_path
            sub.prop(props, "custom_project_path")
            col.enabled = not props.upload_project_as_zip

             # ---- Included Add-ons (collapsible) ----
            col = pb.column(align=True)
            adb = col.box()
            if self._section_header(adb, props, "show_addon_list", "Include Enabled Addons"):
                a_col = adb.column(align=True)
                enabled_addons: list[tuple[str, str]] = []
                for addon in bpy.context.preferences.addons:
                    mod_name = addon.module
                    if mod_name == __package__:
                        continue
                    if mod_name in DEFAULT_ADDONS:
                        continue
                    pretty = mod_name
                    mod = sys.modules.get(mod_name)
                    if not mod:
                        try:
                            mod = importlib.import_module(mod_name)
                        except ModuleNotFoundError:
                            mod = None
                    if mod and hasattr(mod, "bl_info"):
                        pretty = mod.bl_info.get("name", mod_name)
                    enabled_addons.append((mod_name, pretty))
                if not enabled_addons:
                    a_col.label(text="No Add-ons Enabled", icon="INFO")
                else:
                    for mod_name, pretty in enabled_addons:
                        _addon_row(a_col, mod_name, pretty)


        # --------------------------------------------------  Upload section
        ub = layout.box()
        if self._section_header(ub, props, "show_upload", "Job Submission"):
            col = ub.column(align=True)
            self._toggle_row(col, (props, "use_file_name"), (props, "job_name"),
                             toggle_text="Use File Name as Job Name", content_text="Job Name", invert=True)
            col.separator()
            self._toggle_row(col, (props, "use_scene_image_format"), (props, "image_format"),
                             toggle_text="Use Scene Image Format", content_text="Image Format", invert=True)
            col.separator()
            col.prop(props, "render_type")
            col.separator()
            fc = col.column(align=True)
            lbl = "Use Current Frame" if props.render_type == "IMAGE" else "Use Scene Frame Range"
            fc.prop(props, "use_scene_frame_range", text=lbl)
            sub = fc.column(align=True)
            sub.active = not props.use_scene_frame_range
            if props.render_type == "IMAGE":
                sub.prop(props, "frame_start", text="Frame")
            else:
                sub.prop(props, "frame_start", text="Start")
                sub.prop(props, "frame_end",   text="End")
                sub.prop(props, "frame_stepping_size", text="Stepping")
            col.separator()
            sr = col.row()
            using_video_format = bpy.context.scene.render.image_settings.file_format in ["FFMPEG", "AVI_JPEG", "AVI_RAW"]
            sr.enabled = logged_in and projects_ok and not (using_video_format and props.use_scene_image_format)
            sr.operator("superluminal.submit_job", text="Submit Render Job", icon="RENDER_STILL")

            if using_video_format and props.use_scene_image_format:
                col.separator()
                col.label(text=f"Video formats are not supported for rendering. Output is set to {bpy.context.scene.render.image_settings.file_format}.", icon="ERROR")

            if bpy.data.is_dirty:
                row = col.row()
                row.label(text="You have unsaved changes. Some changes may not be included in the render job.", icon="ERROR")

            # ---- spacing before warnings ----
            if not logged_in:
                col.separator()
                col.label(text="Log in first.", icon='ERROR')
            elif not projects_ok:
                col.separator()
                col.label(text="Refresh project list and select a project.", icon='INFO')

        # --------------------------------------------------  Download section
        db = layout.box()
        if self._section_header(db, props, "show_download", "Download"):
            col = db.column(align=True)
            ir = col.row(align=True)
            ip = ir.row(align=True)
            ip.enabled = logged_in and jobs_ok
            # ip.prop(prefs, "job_id", text="Job")

            ip.template_list(
                "SUPERLUMINAL_UL_job_items",
                "",                         # list_ID – leave empty
                prefs, "jobs",              # CollectionProperty
                prefs, "active_job_index",  # IntProperty that stores the active row
                rows=3                      # tweak as you like
            )
            ir.operator("superluminal.fetch_project_jobs", text="", icon="FILE_REFRESH")
            col.separator()
            col.prop(props, "download_path")
            col.separator()
            dr = col.row()
            dop = dr.operator("superluminal.download_job", text="Download Job Output", icon="SORT_ASC")
            dop.job_id = prefs.job_id
            job_name = ""
            for item in (get_job_items(self, context) or []):
                if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == prefs.job_id:
                    job_name = item[1]
                    break
            dop.job_name = job_name
            dr.enabled = logged_in and jobs_ok and bool(job_name)

            # ---- spacing before warnings ----
            if not logged_in:
                col.separator()
                col.label(text="Log in first.", icon='ERROR')
            elif not jobs_ok:
                col.separator()
                col.label(text="Refresh job list and select a job.", icon='INFO')

        # --------------------------------------------------  Advanced section (+ add-ons)
        ab = layout.box()
        if self._section_header(ab, props, "show_advanced", "Advanced"):
            col = ab.column(align=True)
            self._toggle_row(col, (props, "auto_determine_blender_version"), (props, "blender_version"),
                             toggle_text=f"Use Current Blender Version [{get_blender_version_string()}]", content_text="Blender Version", invert=True)
            col.separator()

            col = ab.column(align=True)
            col.label(text="Experimental Features:", icon="EXPERIMENTAL")
            col.prop(props, "ignore_errors")
            col.prop(props, "use_bserver")
            col.prop(props, "use_async_upload")

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
    for cls in reversed(classes):
        unregister_class(cls)
