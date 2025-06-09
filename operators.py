from __future__ import annotations

import json
import bpy

from .constants import POCKETBASE_URL
from .pocketbase_auth import NotAuthenticated
from .storage import Storage
from .utils.request_utils import fetch_projects, get_render_queue_key, fetch_jobs
from .utils.logging import report_exception
from operator import setitem

# -----------------------------------------------------------------------------
#  Authentication
# -----------------------------------------------------------------------------
class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Sign in to Superluminal"""

    bl_idname = "superluminal.login"
    bl_label = "Log in to Superluminal"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        url   = f"{POCKETBASE_URL}/api/collections/users/auth-with-password"
        data  = {"identity": prefs.username, "password": prefs.password}

        # --- 0) authenticate -------------------------------------------------
        try:
            r = Storage.session.post(url, json=data, timeout=Storage.timeout)
            r.raise_for_status()
            if not (token := r.json().get("token")):
                self.report({"WARNING"}, "Login succeeded but no token returned.")
                return {"CANCELLED"}
            Storage.data["user_token"] = token
        except Exception as exc:
            return report_exception(self, exc, "Login failed")

        # --- 1) projects -----------------------------------------------------
        try:
            projects = fetch_projects()
        except Exception as exc:
            self.report({"WARNING"}, f"Logged in but could not fetch projects: {exc}")

        if projects:
            Storage.data["projects"] = projects
            project = projects[0]
            prefs.project_id = project["id"]
            org_id = project["organization_id"]

            try:
                user_key = get_render_queue_key(org_id)

                Storage.data["org_id"] = org_id
                Storage.data["user_key"] = user_key

                jobs = fetch_jobs(org_id, user_key, prefs.project_id)
                Storage.data["jobs"] = jobs

                if jobs:
                    context.scene.superluminal_settings.job_id = list(jobs.keys())[0]
            except Exception as exc:
                report_exception(self, exc, "Projects loaded, but could not fetch jobs")

        Storage.save()

        # --- refresh UI ------------------------------------------------------
        for area in context.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()

        self.report({"INFO"}, "Logged in and data preloaded.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_Logout(bpy.types.Operator):
    """Log out of Superluminal"""

    bl_idname = "superluminal.logout"
    bl_label = "Log out of Superluminal"

    def execute(self, context):
        Storage.clear()
        self.report({"INFO"}, "Logged out.")
        return {"FINISHED"}


# -----------------------------------------------------------------------------
#  Project list utilities
# -----------------------------------------------------------------------------
class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Fetch the project list from Superluminal."""

    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"

    def execute(self, context):
        try:
            projects = fetch_projects()
        except NotAuthenticated as exc:
            return report_exception(
                self, exc, str(exc),
                cleanup=lambda: setitem(Storage.data, "projects", [])
            )
        except Exception as exc:
            return report_exception(
                self, exc, "Error fetching projects",
                cleanup=lambda: setitem(Storage.data, "projects", [])
            )

        Storage.data["projects"] = projects

        self.report({"INFO"}, "Projects fetched.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjectJobs(bpy.types.Operator):
    """Fetch the job list for the selected project from Superluminal."""

    bl_idname = "superluminal.fetch_project_jobs"
    bl_label = "Fetch Project Jobs"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        project_id = prefs.project_id
        if not project_id:
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        org_id   = Storage.data.get("org_id")
        user_key = Storage.data.get("user_key")
        if not org_id or not user_key:
            self.report({"ERROR"}, "Project info missing – log in again.")
            return {"CANCELLED"}

        try:
            jobs = fetch_jobs(org_id, user_key, project_id)
        except NotAuthenticated as exc:
            return report_exception(self, exc, str(exc))
        except Exception as exc:
            return report_exception(self, exc, "Error fetching jobs")

        if jobs:
            context.scene.superluminal_settings.job_id = list(jobs.keys())[0]

        for area in context.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()

        return {"FINISHED"}


# -----------------------------------------------------------------------------
#  Registration helpers
# -----------------------------------------------------------------------------
classes = (
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_Logout,
    SUPERLUMINAL_OT_FetchProjects,
    SUPERLUMINAL_OT_FetchProjectJobs,
)


def _submit_poll(cls, context):
    return bool(Storage.data["user_token"]) and any(item[0] not in {"", "NONE"} for item in Storage.data["projects"])


def _download_poll(cls, context):
    return bool(Storage.data["user_token"]) and any(item[0] not in {"", "NONE"} for item in Storage.data["jobs"])


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if (sub_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")):
        sub_cls.poll = classmethod(_submit_poll)

    if (dl_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")):
        dl_cls.poll = classmethod(_download_poll)


def unregister():
    if (sub_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")) and getattr(sub_cls, "poll", None) is _submit_poll:
        del sub_cls.poll

    if (dl_cls := bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")) and getattr(dl_cls, "poll", None) is _download_poll:
        del dl_cls.poll

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
