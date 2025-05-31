import bpy
import json

# -------------------------------------------------------------------
#  Global caches
# -------------------------------------------------------------------
g_project_items: list[tuple[str, str, str]] = []
g_job_items:     list[tuple[str, str, str]] = []

# -------------------------------------------------------------------
#  Helpers
# -------------------------------------------------------------------
def get_job_items(self, context):
    """Dynamic enum callback for Scene.superluminal_settings.job_id"""
    # Never return an empty list – that breaks the Enum UI – just return [].
    return g_job_items if g_job_items else []

def ensure_cached_project_items(prefs: "SuperluminalAddonPreferences"):
    """Populate g_project_items from prefs.stored_projects once per session."""
    global g_project_items

    if g_project_items:        # already cached
        return

    try:
        cached = json.loads(prefs.stored_projects)
        g_project_items.extend([tuple(t) for t in cached if isinstance(t, (list, tuple)) and len(t) >= 3])
    except Exception:
        # Corrupt cache—reset
        prefs.stored_projects = ""

def get_project_list_items(self, context):
    ensure_cached_project_items(self)
    # If nothing cached yet, return an empty list so the drop-down is blank/disabled
    return g_project_items

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
    user_token: bpy.props.StringProperty(name="User Token")
    stored_projects: bpy.props.StringProperty(
        name="Cached Projects (JSON)", options={'HIDDEN'},
    )
    project_list: bpy.props.EnumProperty(
        name="Project",
        items=get_project_list_items,
        description="Select the Superluminal project to submit your render job to.",
    )

    # ----------------------------------------------------------------
    #  UI
    # ----------------------------------------------------------------
    def draw(self, context):
        layout = self.layout
        # layout.prop(self, "pocketbase_url")

        if self.user_token:
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