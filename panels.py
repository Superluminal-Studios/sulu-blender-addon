from __future__ import annotations

# ─── Blender / stdlib ─────────────────────────────────────────
import bpy
import addon_utils
from bpy.types import UILayout

# ─── Local helpers -------------------------------------------
from .utils.version_utils import get_blender_version_string
from .constants import DEFAULT_ADDONS
from .storage import Storage
from .preferences import refresh_jobs_collection, draw_header_row
from .icons import preview_collections
from .preferences import draw_login

# NEW: project scan for UI warnings about cross-drive assets
from .utils.project_scan import quick_cross_drive_hint, human_shorten

# ╭──────────────────  Global runtime list  ───────────────────╮
addons_to_send: list[str] = []          # filled from scene property


def _read_addons_from_scene(scene: bpy.types.Scene) -> None:
    """Refresh the in-memory list from the scene property (read-only)."""
    props = scene.superluminal_settings
    addons_to_send.clear()
    addons_to_send.extend([m for m in props.included_addons.split(";") if m])


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


def _value_row(layout: UILayout, *, align: bool = False) -> UILayout:
    """
    Return a row aligned with the *value* column when property split is on.
    Use for tools that should visually align with property rows.
    """
    r = layout.row(align=align)
    r.label(text="")  # occupy label column
    sub = r.row(align=align)
    sub.use_property_split = False
    sub.use_property_decorate = False
    return sub


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
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


# ------------------------------------------------------------------
#  Main panel (parent)
# ------------------------------------------------------------------
class SUPERLUMINAL_PT_RenderPanel(bpy.types.Panel):
    bl_idname      = "SUPERLUMINAL_PT_RenderPanel"
    bl_label       = "Superluminal Render"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"

    def draw_header(self, context):
        self.layout.label(
            text="", icon_value=preview_collections["main"].get("SULU").icon_id
        )

    def draw(self, context):
        # Keep the parent panel minimal; put content in sub-panels
        scene = context.scene
        _read_addons_from_scene(scene)  # keep runtime list fresh

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        prefs = context.preferences.addons[__package__].preferences

        refresh_jobs_collection(prefs)

        logged_in   = bool(Storage.data.get("user_token"))
        projects_ok = len(Storage.data.get("projects", [])) > 0

        if not logged_in:
            box = layout.box()
            box.alert = True  # make warning red
            draw_login(box)
            return

        # Project selector row (always visible)
        row = layout.row(align=True)
        row.enabled = logged_in and projects_ok
        row.prop(prefs, "project_id", text="Project")
        row.operator("superluminal.fetch_projects", text="", icon="FILE_REFRESH")



# ------------------------------------------------------------------
#  Sub-panels (native look & feel)
# ------------------------------------------------------------------
class SUPERLUMINAL_PT_Submission(bpy.types.Panel):
    bl_idname      = "SUPERLUMINAL_PT_Submission"
    bl_label       = "Job Submission"
    bl_parent_id   = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"
    bl_order       = 0  # Top-most among siblings
    # Note: open by default (no DEFAULT_CLOSED)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene  = context.scene
        props  = scene.superluminal_settings
        prefs  = context.preferences.addons[__package__].preferences

        logged_in   = bool(Storage.data.get("user_token"))
        projects_ok = len(Storage.data.get("projects", [])) > 0

        # Job name toggle + field
        col = layout.column()
        col.prop(props, "use_file_name", text="Use File Name as Job Name")
        sub = col.column()
        sub.active = not props.use_file_name
        sub.prop(props, "job_name", text="Job Name")

        # Image format (enum with "Scene Image Format" option)
        col = layout.column()
        col.prop(props, "image_format", text="Image Format")

        # Frame range controls (apply to Animation submissions)
        box = layout.box()
        col = box.column()
        col.prop(props, "use_scene_frame_range", text="Use Scene Frame Range")

        sub = col.column()
        range_col = sub.column(align=True)
        if props.use_scene_frame_range:
            # Show actual Scene range in disabled fields
            sub.enabled = False
            range_col.prop(scene, "frame_start", text="Start")
            range_col.prop(scene, "frame_end",   text="End")
            sub.prop(scene, "frame_step",  text="Stepping")
        else:
            range_col.prop(props, "frame_start",          text="Start")
            range_col.prop(props, "frame_end",            text="End")
            sub.prop(props, "frame_stepping_size",  text="Stepping")

        # Submit buttons — same formatting as Download button (plain row)
        VIDEO_FORMATS = {"FFMPEG", "AVI_JPEG", "AVI_RAW"}
        effective_format = (
            scene.render.image_settings.file_format
            if props.image_format == "SCENE" else props.image_format
        )
        using_video_format = effective_format in VIDEO_FORMATS

        row = layout.row(align=True)
        row.enabled = (logged_in and projects_ok and not using_video_format)

        op_still = row.operator("superluminal.submit_job", text="Submit Still", icon="RENDER_STILL")
        op_still.mode = 'STILL'

        op_anim = row.operator("superluminal.submit_job", text="Submit Animation", icon="RENDER_ANIMATION")
        op_anim.mode = 'ANIMATION'

        # Other info/warnings (plain rows)
        if not logged_in:
            return

        if using_video_format:
            r = layout.row()
            r.alert = True  # make warning red
            if props.image_format == "SCENE":
                r.label(
                    text=f"Video formats are not supported for rendering. Scene output is set to {scene.render.image_settings.file_format}.",
                    icon="ERROR"
                )
            else:
                r.label(
                    text=f"Video formats are not supported for rendering ({effective_format}).",
                    icon="ERROR"
                )

        # Fixed-height unsaved-changes row (plain row)
        warn_row = layout.row()
        if bpy.data.is_dirty:
            warn_row.alert = True  # make warning red
            warn_row.label(
                text="You have unsaved changes. Some changes may not be included in the render job.",
                icon="ERROR"
            )
        else:
            warn_row.label(text="")  # placeholder keeps panel height stable


class SUPERLUMINAL_PT_UploadSettings(bpy.types.Panel):
    bl_idname      = "SUPERLUMINAL_PT_UploadSettings"
    bl_label       = "Upload Settings"
    bl_parent_id   = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"
    bl_options     = {'DEFAULT_CLOSED'}
    bl_order       = 10

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        # Upload type selector (always visible)
        layout.prop(props, "upload_type", text="Upload Type")

        # Cross-drive dependency warning (only relevant to Project uploads)
        if props.upload_type == 'PROJECT':
            has_cross, summary = quick_cross_drive_hint()
            if not summary.blend_saved:
                info_row = layout.row()
                info_row.alert = True  # treat as warning for visibility
                info_row.label(text="Save your .blend to enable accurate project root detection.", icon="ERROR")
            if has_cross:
                box = layout.box()
                box.alert = True  # make warning red
                box.label(
                    text="Some dependencies are on a different drive and will be EXCLUDED from Project uploads.",
                    icon="ERROR"
                )
                box.label(text="Move assets onto the same drive, or switch Upload Type to Zip.")
                # show a few examples
                for p in summary.examples_other_roots(3):
                    box.label(text=human_shorten(p), icon="LIBRARY_DATA_BROKEN")
                if summary.cross_drive_count() > 3:
                    box.label(text=f"…and {summary.cross_drive_count() - 3} more")

        # Only show project-path options when 'Project' is selected
        if props.upload_type == 'PROJECT':
            col = layout.column()
            col.prop(props, "automatic_project_path")

            sub = col.column()
            sub.active = not props.automatic_project_path
            sub.prop(props, "custom_project_path")


class SUPERLUMINAL_PT_IncludeAddons(bpy.types.Panel):
    bl_idname      = "SUPERLUMINAL_PT_IncludeAddons"
    bl_label       = "Include Enabled Addons"
    bl_parent_id   = "SUPERLUMINAL_PT_UploadSettings"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        _read_addons_from_scene(context.scene)

        enabled_addons: list[tuple[str, str]] = []
        for addon in bpy.context.preferences.addons:
            mod_name = addon.module
            if mod_name == __package__:
                continue
            if mod_name in DEFAULT_ADDONS:
                continue

            mod = next((m for m in addon_utils.modules() if m.__name__ == mod_name), None)
            if mod:
                pretty_name = addon_utils.module_bl_info(mod).get("name", mod_name)
                enabled_addons.append((mod_name, pretty_name))

        if not enabled_addons:
            layout.label(text="No Add-ons Enabled", icon="INFO")
        else:
            for mod_name, pretty in enabled_addons:
                _addon_row(layout, mod_name, pretty)


# ─────────────────────────────────────────────────────────────
#  "Render Node Settings" (renamed from Render Node)
# ─────────────────────────────────────────────────────────────
class SUPERLUMINAL_PT_RenderNode(bpy.types.Panel):
    bl_idname      = "SUPERLUMINAL_PT_RenderNode"
    bl_label       = "Render Node Settings"
    bl_parent_id   = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"
    bl_options     = {'DEFAULT_CLOSED'}  # parent stays closed by default
    bl_order       = 20

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props  = context.scene.superluminal_settings

        # Blender version (auto toggle + version enum)
        col = layout.column()
        col.prop(
            props,
            "auto_determine_blender_version",
            text=f"Use Current Blender Version [{get_blender_version_string()}]",
        )
        sub = col.column()
        sub.active = not props.auto_determine_blender_version
        sub.prop(props, "blender_version", text="Blender Version")


class SUPERLUMINAL_PT_RenderNode_Experimental(bpy.types.Panel):
    """Separate sub-panel to mirror native grouping."""
    bl_idname      = "SUPERLUMINAL_PT_RenderNode_Experimental"
    bl_label       = "Experimental"
    bl_parent_id   = "SUPERLUMINAL_PT_RenderNode"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"
    bl_order       = 0
    # Note: OPEN by default (no DEFAULT_CLOSED)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props  = context.scene.superluminal_settings

        col = layout.column()
        col.prop(props, "ignore_errors", text="Finish Frame When Errored")
        col.prop(props, "use_bserver", text="Persistence Engine")
        col.prop(props, "use_async_upload", text="Async Frame Upload")


class SUPERLUMINAL_PT_Jobs(bpy.types.Panel):
    bl_idname      = "SUPERLUMINAL_PT_Jobs"
    bl_label       = "Render Jobs"
    bl_parent_id   = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type  = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context     = "render"
    bl_options     = {'DEFAULT_CLOSED'}
    bl_order       = 30

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene  = context.scene
        props  = scene.superluminal_settings
        wm_props = scene.sulu_wm_settings
        prefs  = context.preferences.addons[__package__].preferences

        refresh_jobs_collection(prefs)

        logged_in = bool(Storage.data.get("user_token"))
        jobs_ok   = len(Storage.data.get("jobs", {})) > 0

        # Top row: full width, shove everything to the absolute right
        tools = layout.row(align=True)
        tools.use_property_split = False
        tools.use_property_decorate = False
        tools.separator_spacer()  # eat all space → next items dock to the right edge
        tools.prop(wm_props, "live_job_updates", text="Auto Refresh")
        tools.operator("superluminal.fetch_project_jobs", text="", icon='FILE_REFRESH')
        tools.separator()  # small gap
        tools.menu("SUPERLUMINAL_MT_job_columns", text="", icon='DOWNARROW_HLT')

        # Job list
        col = layout.column()
        col.enabled = logged_in and jobs_ok
        draw_header_row(col, prefs)

        if not logged_in or not jobs_ok:
            box = col.box()
            if not logged_in:
                box.alert = True  # make warning red
                box.label(text="Log in to see your jobs.", icon='ERROR')
            elif not jobs_ok:
                # Not really a warning, keep informational
                box.label(text="No jobs found in selected project.", icon='INFO')
            return

        col.template_list(
            "SUPERLUMINAL_UL_job_items", "",
            prefs, "jobs",
            prefs, "active_job_index",
            rows=3
        )

        # Determine selected job
        projects = Storage.data.get("projects", [])
        selected_project = next((p for p in projects if p.get("id") == prefs.project_id), None)
        selected_project_jobs = (
            [j for j in Storage.data.get("jobs", {}).values()
             if j.get("project_id") == selected_project.get("id")]
            if selected_project else []
        )

        job_id, job_name = "", ""
        if selected_project_jobs and 0 <= prefs.active_job_index < len(selected_project_jobs):
            sel_job = selected_project_jobs[prefs.active_job_index]
            job_id   = sel_job.get("id", "")
            job_name = sel_job.get("name", "")

        # Selected job row + open button
        row = layout.row(align=True)
        row.enabled = logged_in and jobs_ok and bool(job_name) and job_id != ""
        row.label(text=str(job_name))
        op = row.operator("superluminal.open_browser", text="Open in Browser", icon="URL")
        op.job_id = job_id
        op.project_id = prefs.project_id

        # Download path + button
        layout.prop(props, "download_path", text="Download Path")

        row = layout.row()
        row.enabled = logged_in and jobs_ok and bool(job_name) and job_id != ""
        op2 = row.operator("superluminal.download_job", text="Download Job Output", icon="SORT_ASC")
        op2.job_id = job_id
        op2.job_name = job_name



# ------------------------------------------------------------------
#  Registration
# ------------------------------------------------------------------
classes = (
    ToggleAddonSelectionOperator,
    SUPERLUMINAL_PT_RenderPanel,
    SUPERLUMINAL_PT_Submission,
    SUPERLUMINAL_PT_UploadSettings,
    SUPERLUMINAL_PT_IncludeAddons,
    SUPERLUMINAL_PT_RenderNode,
    SUPERLUMINAL_PT_RenderNode_Experimental,
    SUPERLUMINAL_PT_Jobs,
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
