import bpy
import json
from .storage import Storage
from .utils.date_utils import format_submitted
def get_project_items(self, context):
    # get projects from the stored json in storage
    projects = Storage.data["projects"]
    if not projects:
        return []
    
    projects = [(project["id"], project["name"], project["name"]) for project in projects]

    return projects

def get_job_items(self, context):
    # get jobs from the stored json in storage
    jobs = Storage.data["jobs"]
    if not jobs:
        return []

    jobs = [
        (job_id, job["name"], job["name"])
        for job_id, job in jobs.items()
    ]
    
    return jobs

def refresh_jobs_collection(prefs):
    """Sync prefs.jobs ↔ Storage.data['jobs']."""
    Storage.load()
    prefs.jobs.clear()
    for job_id, job in Storage.data["jobs"].items():
        item = prefs.jobs.add()
        item.id              = job_id
        item.name            = job["name"]
        item.status          = job.get("status", "unknown")
        item.submission_time = format_submitted(job.get("submit_time", 0))

class SUPERLUMINAL_UL_job_items(bpy.types.UIList):
    """Shows name • status • submission time in three columns"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon='RENDER_RESULT')
        row.label(text=item.status)
        row.label(text=item.submission_time)


class SuperluminalJobItem(bpy.types.PropertyGroup):
    id:              bpy.props.StringProperty()      # PocketBase ID
    name:            bpy.props.StringProperty()
    submission_time: bpy.props.StringProperty()      # ISO string or localised
    status:          bpy.props.StringProperty()      # queued / running / done …


# -------------------------------------------------------------------
#  Preferences
# -------------------------------------------------------------------
class SuperluminalAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__  # MUST match add-on folder name

    # ----------------------------------------------------------------
    #  Stored properties
    # ----------------------------------------------------------------
    username: bpy.props.StringProperty(name="Username")
    password: bpy.props.StringProperty(name="Password", subtype="PASSWORD")
    
    project_id: bpy.props.EnumProperty(
        name="Project",
        items=get_project_items,
        description="Select the Superluminal project to submit your render job to.",
    )

    job_id: bpy.props.EnumProperty(
        name="Job",
        items=get_job_items,
        description="Select the job to download the rendered frames from.",
    )

    jobs:              bpy.props.CollectionProperty(type=SuperluminalJobItem)
    active_job_index:  bpy.props.IntProperty()   # keeps selection in UIList


    # ----------------------------------------------------------------
    #  UI
    # ----------------------------------------------------------------
    def draw(self, context):
        layout = self.layout
        # layout.prop(self, "pocketbase_url")
        Storage.load()
        if Storage.data["user_token"]:
            # Logged in – hide creds, show Log out
            layout.operator("superluminal.logout", text="Log out")
        else:
            # Not logged in – show creds & Log in
            layout.prop(self, "username")
            layout.prop(self, "password")
            layout.operator("superluminal.login", text="Log in")


classes = (
    SuperluminalJobItem,          # 1  ← must be first
    SUPERLUMINAL_UL_job_items,    # 2  (order doesn’t matter for UIList)
    SuperluminalAddonPreferences, # 3  ← can only be registered after 1
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)