from __future__ import annotations

import bpy
import webbrowser
import time
import platform
import threading

from .constants import POCKETBASE_URL
from .pocketbase_auth import (
    AuthorizationError,
    NotAuthenticated,
    UpstreamServiceError,
    TransportError,
)
from .storage import Storage
from .utils.request_utils import (
    get_render_queue_key,
    queue_login_bootstrap,
    request_jobs_refresh,
    request_projects_refresh,
    set_refresh_context,
    stop_refresh_service,
)
from .utils.logging import report_exception


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


def _resolve_project_context(project_id: str) -> tuple[str, str]:
    project = next(
        (p for p in Storage.data.get("projects", []) if p.get("id") == project_id),
        None,
    )
    if not project:
        raise RuntimeError("Selected project not found.")

    org_id = str(project.get("organization_id", "") or "")
    if not org_id:
        raise RuntimeError("Project organization missing.")

    current_org = str(Storage.data.get("org_id", "") or "")
    user_key = str(Storage.data.get("user_key", "") or "")
    if not user_key or current_org != org_id:
        user_key = get_render_queue_key(org_id)

    Storage.data["org_id"] = org_id
    Storage.data["user_key"] = user_key
    return org_id, user_key


def _browser_login_thread_v2(txn, addon_package: str):
    token_url = f"{POCKETBASE_URL}/api/cli/token"
    try:
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
                if token and not queue_login_bootstrap(token, addon_package=addon_package):
                    raise RuntimeError("Could not start sign-in synchronization.")
    except Exception as exc:
        Storage.panel_data["login_error"] = str(exc)
        print("Browser sign-in failed:", exc)


def first_login(token):
    if not token:
        raise RuntimeError("Sign-in token is missing.")
    if not queue_login_bootstrap(token, addon_package=__package__):
        raise RuntimeError("Could not start sign-in synchronization.")
    

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

        self.report({"INFO"}, "Signed in. Syncing projects...")
        return {"FINISHED"}


class SUPERLUMINAL_OT_Logout(bpy.types.Operator):
    """Sign out of Superluminal"""
    bl_idname = "superluminal.logout"
    bl_label = "Sign Out"

    def execute(self, context):
        stop_refresh_service()
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

        t = threading.Thread(
            target=_browser_login_thread_v2,
            args=(txn, __package__),
            daemon=True,
        )
        t.start()


        self.report({"INFO"}, "Browser opened. Approve the connection to continue.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Refresh the project list"""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Refresh Projects"

    def execute(self, context):
        if not Storage.data.get("user_token"):
            self.report({"ERROR"}, "Sign in first.")
            return {"CANCELLED"}

        ok = request_projects_refresh(reason="manual")
        if not ok:
            Storage.data["projects"] = []
            self.report({"ERROR"}, "Could not start project refresh.")
            return {"CANCELLED"}

        self.report({"INFO"}, "Refreshing projects...")
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
            org_id, user_key = _resolve_project_context(project_id)
        except NotAuthenticated as exc:
            return report_exception(self, exc, str(exc))
        except AuthorizationError as exc:
            return report_exception(self, exc, f"Access denied: {exc}")
        except TransportError as exc:
            return report_exception(self, exc, f"Network error: {exc}")
        except UpstreamServiceError as exc:
            return report_exception(self, exc, f"Service unavailable: {exc}")
        except Exception as exc:
            return report_exception(self, exc, "Error preparing job refresh")

        set_refresh_context(org_id, user_key, project_id)
        if not request_jobs_refresh(reason="manual"):
            self.report({"ERROR"}, "Could not start job refresh.")
            return {"CANCELLED"}

        self.report({"INFO"}, "Refreshing jobs...")
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
