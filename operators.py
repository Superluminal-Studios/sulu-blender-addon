import bpy
import json
import requests

from .preferences import g_project_items, g_job_items
from .constants import POCKETBASE_URL

# -------------------------------------------------------------------
#  Authentication
# -------------------------------------------------------------------
class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Authenticate with PocketBase and store token."""
    bl_idname = "superluminal.login"
    bl_label = "Log in to Superluminal"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        auth_url = f"{POCKETBASE_URL}/api/collections/users/auth-with-password"
        payload  = {"identity": prefs.username, "password": prefs.password}

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
        self.report({"INFO"}, "Logged in successfully.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_Logout(bpy.types.Operator):
    """Clear the stored PocketBase token."""
    bl_idname = "superluminal.logout"
    bl_label = "Log out of Superluminal"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        prefs.user_token = ""
        self.report({"INFO"}, "Logged out.")
        return {"FINISHED"}


# -------------------------------------------------------------------
#  Project list utilities
# -------------------------------------------------------------------
class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Fetch PocketBase project list and cache it permanently."""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        if not prefs.user_token:
            self.report({"ERROR"}, "Not authenticated—log in first.")
            return {"CANCELLED"}

        projects_url = f"{POCKETBASE_URL}/api/collections/projects/records"
        headers      = {"Authorization": prefs.user_token}

        try:
            response = requests.get(projects_url, headers=headers, timeout=10)
            response.raise_for_status()
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching projects: {exc}")
            return {"CANCELLED"}

        fetched_items = [
            (
                proj.get("id", ""),
                proj.get("name", proj.get("id", "")),
                f"Project {proj.get('name', '')}",
            )
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
    """Fetch PocketBase job list for the active project and cache it."""
    bl_idname = "superluminal.fetch_project_jobs"
    bl_label = "Fetch Project Jobs"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        if not prefs.user_token:
            self.report({"ERROR"}, "Not authenticated—log in first.")
            return {"CANCELLED"}

        project_id = prefs.project_list
        if not project_id:
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        # ---------------------------------------------------------- #
        #  Resolve organisation ID – first grab that project record
        # ---------------------------------------------------------- #
        try:
            proj_resp = requests.get(
                f"{POCKETBASE_URL}/api/collections/projects/records",
                headers={"Authorization": prefs.user_token},
                params={"filter": f"(id='{project_id}')"},
                timeout=30,
            )
            proj_resp.raise_for_status()
            proj = proj_resp.json()["items"][0]
            org_id = proj["organization_id"]
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching project info: {exc}")
            return {"CANCELLED"}

        # ---------------------------------------------------------- #
        #  Look up the user-key for that org’s render queue
        # ---------------------------------------------------------- #
        try:
            rq_resp = requests.get(
                f"{POCKETBASE_URL}/api/collections/render_queues/records",
                headers={"Authorization": prefs.user_token},
                params={"filter": f"(organization_id='{org_id}')"},
                timeout=30,
            )

            
            rq_resp.raise_for_status()
            user_key = rq_resp.json()["items"][0]["user_key"]
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching render queue: {exc}")
            return {"CANCELLED"}

        # ---------------------------------------------------------- #
        #  Finally fetch the jobs from the farm
        # ---------------------------------------------------------- #
        try:
            jobs_url = f"{POCKETBASE_URL}/farm/{org_id}/api/job_list"
            jobs_resp = requests.get(jobs_url, headers={"Auth-Token": user_key}, timeout=10)
            jobs_resp.raise_for_status()
            jobs = jobs_resp.json()
            
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching jobs: {exc}")
            return {"CANCELLED"}

        g_job_items.clear()
        g_job_items.extend(
            (job_id, data.get("name", job_id), data.get("name", job_id))
            for job_id, data in jobs.get("body", {}).items() if prefs.project_list == data.get("project_id")
        )

        # Make the first entry the current selection (optional)
        if g_job_items:
            context.scene.superluminal_settings.job_id = g_job_items[0][0]

        # Force UI refresh so the Properties-editor redraws immediately
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

# Extra poll functions for the *existing* Submit/Download operators
def _submit_poll(cls, context):
    """Submit allowed only when logged in *and* a project exists."""
    prefs = context.preferences.addons[__package__].preferences
    logged_in = bool(prefs.user_token)
    projects_ok = any(item[0] not in {"", "NONE"} for item in g_project_items)
    return logged_in and projects_ok

def _download_poll(cls, context):
    """Download allowed only when logged in *and* jobs exist."""
    prefs = context.preferences.addons[__package__].preferences
    logged_in = bool(prefs.user_token)
    jobs_ok = any(item[0] not in {"", "NONE"} for item in g_job_items)
    return logged_in and jobs_ok


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Patch poll functions if the target operators are registered
    sub_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")
    if sub_cls:
        sub_cls.poll = classmethod(_submit_poll)

    dl_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")
    if dl_cls:
        dl_cls.poll = classmethod(_download_poll)


def unregister():
    # Restore default polls (optional)
    sub_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")
    if sub_cls and sub_cls.poll is _submit_poll:
        del sub_cls.poll

    dl_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")
    if dl_cls and dl_cls.poll is _download_poll:
        del dl_cls.poll

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)