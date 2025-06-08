import bpy
import json
from .storage import Storage


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


# -------------------------------------------------------------------
#  Registration helpers
# -------------------------------------------------------------------
def register():
    bpy.utils.register_class(SuperluminalAddonPreferences)


def unregister():
    bpy.utils.unregister_class(SuperluminalAddonPreferences)