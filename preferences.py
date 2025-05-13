import bpy
import json

# -------------------------------------------------------------------
#  Global cache for dynamic project list
# -------------------------------------------------------------------
g_project_items = []

g_job_items: list[tuple[str, str, str]] = [
    # ("NONE", "Not Loaded", "Run “Fetch Project Jobs” first")
]

def get_job_items(self, context):
    """Dynamic enum callback for Scene.superluminal_settings.job_id"""
    if not g_job_items:           # never return an empty list
        # return [("NONE", "Not Loaded", "Run “Fetch Project Jobs” first")]
        return []
    return g_job_items

def ensure_cached_project_items(prefs):
    """Populate g_project_items from prefs.stored_projects once per session."""
    global g_project_items
    # if (not g_project_items):
    #     try:
    #         cached = json.loads(prefs.stored_projects)
    #         g_project_items.clear()
    #         g_project_items.extend([tuple(t) for t in cached])
    #     except Exception:
    #         # Corrupt cache—reset
    #         prefs.stored_projects = ""

def get_project_list_items(self, context):
    ensure_cached_project_items(self)
    return g_project_items



class SuperluminalAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__  # MUST match add‑on folder name

    # ----------------------------------------------------------------
    #  Stored properties
    # ----------------------------------------------------------------
    pocketbase_url: bpy.props.StringProperty(
        name="PocketBase URL",
        default="https://api.superlumin.al",
    )
    username: bpy.props.StringProperty(name="Username")
    password: bpy.props.StringProperty(name="Password", subtype="PASSWORD")
    user_token: bpy.props.StringProperty(name="User Token")
    stored_projects: bpy.props.StringProperty(
        name="Cached Projects (JSON)", options={'HIDDEN'}
    )
    project_list: bpy.props.EnumProperty(
        name="Project",
        items=get_project_list_items,
    )

    # ----------------------------------------------------------------
    #  UI
    # ----------------------------------------------------------------
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pocketbase_url")

        if self.user_token:
            # Logged in – hide creds, show Log out
            layout.operator("superluminal.logout", text="Log out")
        else:
            # Not logged in – show creds & Log in
            layout.prop(self, "username")
            layout.prop(self, "password")
            layout.operator("superluminal.login", text="Log in")


# -------------------------------------------------------------------
#  Registration helpers
# -------------------------------------------------------------------

def register():
    bpy.utils.register_class(SuperluminalAddonPreferences)


def unregister():
    bpy.utils.unregister_class(SuperluminalAddonPreferences)
