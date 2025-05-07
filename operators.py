import bpy
import json
import requests

from .preferences import g_project_items, g_job_items


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


class SUPERLUMINAL_OT_FetchProjectJobs(bpy.types.Operator):
    """Fetch PocketBase project list and cache it permanently."""
    bl_idname = "superluminal.fetch_project_jobs"
    bl_label = "Fetch Project Jobs"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        if not prefs.user_token:
            self.report({"ERROR"}, "Not authenticated—log in first.")
            return {"CANCELLED"}
        
        project_id = prefs.project_list

        proj = requests.get(
            f"{prefs.pocketbase_url}/api/collections/projects/records",
            headers={"Authorization": prefs.user_token},
            params={"filter": f"(id='{project_id}')"},
            timeout=30,
        ).json()["items"][0]

        org_id = proj["organization_id"]

        render_queue_url = f"{prefs.pocketbase_url}/api/collections/render_queues/records"
        headers = {"Authorization": prefs.user_token}
        params = {"filter": f"(organization_id='{org_id}')"}
        response = requests.get(render_queue_url, headers=headers, params=params, timeout=30).json()

        user_key = response["items"][0]["user_key"]

        jobs_url = f"{prefs.pocketbase_url}/farm/{org_id}/api/job_list"
        headers = {"Auth-Token": user_key}

        try:
            response = requests.get(jobs_url, headers=headers, timeout=10)
            response.raise_for_status()
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching jobs: {exc}")
            return {"CANCELLED"}
        
        jobs = response.json()

        g_job_items.clear()
        g_job_items.extend(
            (job_id, job_data.get("name", job_id), job_data.get("name", job_id))
            for job_id, job_data in jobs.get("body", {}).items()
        )

        # (optional) make the first entry the current selection
        if g_job_items:
            context.scene.superluminal_settings.job_id = g_job_items[0][0]

        # force UI refresh so the Properties editor redraws immediately
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
        return {"FINISHED"}

# -------------------------------------------------------------------
#  Registration helpers
# -------------------------------------------------------------------

classes = (
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_Logout,
    SUPERLUMINAL_OT_FetchProjects,
    SUPERLUMINAL_OT_FetchProjectJobs,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
