"""
Blender operators that communicate with PocketBase,
using the simplified pocketbase_auth for token handling.

Changes in this revision
------------------------
• All automatic refresh logic removed – we rely on the backend to return
  401 when the JWT is no longer valid.
• Calls to `authorized_request()` no longer pass the old `refresh_first`
  parameter.
• Error-handling text unchanged; behaviour is simply clearer.
"""

from __future__ import annotations

import json

import bpy

from .constants import POCKETBASE_URL
from .preferences import g_project_items, g_job_items
from .pocketbase_auth import authorized_request, NotAuthenticated

# -------------------------------------------------------------------
#  Authentication
# -------------------------------------------------------------------
class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Sign in to Superluminal"""
    bl_idname = "superluminal.login"
    bl_label = "Log in to Superluminal"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        url   = f"{POCKETBASE_URL}/api/collections/users/auth-with-password"
        data  = {"identity": prefs.username, "password": prefs.password}

        import requests
        try:
            r = requests.post(url, json=data, timeout=10)
            r.raise_for_status()
            token = r.json().get("token")
            if not token:
                self.report({"WARNING"}, "Login succeeded but no token returned.")
                return {"CANCELLED"}
            prefs.user_token = token
        except Exception as err:
            self.report({"ERROR"}, f"Login failed: {err}")
            return {"CANCELLED"}

        # ---------------- 1) Fetch projects --------------------------
        try:
            proj_resp = authorized_request(
                prefs,
                "GET",
                f"{POCKETBASE_URL}/api/collections/projects/records",
            )
            fetched_projects = [
                (
                    p.get("id", ""),
                    p.get("name", p.get("id", "")),
                    f"Project {p.get('name', '')}",
                )
                for p in proj_resp.json().get("items", [])
            ]
        except Exception as exc:
            fetched_projects = []
            self.report(
                {"WARNING"},
                f"Logged in but could not fetch projects: {exc}",
            )

        g_project_items.clear()
        if fetched_projects:
            g_project_items.extend(fetched_projects)
            prefs.stored_projects = json.dumps([list(t) for t in fetched_projects])
            if not prefs.project_list or prefs.project_list == "NONE":
                prefs.project_list = fetched_projects[0][0]
        else:
            prefs.stored_projects = ""
            prefs.project_list   = ""

        # ---------------- 2) Fetch jobs for selected project --------
        g_job_items.clear()
        if prefs.project_list:
            try:
                # (a) organisation ID
                proj_resp = authorized_request(
                    prefs,
                    "GET",
                    f"{POCKETBASE_URL}/api/collections/projects/records",
                    params={"filter": f"(id='{prefs.project_list}')"},
                )
                proj   = proj_resp.json()["items"][0]
                org_id = proj["organization_id"]

                # (b) render-queue key
                rq_resp = authorized_request(
                    prefs,
                    "GET",
                    f"{POCKETBASE_URL}/api/collections/render_queues/records",
                    params={"filter": f"(organization_id='{org_id}')"},
                )
                user_key = rq_resp.json()["items"][0]["user_key"]

                # (c) verify farm availability
                authorized_request(
                    prefs,
                    "GET",
                    f"{POCKETBASE_URL}/api/farm_status/{org_id}",
                    headers={"Auth-Token": user_key},
                )

                # (d) fetch jobs
                jobs_resp = authorized_request(
                    prefs,
                    "GET",
                    f"{POCKETBASE_URL}/farm/{org_id}/api/job_list",
                    headers={"Auth-Token": user_key},
                )
                jobs = jobs_resp.json()

                g_job_items.extend(
                    (jid, d.get("name", jid), d.get("name", jid))
                    for jid, d in jobs.get("body", {}).items()
                    if prefs.project_list == d.get("project_id")
                )
                if g_job_items:
                    context.scene.superluminal_settings.job_id = g_job_items[0][0]

            except Exception as exc:
                g_job_items.clear()
                self.report(
                    {"WARNING"},
                    f"Projects loaded, but could not fetch jobs: {exc}",
                )

        # UI refresh
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
        prefs = context.preferences.addons[__package__].preferences
        prefs.user_token = ""
        g_project_items.clear()
        g_job_items.clear()
        self.report({"INFO"}, "Logged out.")
        return {"FINISHED"}


# -------------------------------------------------------------------
#  Project list utilities
# -------------------------------------------------------------------
class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Fetch the project list from Superluminal."""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Fetch Project List"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        try:
            resp = authorized_request(
                prefs,
                "GET",
                f"{POCKETBASE_URL}/api/collections/projects/records",
            )
        except NotAuthenticated as exc:
            self.report({"ERROR"}, str(exc))
            g_project_items.clear()
            g_job_items.clear()
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching projects: {exc}")
            g_project_items.clear()
            g_job_items.clear()
            return {"CANCELLED"}

        fetched = [
            (
                proj.get("id", ""),
                proj.get("name", proj.get("id", "")),
                f"Project {proj.get('name', '')}",
            )
            for proj in resp.json().get("items", [])
        ]

        g_project_items.clear()
        if fetched:
            g_project_items.extend(fetched)
            prefs.stored_projects = json.dumps([list(t) for t in fetched])
        else:
            prefs.stored_projects = ""

        self.report({"INFO"}, "Projects fetched.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjectJobs(bpy.types.Operator):
    """Fetch the job list for the selected project from Superluminal."""
    bl_idname = "superluminal.fetch_project_jobs"
    bl_label = "Fetch Project Jobs"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        project_id = prefs.project_list
        if not project_id:
            self.report({"ERROR"}, "No project selected.")
            g_job_items.clear()
            return {"CANCELLED"}

        # 1) organisation ID
        try:
            proj_resp = authorized_request(
                prefs,
                "GET",
                f"{POCKETBASE_URL}/api/collections/projects/records",
                params={"filter": f"(id='{project_id}')"},
            )
            proj   = proj_resp.json()["items"][0]
            org_id = proj["organization_id"]
        except NotAuthenticated as exc:
            self.report({"ERROR"}, str(exc))
            g_job_items.clear()
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching project info: {exc}")
            g_job_items.clear()
            return {"CANCELLED"}

        # 2) render-queue key
        try:
            rq_resp = authorized_request(
                prefs,
                "GET",
                f"{POCKETBASE_URL}/api/collections/render_queues/records",
                params={"filter": f"(organization_id='{org_id}')"},
            )
            user_key = rq_resp.json()["items"][0]["user_key"]
        except NotAuthenticated as exc:
            self.report({"ERROR"}, str(exc))
            g_job_items.clear()
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching render queue: {exc}")
            g_job_items.clear()
            return {"CANCELLED"}

        # 3) verify farm availability
        try:
            authorized_request(
                prefs,
                "GET",
                f"{POCKETBASE_URL}/api/farm_status/{org_id}",
                headers={"Auth-Token": user_key},
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Farm not available: {exc}")
            g_job_items.clear()
            return {"CANCELLED"}

        # 4) fetch jobs
        try:
            jobs_resp = authorized_request(
                prefs,
                "GET",
                f"{POCKETBASE_URL}/farm/{org_id}/api/job_list",
                headers={"Auth-Token": user_key},
            )
            jobs = jobs_resp.json()
        except NotAuthenticated as exc:
            self.report({"ERROR"}, str(exc))
            g_job_items.clear()
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Error fetching jobs: {exc}")
            g_job_items.clear()
            return {"CANCELLED"}

        g_job_items.clear()
        g_job_items.extend(
            (jid, d.get("name", jid), d.get("name", jid))
            for jid, d in jobs.get("body", {}).items()
            if prefs.project_list == d.get("project_id")
        )

        if g_job_items:
            context.scene.superluminal_settings.job_id = g_job_items[0][0]

        for area in context.screen.areas:
            if area.type == "PROPERTIES":
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

def _submit_poll(cls, context):
    prefs = context.preferences.addons[__package__].preferences
    logged_in   = bool(prefs.user_token)
    projects_ok = any(item[0] not in {"", "NONE"} for item in g_project_items)
    return logged_in and projects_ok


def _download_poll(cls, context):
    prefs = context.preferences.addons[__package__].preferences
    logged_in = bool(prefs.user_token)
    jobs_ok   = any(item[0] not in {"", "NONE"} for item in g_job_items)
    return logged_in and jobs_ok


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    sub_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")
    if sub_cls:
        sub_cls.poll = classmethod(_submit_poll)

    dl_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")
    if dl_cls:
        dl_cls.poll = classmethod(_download_poll)


def unregister():
    sub_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.submit_job")
    if sub_cls and getattr(sub_cls, "poll", None) is _submit_poll:
        del sub_cls.poll

    dl_cls = bpy.types.Operator.bl_rna_get_subclass_py("superluminal.download_job")
    if dl_cls and getattr(dl_cls, "poll", None) is _download_poll:
        del dl_cls.poll

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
