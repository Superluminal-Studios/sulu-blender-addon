import bpy
import requests

class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Authenticate using PocketBase credentials."""
    bl_idname = "superluminal.login"
    bl_label = "Login to PocketBase"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        auth_url = f"{prefs.pocketbase_url}/api/collections/users/auth-with-password"
        payload = {"identity": prefs.username, "password": prefs.password}

        try:
            response = requests.post(auth_url, json=payload)
            response.raise_for_status()
        except Exception as e:
            self.report({"ERROR"}, f"Error logging in: {str(e)}")
            return {"CANCELLED"}

        data = response.json()
        if "token" in data:
            prefs.user_token = data["token"]
            self.report({"INFO"}, "Logged in successfully!")
        else:
            self.report({"WARNING"}, "Login response did not contain a token.")

        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Fetch the list of available projects from PocketBase."""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        projects_url = f"{prefs.pocketbase_url}/api/collections/projects/records"
        headers = {"Authorization": f"{prefs.user_token}"}

        try:
            response = requests.get(projects_url, headers=headers)
            response.raise_for_status()
        except Exception as e:
            self.report({"ERROR"}, f"Error fetching projects: {str(e)}")
            return {"CANCELLED"}

        data = response.json()
        from .preferences import g_project_items
        local_items = []
        if "items" in data:
            for project in data["items"]:
                project_id = project.get("id", "")
                project_name = project.get("name", project_id)
                local_items.append(
                    (project_id, project_name, f"Project {project_name}")
                )

        if not local_items:
            local_items = [("NONE", "No projects", "No projects")]

        g_project_items.clear()
        g_project_items.extend(local_items)

        self.report({"INFO"}, "Projects fetched successfully.")
        return {"FINISHED"}
    

classes = (
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_FetchProjects,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)