# ─── preferences.py ───────────────────────────────────────────
import bpy
from .storage            import Storage
from .utils.date_utils   import format_submitted   # ← your helper
from .icons import preview_collections

print(preview_collections)


STATUS_ICONS = {
    "queued":   preview_collections["main"].get("QUEUED").icon_id,
    "running":  preview_collections["main"].get("RUNNING").icon_id,
    "finished": preview_collections["main"].get("FINISHED").icon_id,
    "error":    preview_collections["main"].get("ERROR").icon_id,
    "paused":   preview_collections["main"].get("PAUSED").icon_id,
}

# ╭──────────────────  Helpers  ───────────────────────────────╮
def get_project_items(self, context):
    Storage.load()
    return [(p["id"], p["name"], p["name"]) for p in Storage.data["projects"]]

#  (Enum fallback still allowed elsewhere in the add-on if you need it)
def get_job_items(self, context):
    Storage.load()
    return [(jid, j["name"], j["name"]) for jid, j in Storage.data["jobs"].items()]

def refresh_jobs_collection(prefs):
    """Sync prefs.jobs ←→ Storage.data['jobs'] and format fields."""
    Storage.load()
    prefs.jobs.clear()

    for jid, job in Storage.data["jobs"].items():
        it = prefs.jobs.add()
        it.id               = jid
        it.name             = job.get("name", "")
        it.status           = job.get("status", "")
        it.submission_time  = format_submitted(job.get("submit_time"))
        it.started_time     = format_submitted(job.get("start_time"))
        it.finished_time    = format_submitted(job.get("end_time"))
        it.start_frame      = job.get("start", 0)
        it.end_frame        = job.get("end",   0)
        it.progress         = job.get("tasks", {}).get("finished", 0) / job.get("total_tasks", 1)
        it.finished_frames  = job.get("tasks", {}).get("finished", 0)
        it.blender_version  = job.get("blender_version", "")
        it.type             = "Zip" if job.get("zip", True) else "Project"
        it.icon             = STATUS_ICONS.get(job.get("status", ""), "FILE_FOLDER")

# ╭──────────────────  Data container  ────────────────────────╮
class SuperluminalJobItem(bpy.types.PropertyGroup):
    id:               bpy.props.StringProperty()
    name:             bpy.props.StringProperty()
    status:           bpy.props.StringProperty()
    submission_time:  bpy.props.StringProperty()
    started_time:     bpy.props.StringProperty()
    finished_time:    bpy.props.StringProperty()
    start_frame:      bpy.props.IntProperty()
    end_frame:        bpy.props.IntProperty()
    progress:         bpy.props.FloatProperty(subtype='FACTOR', min=0.0, max=1.0)
    finished_frames:  bpy.props.IntProperty()
    blender_version:  bpy.props.StringProperty()
    type:             bpy.props.StringProperty()

# ╭──────────────────  Column toggle menu  ────────────────────╮
class SUPERLUMINAL_MT_job_columns(bpy.types.Menu):
    bl_label = "Columns"
    cols = (
        ("show_col_name",            "Name"),
        ("show_col_status",          "Status"),
        ("show_col_submission_time", "Submitted"),
        ("show_col_started_time",    "Started"),
        ("show_col_finished_time",   "Finished"),
        ("show_col_start_frame",     "Start Frame"),
        ("show_col_end_frame",       "End Frame"),
        ("show_col_progress",        "Progress"),
        ("show_col_finished_frames", "Finished Frames"),
        ("show_col_blender_version", "Blender Ver."),
        ("show_col_type",            "Type"),
    )

    def draw(self, context):
        prefs = context.preferences.addons[__package__].preferences
        layout = self.layout
        for attr, label in self.cols:
            layout.prop(prefs, attr, text=label)

# ╭──────────────────  UIList  ────────────────────────────────╮
class SUPERLUMINAL_UL_job_items(bpy.types.UIList):
    """List of render jobs with user-selectable columns."""
    order = [                        # draw order
        "name", "status", "submission_time", "started_time", "finished_time",
        "start_frame", "end_frame", "progress", "finished_frames",
        "blender_version", "type",
    ]

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        prefs = context.preferences.addons[__package__].preferences

        # ---- Header row -----------------------------------------------------
        if index == -1:                       # -1 is header
            for key in self.order:
                if getattr(prefs, f"show_col_{key}"):
                    text = key.replace("_", " ").title()
                    layout.label(text=text if key != "progress" else "Prog.")
            layout.menu("SUPERLUMINAL_MT_job_columns", icon='DOWNARROW_HLT', text="")
            return

        # ---- Data rows ------------------------------------------------------
        row = layout.row(align=True)
        if prefs.show_col_name:            row.label(text=item.name,   icon_value=STATUS_ICONS.get(item.status, "FILE_FOLDER"))
        if prefs.show_col_start_frame:     row.label(text=str(item.start_frame))
        if prefs.show_col_end_frame:       row.label(text=str(item.end_frame))
        if prefs.show_col_finished_frames: row.label(text=str(item.finished_frames))
        if prefs.show_col_blender_version: row.label(text=item.blender_version)
        if prefs.show_col_type:            row.label(text=item.type)
        if prefs.show_col_submission_time: row.label(text=item.submission_time)
        if prefs.show_col_started_time:    row.label(text=item.started_time)
        if prefs.show_col_finished_time:   row.label(text=item.finished_time)
        if prefs.show_col_status:          row.label(text=item.status)
        if prefs.show_col_progress:        row.prop(item, "progress", text="")

# ╭──────────────────  Add-on preferences  ───────────────────╮
class SuperluminalAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # ▸ credentials / project picker
    username: bpy.props.StringProperty(name="Username")
    password: bpy.props.StringProperty(name="Password", subtype="PASSWORD")
    project_id: bpy.props.EnumProperty(name="Project", items=get_project_items)
    job_id:     bpy.props.EnumProperty(name="Job (legacy)", items=get_job_items)

    # ▸ job table
    jobs:             bpy.props.CollectionProperty(type=SuperluminalJobItem)
    active_job_index: bpy.props.IntProperty()

    # ▸ column visibility toggles (all default-on)
    show_col_name:            bpy.props.BoolProperty(default=True)
    show_col_status:          bpy.props.BoolProperty(default=False)
    show_col_submission_time: bpy.props.BoolProperty(default=True)
    show_col_started_time:    bpy.props.BoolProperty(default=False)
    show_col_finished_time:   bpy.props.BoolProperty(default=False)
    show_col_start_frame:     bpy.props.BoolProperty(default=False)
    show_col_end_frame:       bpy.props.BoolProperty(default=False)
    show_col_progress:        bpy.props.BoolProperty(default=True)
    show_col_finished_frames: bpy.props.BoolProperty(default=False)
    show_col_blender_version: bpy.props.BoolProperty(default=False)
    show_col_type:            bpy.props.BoolProperty(default=False)

    # ▸ UI
    def draw(self, context):
        layout = self.layout
        Storage.load()
        if Storage.data["user_token"]:
            layout.operator("superluminal.logout", text="Log out")
        else:
            layout.prop(self, "username")
            layout.prop(self, "password")
            layout.operator("superluminal.login", text="Log in")

# ╭──────────────────  Register helpers  ─────────────────────╮
classes = (
    SuperluminalJobItem,
    SUPERLUMINAL_MT_job_columns,
    SUPERLUMINAL_UL_job_items,
    SuperluminalAddonPreferences,
)

def register():
    from bpy.utils import register_class
    for c in classes:
        register_class(c)

def unregister():
    from bpy.utils import unregister_class
    for c in reversed(classes):
        unregister_class(c)
