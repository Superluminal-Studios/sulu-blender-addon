from __future__ import annotations

import bpy
import addon_utils
import time
from bpy.types import UILayout

from .utils.version_utils import get_blender_version_string
from .constants import DEFAULT_ADDONS
from .storage import Storage
from .preferences import refresh_jobs_collection, draw_header_row
from .preferences import draw_login, format_job_status
from .icons import get_icon_id, get_fallback_icon

from .utils.project_scan import quick_cross_drive_hint, human_shorten

addons_to_send: list[str] = []

# -----------------------------------------------------------------------------
# Enabled add-ons UI (sorted + scrollable, uses built-in UIList search)
# -----------------------------------------------------------------------------

# Cache for enabled addons list to avoid expensive rebuilds on every draw
_addon_cache: dict = {
    "enabled_set": None,  # frozenset of enabled addon module names
    "addon_list": [],     # list of (module_name, pretty_label) tuples
}


class SUPERLUMINAL_PG_AddonItem(bpy.types.PropertyGroup):
    module: bpy.props.StringProperty()
    label: bpy.props.StringProperty()


def _gather_enabled_addons_sorted() -> list[tuple[str, str]]:
    """Return enabled add-ons as (module_name, pretty_label), sorted by pretty_label.

    Uses a module lookup dict for O(n+m) instead of O(n*m) performance.
    """
    enabled: list[tuple[str, str]] = []

    # Build a lookup dict from module name -> module object (O(m) once)
    module_lookup: dict = {m.__name__: m for m in addon_utils.modules()}

    for addon in bpy.context.preferences.addons:
        mod_name = addon.module

        if mod_name == __package__:
            continue
        if mod_name in DEFAULT_ADDONS:
            continue

        mod = module_lookup.get(mod_name)
        pretty = (
            addon_utils.module_bl_info(mod).get("name", mod_name) if mod else mod_name
        )

        enabled.append((mod_name, pretty))

    # Sort by the displayed label (case-insensitive), then module name for stability.
    enabled.sort(key=lambda it: (it[1].casefold(), it[0].casefold()))
    return enabled


def _rebuild_enabled_addons_ui_cache(context) -> None:
    """Rebuild WindowManager cache collection for the UIList.

    Only rebuilds if the set of enabled addons has changed since last call.
    """
    # Build current set of enabled addon names (fast check)
    current_enabled = frozenset(
        addon.module for addon in bpy.context.preferences.addons
        if addon.module != __package__ and addon.module not in DEFAULT_ADDONS
    )

    # Skip rebuild if nothing changed
    if current_enabled == _addon_cache["enabled_set"]:
        return

    # Cache miss - rebuild the list
    _addon_cache["enabled_set"] = current_enabled
    _addon_cache["addon_list"] = _gather_enabled_addons_sorted()

    wm = context.window_manager
    items = wm.superluminal_ui_addons

    items.clear()

    for mod_name, pretty in _addon_cache["addon_list"]:
        it = items.add()
        it.module = mod_name
        it.label = pretty

    # Clamp index
    if wm.superluminal_ui_addons_index >= len(items):
        wm.superluminal_ui_addons_index = max(0, len(items) - 1)


class SUPERLUMINAL_UL_addon_items(bpy.types.UIList):
    """Scrollable list for enabled add-ons (built-in search works via filter_items)."""

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        # item is SUPERLUMINAL_PG_AddonItem
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            enabled = item.module in addons_to_send

            row = layout.row(align=True)
            op = row.operator(
                ToggleAddonSelectionOperator.bl_idname,
                text="",
                icon="CHECKBOX_HLT" if enabled else "CHECKBOX_DEHLT",
                emboss=False,
            )
            op.addon_name = item.module
            row.label(text=item.label)
        else:
            layout.label(text=item.label)

    def filter_items(self, context, data, propname):
        """
        Hook up Blender's built-in template_list search (filter_name) + optional alpha sorting.
        This is what makes the built-in search bar actually filter the list.
        """
        items = getattr(data, propname)
        helper = bpy.types.UI_UL_list

        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder: list[int] = []

        # Text filter (built-in search field)
        if self.filter_name:
            needle = self.filter_name.casefold().strip()
            for i, it in enumerate(items):
                label = (getattr(it, "label", "") or "").casefold()
                module = (getattr(it, "module", "") or "").casefold()
                if needle in label or needle in module:
                    flt_flags[i] = self.bitflag_filter_item
                else:
                    flt_flags[i] = 0

        # Optional alpha sort toggle (built-in)
        if self.use_filter_sort_alpha:
            flt_neworder = helper.sort_items_by_name(items, "label")
            if self.use_filter_sort_reverse:
                flt_neworder.reverse()

        return flt_flags, flt_neworder


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


def _projects_refresh_status() -> tuple[str, str]:
    err = str(Storage.panel_data.get("projects_refresh_error", "") or "").strip()
    if err:
        return "ERROR", f"Refresh projects error: {err}"

    refreshed_at = float(Storage.panel_data.get("projects_refresh_at", 0.0) or 0.0)
    if refreshed_at > 0:
        stamp = time.strftime("%H:%M:%S", time.localtime(refreshed_at))
        return "INFO", f"Projects refreshed: {stamp}"
    return "", ""


def _refresh_service_status() -> tuple[str, str]:
    state = str(Storage.panel_data.get("refresh_service_state", "") or "").strip().lower()
    if not state:
        return "", ""
    if state == "error":
        return "ERROR", "Auto refresh encountered an error."
    # "running" and other non-error states are intentionally silent in UI.
    return "", ""


def _should_show_refresh_state(*, jobs_refresh_error: str) -> bool:
    """Only show generic refresh state when no explicit jobs error is present."""
    return not str(jobs_refresh_error or "").strip()


# Operators
class ToggleAddonSelectionOperator(bpy.types.Operator):
    """Select or deselect an add-on for inclusion in the upload"""

    bl_idname = "superluminal.toggle_addon_selection"
    bl_label = "Toggle add-on selection"

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


# Main panel


class SUPERLUMINAL_PT_RenderPanel(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_RenderPanel"
    bl_label = " Superluminal Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw_header(self, context):
        icon_id = get_icon_id("LOGO")
        if icon_id:
            self.layout.label(text="", icon_value=icon_id)
        else:
            self.layout.label(text="", icon=get_fallback_icon("LOGO"))

    def draw(self, context):
        # Keep the parent panel minimal; put content in sub-panels
        scene = context.scene
        _read_addons_from_scene(scene)  # keep runtime list fresh

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        prefs = context.preferences.addons[__package__].preferences
        props = scene.superluminal_settings

        if Storage.data.get("user_token") != Storage.panel_data.get("last_token"):
            Storage.panel_data["last_token"] = Storage.data.get("user_token")

        refresh_jobs_collection(prefs)

        logged_in = bool(Storage.data.get("user_token"))
        projects_ok = len(Storage.data.get("projects", [])) > 0

        if not logged_in:
            box = layout.box()
            draw_login(box)
            return

        if logged_in and projects_ok:
            row = layout.row(align=True)
            row.prop(prefs, "project_id", text="Project")
            row.operator("superluminal.fetch_projects", text="", icon="FILE_REFRESH")
        else:
            row = layout.row(align=True)
            row.operator("superluminal.open_projects_web_page", text="Create Project")
            row.operator("superluminal.fetch_projects", text="", icon="FILE_REFRESH")

        status_icon, status_text = _projects_refresh_status()
        if status_text:
            status_row = layout.row()
            if status_icon == "ERROR":
                status_row.alert = True
            status_row.label(text=status_text, icon=status_icon)

        logged_in = bool(Storage.data.get("user_token"))
        projects_ok = len(Storage.data.get("projects", [])) > 0

        # Job name toggle + field
        box = layout.box()
        col = box.column()
        col.prop(props, "use_file_name", text="Use file name")
        sub = col.column()
        sub.active = not props.use_file_name
        sub.prop(props, "job_name", text="Job name")

        # Frame range controls (apply to Animation submissions)
        box = layout.box()
        col = box.column()
        col.prop(props, "use_scene_frame_range", text="Use scene frame range")

        sub = col.column()
        range_col = sub.column(align=True)
        if props.use_scene_frame_range:
            # Show actual Scene range in disabled fields
            sub.enabled = False
            range_col.prop(scene, "frame_start", text="Start")
            range_col.prop(scene, "frame_end", text="End")
            sub.prop(scene, "frame_step", text="Stepping")
        else:
            range_col.prop(props, "frame_start", text="Start")
            range_col.prop(props, "frame_end", text="End")
            sub.prop(props, "frame_stepping_size", text="Stepping")

        row = layout.row(align=True)
        row.prop(props, "image_format", text="Image format")

        # Submit buttons — same formatting as Download button (plain row)
        VIDEO_FORMATS = {"FFMPEG", "AVI_JPEG", "AVI_RAW"}
        effective_format = (
            scene.render.image_settings.file_format
            if props.image_format == "SCENE"
            else props.image_format
        )
        using_video_format = effective_format in VIDEO_FORMATS

        row = layout.row(align=True)
        row.enabled = logged_in and projects_ok and not using_video_format

        op_still = row.operator(
            "superluminal.submit_job", text="Submit Still", icon="RENDER_STILL"
        )
        op_still.mode = "STILL"

        op_anim = row.operator(
            "superluminal.submit_job", text="Submit Animation", icon="RENDER_ANIMATION"
        )
        op_anim.mode = "ANIMATION"

        # Other info/warnings (plain rows)
        if not logged_in:
            return

        if using_video_format:
            r = layout.row()
            r.alert = True  # make warning red
            if props.image_format == "SCENE":
                r.label(
                    text=f"Video formats not supported. Scene output is {scene.render.image_settings.file_format}.",
                    icon="ERROR",
                )
            else:
                r.label(
                    text=f"Video formats not supported ({effective_format}).",
                    icon="ERROR",
                )

        # Fixed-height unsaved-changes row (plain row)
        warn_row = layout.row()
        if bpy.data.is_dirty:
            warn_row.alert = True  # make warning red
            warn_row.label(
                text="Unsaved changes may not be included in the render job.",
                icon="ERROR",
            )
        else:
            warn_row.label(text="")  # placeholder keeps panel height stable


class SUPERLUMINAL_PT_UploadSettings(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_UploadSettings"
    bl_label = "Upload Settings"
    bl_parent_id = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        # Upload type selector (always visible)
        layout.prop(props, "upload_type", text="Upload type")

        # Cross-drive dependency warning (only relevant to Project uploads)
        if props.upload_type == "PROJECT":
            has_cross, summary = quick_cross_drive_hint()
            if not summary.blend_saved:
                info_row = layout.row()
                info_row.alert = True  # treat as warning for visibility
                info_row.label(
                    text="Save your .blend for accurate project root detection.",
                    icon="ERROR",
                )
            if has_cross:
                box = layout.box()
                box.alert = True  # make warning red
                box.label(
                    text="Some dependencies are on a different drive and are excluded from Project uploads.",
                    icon="ERROR",
                )
                box.label(
                    text="Move assets to the same drive, or switch upload type to Zip."
                )
                # show a few examples
                for p in summary.examples_other_roots(3):
                    box.label(text=human_shorten(p), icon="LIBRARY_DATA_BROKEN")
                if summary.cross_drive_count() > 3:
                    box.label(text=f"…and {summary.cross_drive_count() - 3} more")

        # Only show project-path options when 'Project' is selected
        if props.upload_type == "PROJECT":
            col = layout.column()
            col.prop(props, "automatic_project_path")

            sub = col.column()
            sub.active = not props.automatic_project_path
            sub.prop(props, "custom_project_path")

            # Warning if automatic is disabled but no custom path is set
            if not props.automatic_project_path:
                custom_path = str(props.custom_project_path or "").strip()
                if not custom_path:
                    warn_box = col.box()
                    warn_row = warn_box.row()
                    warn_row.alert = True
                    warn_row.label(text="Custom project path is empty. Turn on automatic project path or select a folder.", icon="ERROR")


class SUPERLUMINAL_PT_IncludeAddons(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_IncludeAddons"
    bl_label = "Include Enabled Addons"
    bl_parent_id = "SUPERLUMINAL_PT_UploadSettings"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        _read_addons_from_scene(context.scene)

        wm = context.window_manager
        _rebuild_enabled_addons_ui_cache(context)

        if len(wm.superluminal_ui_addons) == 0:
            layout.label(text="No add-ons enabled", icon="INFO")
            return

        # Scrollable list (built-in search + sort controls appear automatically,
        # and now work because SUPERLUMINAL_UL_addon_items implements filter_items).
        layout.template_list(
            "SUPERLUMINAL_UL_addon_items",
            "",
            wm,
            "superluminal_ui_addons",
            wm,
            "superluminal_ui_addons_index",
            rows=8,
        )


class SUPERLUMINAL_PT_RenderNode(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_RenderNode"
    bl_label = "Render Node Settings"
    bl_parent_id = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 20
    blender_version = get_blender_version_string()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        # Blender version (auto toggle + version enum)
        col = layout.column()
        col.prop(
            props,
            "auto_determine_blender_version",
            text=f"Use Current Blender Version [{self.blender_version}]",
        )
        sub = col.column()
        sub.active = not props.auto_determine_blender_version
        sub.prop(props, "blender_version", text="Blender Version")

        # col = col.column()
        # col.prop(props, "device_type", text="Device Type")


class SUPERLUMINAL_PT_RenderNode_Experimental(bpy.types.Panel):
    """Separate sub-panel to mirror native grouping."""

    bl_idname = "SUPERLUMINAL_PT_RenderNode_Experimental"
    bl_label = "Experimental"
    bl_parent_id = "SUPERLUMINAL_PT_RenderNode"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        col = layout.column()
        col.prop(props, "ignore_errors", text="Finish frame when errored")
        col.prop(props, "use_bserver", text="Persistence engine")
        col.prop(props, "use_async_upload", text="Async frame upload")


class SUPERLUMINAL_PT_Jobs(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_Jobs"
    bl_label = "Manage & Download"
    bl_parent_id = "SUPERLUMINAL_PT_RenderPanel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 30

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        scene = context.scene
        props = scene.superluminal_settings
        wm_props = scene.sulu_wm_settings
        prefs = context.preferences.addons[__package__].preferences

        refresh_jobs_collection(prefs)

        logged_in = bool(Storage.data.get("user_token"))
        jobs_ok = len(Storage.data.get("jobs", {})) > 0

        tools = layout.row(align=True)
        tools.use_property_split = False
        tools.use_property_decorate = False
        tools.separator_spacer()
        tools.prop(wm_props, "live_job_updates", text="Auto refresh")
        tools.operator("superluminal.fetch_project_jobs", text="", icon="FILE_REFRESH")
        tools.separator()
        tools.menu("SUPERLUMINAL_MT_job_columns", text="", icon="DOWNARROW_HLT")

        last_refresh = float(Storage.panel_data.get("last_jobs_refresh_at", 0.0) or 0.0)
        refresh_err = str(Storage.panel_data.get("jobs_refresh_error", "") or "").strip()
        if refresh_err:
            warn = layout.row()
            warn.alert = True
            warn.label(text=f"Refresh error: {refresh_err}", icon="ERROR")
        elif last_refresh > 0:
            stamp = time.strftime("%H:%M:%S", time.localtime(last_refresh))
            info = layout.row()
            info.label(text=f"Last refreshed: {stamp}", icon="INFO")

        refresh_icon, refresh_text = _refresh_service_status()
        if (
            refresh_text
            and logged_in
            and _should_show_refresh_state(jobs_refresh_error=refresh_err)
        ):
            info = layout.row()
            if refresh_icon == "ERROR":
                info.alert = True
            info.label(text=refresh_text, icon=refresh_icon)

        col = layout.column()
        col.enabled = logged_in and jobs_ok
        draw_header_row(col, prefs)

        if not logged_in or not jobs_ok:
            box = col.box()
            if not logged_in:
                box.alert = True
                box.label(text="Sign in to see your jobs.", icon="ERROR")
            elif not jobs_ok:
                box.label(text="No jobs found in selected project.", icon="INFO")
            return

        col.template_list(
            "SUPERLUMINAL_UL_job_items",
            "",
            prefs,
            "jobs",
            prefs,
            "active_job_index",
            rows=3,
        )

        # Determine selected job
        projects = Storage.data.get("projects", [])
        selected_project = next(
            (p for p in projects if p.get("id") == prefs.project_id), None
        )
        selected_project_jobs = (
            [
                j
                for j in Storage.data.get("jobs", {}).values()
                if j.get("project_id") == selected_project.get("id")
            ]
            if selected_project
            else []
        )

        job_id, job_name, job_status = "", "", ""
        if selected_project_jobs and 0 <= prefs.active_job_index < len(
            selected_project_jobs
        ):
            sel_job = selected_project_jobs[prefs.active_job_index]
            job_id = sel_job.get("id", "")
            job_name = sel_job.get("name", "")
            job_status = sel_job.get("status", "")

        has_selection = logged_in and jobs_ok and bool(job_name) and job_id != ""

        # Selected job context box
        box = layout.box()
        box.enabled = has_selection

        if has_selection:
            header = box.row(align=True)
            status_icon_id = get_icon_id(job_status.upper())
            status_text = format_job_status(job_status)
            title_text = f"{job_name} | {status_text}"
            if status_icon_id:
                header.label(text=title_text, icon_value=status_icon_id)
            else:
                header.label(text=title_text, icon=get_fallback_icon(job_status))
            op = header.operator(
                "superluminal.open_browser",
                text="",
                icon="URL",
            )
            op.job_id = job_id
            op.project_id = prefs.project_id
        else:
            header = box.row(align=True)
            header.label(text="No job selected", icon="BLANK1")

        # Download section inside the box
        box.prop(props, "download_path", text="Download path")

        op2 = box.operator(
            "superluminal.download_job", text="Download job output", icon="IMPORT"
        )
        op2.job_id = job_id
        op2.job_name = job_name


classes = (
    ToggleAddonSelectionOperator,
    SUPERLUMINAL_PG_AddonItem,
    SUPERLUMINAL_UL_addon_items,
    SUPERLUMINAL_PT_RenderPanel,
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

    # UI-only cache for the scrollable list (don’t save into .blend)
    bpy.types.WindowManager.superluminal_ui_addons = bpy.props.CollectionProperty(
        type=SUPERLUMINAL_PG_AddonItem,
        options={"SKIP_SAVE"},
    )
    bpy.types.WindowManager.superluminal_ui_addons_index = bpy.props.IntProperty(
        default=0,
        options={"SKIP_SAVE"},
    )


def unregister():
    # Remove WM properties first
    if hasattr(bpy.types.WindowManager, "superluminal_ui_addons"):
        del bpy.types.WindowManager.superluminal_ui_addons
    if hasattr(bpy.types.WindowManager, "superluminal_ui_addons_index"):
        del bpy.types.WindowManager.superluminal_ui_addons_index

    from bpy.utils import unregister_class

    for cls in reversed(classes):
        unregister_class(cls)
