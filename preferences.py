import bpy
from .storage            import Storage
from .utils.date_utils   import format_submitted
from .icons              import preview_collections

COLUMN_ORDER = [
    "name",
    "status",
    "submission_time",
    "started_time",
    "finished_time",
    "start_frame",
    "end_frame",
    "progress",
    "finished_frames",
    "blender_version",
    "type",
]


STATUS_ICONS = {
    "queued":   preview_collections["main"].get("QUEUED").icon_id,
    "running":  preview_collections["main"].get("RUNNING").icon_id,
    "finished": preview_collections["main"].get("FINISHED").icon_id,
    "error":    preview_collections["main"].get("ERROR").icon_id,
    "paused":   preview_collections["main"].get("PAUSED").icon_id,
}

def get_project_items(self, context):
    return [(p["id"], p["name"], p["name"]) for p in Storage.data["projects"]]


def get_job_items(self, context):
    return [(jid, j["name"], j["name"]) for jid, j in Storage.data["jobs"].items()]


def draw_header_row(layout, prefs):
    """
    Draw a header row with the same enabled columns and labels that
    SUPERLUMINAL_UL_job_items uses internally.
    """
    row = layout.row(align=True)
    row.scale_y = 0.6

    for key in COLUMN_ORDER:
        if getattr(prefs, f"show_col_{key}"):
            box = row.box()
            label = "Prog." if key == "progress" else key.replace("_", " ").title()
            box.label(text=label)


def refresh_jobs_collection(prefs):
    """Sync prefs.jobs ←→ Storage.data['jobs'] and format fields."""
    prefs.jobs.clear()

    if not Storage.data["projects"]:
        return

    selected_project =  [p for p in Storage.data["projects"] if p["id"] == prefs.project_id][0]

    for jid, job in Storage.data["jobs"].items():
        if job.get("project_id") != selected_project.get("id"):
            continue

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


class SUPERLUMINAL_MT_job_columns(bpy.types.Menu):
    bl_label = "Columns"
    cols = (  # order MUST match COLUMN_ORDER
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


class SUPERLUMINAL_UL_job_items(bpy.types.UIList):
    """List of render jobs with user-selectable columns."""
    order = COLUMN_ORDER  # single source-of-truth for column order

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        prefs = context.preferences.addons[__package__].preferences

        # ---- Header row -----------------------------------------------------
        if index == -1: 
            for key in self.order:
                if getattr(prefs, f"show_col_{key}"):
                    text = "Prog." if key == "progress" else key.replace("_", " ").title()
                    layout.label(text=text)
            layout.menu("SUPERLUMINAL_MT_job_columns", icon='DOWNARROW_HLT', text="")
            return

        # ---- Data rows ------------------------------------------------------
        enabled_cols = [k for k in self.order if getattr(prefs, f"show_col_{k}")]
        cols = layout.column_flow(columns=len(enabled_cols))

        for key in self.order:
            if not getattr(prefs, f"show_col_{key}"):
                continue

            if key == "name":
                cols.label(text=item.name, icon_value=STATUS_ICONS.get(item.status, "FILE_FOLDER"))
            elif key == "status":
                cols.label(text=item.status)
            elif key == "submission_time":
                cols.label(text=item.submission_time)
            elif key == "started_time":
                cols.label(text=item.started_time)
            elif key == "finished_time":
                cols.label(text=item.finished_time)
            elif key == "start_frame":
                cols.label(text=str(item.start_frame))
            elif key == "end_frame":
                cols.label(text=str(item.end_frame))
            elif key == "progress":
                cols.progress(factor=item.progress, type='BAR', text=f"{item.progress * 100:.0f}%")
            elif key == "finished_frames":
                cols.label(text=str(item.finished_frames))
            elif key == "blender_version":
                cols.label(text=item.blender_version)
            elif key == "type":
                cols.label(text=item.type)




def draw_login(layout):
    # Already authenticated?
    if Storage.data.get("user_token"):
        layout.operator("superluminal.logout", text="Log out")
        return

    # 1) Sign in with browser (primary action)
    layout.operator(
        "superluminal.login_browser",
        text="Connect to Superluminal",
        icon_value=preview_collections["main"].get("SULU").icon_id,
    )

    # 2) Collapsible password login (closed by default)
    prefs = bpy.context.preferences.addons[__package__].preferences
    layout.separator()

    header = layout.row(align=True)
    icon = 'TRIA_DOWN' if getattr(prefs, "show_password_login", False) else 'TRIA_RIGHT'
    header.prop(prefs, "show_password_login", text="", icon=icon, emboss=False)
    header.label(text="Sign in with password")

    if not getattr(prefs, "show_password_login", False):
        return 

    # Expanded → draw boxed credentials
    wm = bpy.context.window_manager
    creds = getattr(wm, "sulu_wm", None)
    if creds is None:
        col = layout.column()
        col.label(text="Internal error: auth props not registered.", icon='ERROR')
        return

    box = layout.box()
    box.prop(creds, "username", text="Email")
    box.prop(creds, "password", text="Password")
    box.operator("superluminal.login", text="Log in")



class SuperluminalAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__


    project_id: bpy.props.EnumProperty(name="Project", items=get_project_items)


    jobs:             bpy.props.CollectionProperty(type=SuperluminalJobItem)
    active_job_index: bpy.props.IntProperty()


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


    show_password_login: bpy.props.BoolProperty(
        name="Show password sign-in",
        description="Reveal email/password login fields",
        default=False,                 # closed by default
        options={'SKIP_SAVE'},         # don't persist across sessions
    )


    def draw(self, context):
        layout = self.layout
        draw_login(layout)


classes = (
    SuperluminalJobItem,
    SUPERLUMINAL_MT_job_columns,
    SUPERLUMINAL_UL_job_items := SUPERLUMINAL_UL_job_items,  # keep stable name in bpy
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
