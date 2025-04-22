import bpy
import json
import requests

from .preferences import g_project_items, ensure_cached_project_items


# -------------------------------------------------------------------
#  Authentication
# -------------------------------------------------------------------

class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Authenticate with PocketBase and store token."""
    bl_idname = "superluminal.login"
    bl_label = "Log in to PocketBase"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        auth_url = f"{prefs.pocketbase_url}/api/collections/users/auth-with-password"
        payload = {"identity": prefs.username, "password": prefs.password}

        try:
            response = requests.post(auth_url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as exc:
            self.report({"ERROR"}, f"Error logging in: {exc}")
            return {"CANCELLED"}

        token = response.json().get("token")
        if not token:
            self.report({"WARNING"}, "Login succeeded but no token was returned.")
            return {"CANCELLED"}

        prefs.user_token = token
        self.report({"INFO"}, "Logged in successfully.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_Logout(bpy.types.Operator):
    """Clear the stored PocketBase token."""
    bl_idname = "superluminal.logout"
    bl_label = "Log out"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        prefs.user_token = ""
        self.report({"INFO"}, "Logged out.")
        return {"FINISHED"}


# -------------------------------------------------------------------
#  Project list
# -------------------------------------------------------------------

class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Fetch PocketBase project list and cache it permanently."""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        if not prefs.user_token:
            self.report({"ERROR"}, "Not authenticated—log in first.")
            return {"CANCELLED"}

        projects_url = f"{prefs.pocketbase_url}/api/collections/projects/records"
        headers = {"Authorization": prefs.user_token}

        try:
            response = requests.get(projects_url, headers=headers, timeout=10)
            response.raise_for_status()
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching projects: {exc}")
            return {"CANCELLED"}

        fetched_items = [
            (proj.get("id", ""), proj.get("name", proj.get("id", "")), f"Project {proj.get('name', '')}")
            for proj in response.json().get("items", [])
        ]

        if not fetched_items:
            fetched_items = [("NONE", "No projects", "No projects")]

        g_project_items.clear()
        g_project_items.extend(fetched_items)
        prefs.stored_projects = json.dumps([list(t) for t in fetched_items])

        self.report({"INFO"}, "Projects fetched.")
        return {"FINISHED"}


# -------------------------------------------------------------------
#  Registration helpers
# -------------------------------------------------------------------

classes = (
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_Logout,
    SUPERLUMINAL_OT_FetchProjects,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
