from __future__ import annotations

import bpy
from operator import setitem
import webbrowser
import time
import platform
import threading

from .constants import POCKETBASE_URL
from .pocketbase_auth import NotAuthenticated
from .storage import Storage
from .utils.request_utils import fetch_projects
from .utils.logging import report_exception
from .utils.project_context import ProjectContextError
from .preferences import apply_project_context


def _flush_wm_credentials(wm: bpy.types.WindowManager) -> None:
    try:
        creds = wm.sulu_wm
        creds.username = ""
        creds.password = ""
    except Exception:
        print("Could not flush WM credentials.")


def _flush_wm_password(wm: bpy.types.WindowManager) -> None:
    try:
        wm.sulu_wm.password = ""
    except Exception:
        print("Could not flush WM password.")


def _redraw_properties_ui() -> None:
    wm = bpy.context.window_manager
    for win in getattr(wm, "windows", []):
        scr = getattr(win, "screen", None)
        if not scr:
            continue
        for area in scr.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()


def _browser_login_thread_v2(txn):
    token_url = f"{POCKETBASE_URL}/api/cli/token"
    token = None
    while token is None:
        response = Storage.session.post(token_url, json={"txn": txn}, timeout=Storage.timeout)

        if response.status_code == 428:
            time.sleep(0.2)
            continue

        response.raise_for_status()
        payload = response.json()

        if "token" in payload:
            token = payload.get("token")
            first_login(token)

    return token


def first_login(token):
    Storage.data["user_token"] = token
    Storage.data["user_token_time"] = int(time.time())
    Storage.data["org_id"] = ""
    Storage.data["user_key"] = ""
    Storage.data["jobs"] = {}

    projects = fetch_projects() or []
    Storage.data["projects"] = projects
    Storage.save()

    prefs = bpy.context.preferences.addons[__package__].preferences
    previous_project_id = prefs.project_id
    selected_project_id = projects[0].get("id", "") if projects else ""
    prefs.project_id = selected_project_id
    print("First login project:", selected_project_id)

    if not selected_project_id:
        return

    if selected_project_id == previous_project_id:
        try:
            apply_project_context(selected_project_id, refresh_jobs=True)
        except ProjectContextError as exc:
            print(f"Project context incomplete after login: {exc}")
        except Exception as exc:
            print(f"Could not sync project context after login: {exc}")
    

class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Sign in to Superluminal"""
    bl_idname = "superluminal.login"
    bl_label = "Sign In"

    def execute(self, context):
        wm = context.window_manager
        creds = getattr(wm, "sulu_wm", None)

        if creds is None:
            self.report({"ERROR"}, "Authentication not available. Restart Blender.")
            return {"CANCELLED"}

        url   = f"{POCKETBASE_URL}/api/collections/users/auth-with-password"
        data  = {"identity": creds.username.strip(), "password": creds.password}

        try:
            r = Storage.session.post(url, json=data, timeout=Storage.timeout)
            if r.status_code in (401, 403):
                _flush_wm_credentials(wm)  # scrub both email+password on wrong creds
                self.report({"ERROR"}, "Invalid email or password.")
                return {"CANCELLED"}

            r.raise_for_status()
            payload = r.json()
            token = payload.get("token")
            if token:
                first_login(token)
            if not token:
                _flush_wm_password(wm)
                self.report({"WARNING"}, "Sign-in incomplete. Try again.")
                return {"CANCELLED"}


        except Exception as exc:
            _flush_wm_password(wm)
            return report_exception(self, exc, "Login failed")

        _flush_wm_credentials(wm)
        _redraw_properties_ui()

        self.report({"INFO"}, "Signed in.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_Logout(bpy.types.Operator):
    """Sign out of Superluminal"""
    bl_idname = "superluminal.logout"
    bl_label = "Sign Out"

    def execute(self, context):
        Storage.clear()
        _flush_wm_credentials(context.window_manager)
        self.report({"INFO"}, "Signed out.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_LoginBrowser(bpy.types.Operator):
    """Sign in via your default browser"""
    bl_idname = "superluminal.login_browser"
    bl_label = "Sign In with Browser"

    def execute(self, context):
        url = f"{POCKETBASE_URL}/api/cli/start"
        payload = {"device_hint": f"Blender {bpy.app.version_string} / {platform.system()}", "scope": "default"}

        try:
            response = Storage.session.post(url, json=payload, timeout=Storage.timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return report_exception(self, exc, "Could not start browser sign-in")

        txn = data.get("txn", "")
        if not txn:
            self.report({"ERROR"}, "Sign-in unavailable. Try again later.")
            return {"CANCELLED"}
        
        verification_url = data.get("verification_uri_complete") or data.get("verification_uri")

        try:
            if verification_url:
                webbrowser.open(verification_url)
        except Exception:
            if verification_url:
                self.report({"INFO"}, f"Open this URL to approve: {verification_url}")

        t = threading.Thread(target=_browser_login_thread_v2, args=(txn,), daemon=True)
        t.start()


        self.report({"INFO"}, "Browser opened. Approve the connection to continue.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Refresh the project list"""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Refresh Projects"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        previous_project_id = prefs.project_id

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
        if previous_project_id and any(p.get("id") == previous_project_id for p in projects):
            selected_project_id = previous_project_id
        else:
            selected_project_id = projects[0].get("id", "") if projects else ""
        prefs.project_id = selected_project_id

        if not selected_project_id:
            Storage.data["org_id"] = ""
            Storage.data["user_key"] = ""
            Storage.data["jobs"] = {}
            Storage.save()
            self.report({"INFO"}, "Projects updated.")
            return {"FINISHED"}

        if selected_project_id == previous_project_id:
            try:
                apply_project_context(selected_project_id, refresh_jobs=True)
            except ProjectContextError as exc:
                self.report({"WARNING"}, str(exc))
            except NotAuthenticated as exc:
                return report_exception(self, exc, str(exc))
            except Exception as exc:
                return report_exception(self, exc, "Error syncing project context")

        Storage.save()

        self.report({"INFO"}, "Projects updated.")
        return {"FINISHED"}
    

class SUPERLUMINAL_OT_OpenProjectsWebPage(bpy.types.Operator):
    """Open projects page in browser"""
    bl_idname = "superluminal.open_projects_web_page"
    bl_label = "Open Projects Page"

    def execute(self, context):
        try:
            webbrowser.open(f"https://superlumin.al/p")
        except Exception as exc:
            print("Could not open web browser.", exc)

        self.report({"INFO"}, "Browser opened.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjectJobs(bpy.types.Operator):
    """Refresh the job list for the selected project"""
    bl_idname = "superluminal.fetch_project_jobs"
    bl_label = "Refresh Jobs"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        project_id = prefs.project_id
        if not project_id:
            self.report({"ERROR"}, "No project selected.")
            return {"CANCELLED"}

        try:
            apply_project_context(project_id, refresh_jobs=True)
        except NotAuthenticated as exc:
            return report_exception(self, exc, str(exc))
        except ProjectContextError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:
            return report_exception(self, exc, "Error fetching jobs")

        # Best-effort set active job id if present
        try:
            jobs = Storage.data.get("jobs", {})
            if jobs and hasattr(context.scene, "superluminal_settings"):
                if hasattr(context.scene.superluminal_settings, "job_id"):
                    context.scene.superluminal_settings.job_id = list(jobs.keys())[0]
        except Exception as exc:
            print("Could not set default job after login.", exc)

        _redraw_properties_ui()
        return {"FINISHED"}


class SUPERLUMINAL_OT_OpenBrowser(bpy.types.Operator):
    """Open the job page in browser"""
    bl_idname = "superluminal.open_browser"
    bl_label = "Open in Browser"
    job_id: bpy.props.StringProperty(name="Job ID")
    project_id: bpy.props.StringProperty(name="Project ID")

    def execute(self, context):
        if not self.job_id:
            return {"CANCELLED"}
        webbrowser.open(f"https://superlumin.al/p/{self.project_id}/farm/jobs/{self.job_id}")
        return {"FINISHED"}


# -----------------------------------------------------------------------------
#  Registration helpers
# -----------------------------------------------------------------------------
classes = (
    SUPERLUMINAL_OT_Login,
    SUPERLUMINAL_OT_Logout,
    SUPERLUMINAL_OT_LoginBrowser,      # ← NON-BLOCKING browser sign-in
    SUPERLUMINAL_OT_FetchProjects,
    SUPERLUMINAL_OT_FetchProjectJobs,
    SUPERLUMINAL_OT_OpenBrowser,
    SUPERLUMINAL_OT_OpenProjectsWebPage
    
)

def _submit_poll(cls, context):
    try:
        has_token   = bool(Storage.data.get("user_token"))
        has_project = any(bool(p.get("id")) for p in Storage.data.get("projects", []))
        return has_token and has_project
    except Exception:
        return False

def _download_poll(cls, context):
    try:
        has_token = bool(Storage.data.get("user_token"))
        # if jobs is a dict, truthy means at least one job
        has_jobs  = bool(Storage.data.get("jobs"))
        return has_token and has_jobs
    except Exception:
        return False


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Attach safer poll functions if those operators exist
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
