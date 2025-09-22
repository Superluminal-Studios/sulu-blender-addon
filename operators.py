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
from .utils.request_utils import fetch_projects, get_render_queue_key, fetch_jobs
from .utils.logging import report_exception


# ────────────────────────────────────────────────────────────────
#  Helpers to scrub in-memory credentials (WindowManager props)
# ────────────────────────────────────────────────────────────────
def _flush_wm_credentials(wm: bpy.types.WindowManager) -> None:
    try:
        creds = wm.sulu_wm
        creds.username = ""
        creds.password = ""
    except Exception:
        pass

def _flush_wm_password(wm: bpy.types.WindowManager) -> None:
    try:
        wm.sulu_wm.password = ""
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────
#  Non-blocking browser-login worker (thread + timer pump)
# ────────────────────────────────────────────────────────────────
class _BrowserLoginState:
    """Shared state between the polling thread and the timer pump."""
    def __init__(self):
        self.lock = threading.Lock()
        self.active = False
        self.stop = threading.Event()

        # inputs
        self.txn: str = ""
        self.deadline: float = 0.0
        self.interval: float = 2.0

        # outputs / milestones
        self.error: str | None = None
        self.token: str | None = None
        self.bootstrap_done: bool = False
        self.bootstrap_error: str | None = None

        # data fetched in background (applied on main thread)
        self.projects: list | None = None
        self.org_id: str = ""
        self.user_key: str = ""
        self.jobs: dict | None = None
        self.selected_project_id: str = ""

        self.thread: threading.Thread | None = None

    def reset(self):
        with self.lock:
            self.active = False
            self.stop.clear()
            self.txn = ""
            self.deadline = 0.0
            self.interval = 2.0
            self.error = None
            self.token = None
            self.bootstrap_done = False
            self.bootstrap_error = None
            self.projects = None
            self.org_id = ""
            self.user_key = ""
            self.jobs = None
            self.selected_project_id = ""
            self.thread = None


_LOGIN_STATE = _BrowserLoginState()
_PUMP_REGISTERED = False


def _redraw_properties_ui() -> None:
    wm = bpy.context.window_manager
    for win in getattr(wm, "windows", []):
        scr = getattr(win, "screen", None)
        if not scr:
            continue
        for area in scr.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()


def _apply_bootstrap_to_blender(state: _BrowserLoginState):
    """Apply fetched data to Blender data on the main thread (UI-safe)."""
    prefs = bpy.context.preferences.addons[__package__].preferences

    # install token + fetched data into Storage
    if state.token:
        Storage.data["user_token"] = state.token
    Storage.data["projects"] = state.projects or []
    Storage.data["org_id"] = state.org_id or ""
    Storage.data["user_key"] = state.user_key or ""
    Storage.data["jobs"] = state.jobs or {}

    # choose default project
    if Storage.data["projects"]:
        try:
            project_id = state.selected_project_id or Storage.data["projects"][0]["id"]
            prefs.project_id = project_id
        except Exception:
            pass

    Storage.save()
    _flush_wm_credentials(bpy.context.window_manager)
    _redraw_properties_ui()


def _browser_login_thread(state: _BrowserLoginState):
    """
    Background thread:
    1) Poll /api/cli/token until approved/denied/expired.
    2) On approval, set token into Storage (for downstream API calls),
       then fetch projects → org key → jobs in background.
    NOTE: No Blender UI/RNA access here!
    """
    try:
        token_url = f"{POCKETBASE_URL}/api/cli/token"
        while not state.stop.is_set():
            # check deadline
            if time.time() >= state.deadline:
                with state.lock:
                    state.error = "Sign-in link expired. Please try again."
                return

            try:
                r = Storage.session.post(
                    token_url, json={"txn": state.txn}, timeout=Storage.timeout
                )
                if r.status_code == 428:
                    # authorization_pending
                    time.sleep(max(0.2, min(5.0, state.interval)))
                    continue
                if r.status_code in (400, 404):
                    try:
                        msg = r.json().get("message", "Denied or expired.")
                    except Exception:
                        msg = "Denied or expired."
                    with state.lock:
                        state.error = msg
                    return

                r.raise_for_status()
                payload = r.json()
                token = payload.get("token")
                if not token:
                    with state.lock:
                        state.error = "Approved but no token returned."
                    return

                # put token into Storage so API helpers can work
                with state.lock:
                    state.token = token
                Storage.data["user_token"] = token

                # background bootstrap (network only)
                try:
                    projects = fetch_projects() or []
                    org_id = ""
                    user_key = ""
                    jobs = {}

                    if projects:
                        # pick first (same as password flow)
                        project = projects[0]
                        org_id = project.get("organization_id", "")
                        if org_id:
                            user_key = get_render_queue_key(org_id)
                            if user_key:
                                jobs = fetch_jobs(org_id, user_key, project.get("id", "")) or {}

                    with state.lock:
                        state.projects = projects
                        state.org_id = org_id
                        state.user_key = user_key
                        state.jobs = jobs
                        state.selected_project_id = projects[0]["id"] if projects else ""
                        state.bootstrap_done = True
                    return

                except Exception as exc:
                    with state.lock:
                        state.bootstrap_error = f"Logged in but could not fetch data: {exc}"
                        state.bootstrap_done = True
                    return

            except Exception:
                # transient network error; short backoff
                time.sleep(max(0.2, min(2.0, state.interval)))
                continue
    finally:
        # thread exits; timer pump will observe flags and clean up state
        pass


def _browser_login_pump():
    """Timer pump that reads state and updates Blender UI. Runs very fast + tiny."""
    global _PUMP_REGISTERED
    st = _LOGIN_STATE

    with st.lock:
        active = st.active
        error = st.error
        token = st.token
        bootstrap_done = st.bootstrap_done
        bootstrap_error = st.bootstrap_error

    if not active:
        _PUMP_REGISTERED = False
        return None  # stop timer

    # surface errors to the user and stop
    if error:
        _LOGIN_STATE.stop.set()
        _LOGIN_STATE.active = False
        try:
            bpy.ops.wm.call_panel('INVOKE_DEFAULT')  # no-op; ensures status bar refresh
        except Exception:
            pass
        bpy.ops.wm.report(type={'ERROR'}, message=error) if hasattr(bpy.ops.wm, "report") else None
        return None

    # once bootstrap is done, apply on main thread
    if bootstrap_done:
        if token:
            _apply_bootstrap_to_blender(st)
            if bootstrap_error:
                # Informative warning but still considered a successful login.
                try:
                    bpy.ops.wm.report(type={'WARNING'}, message=bootstrap_error)
                except Exception:
                    pass
            else:
                try:
                    bpy.ops.wm.report(type={'INFO'}, message="Logged in via browser.")
                except Exception:
                    pass
        else:
            # shouldn't happen: bootstrap_done but no token
            try:
                bpy.ops.wm.report(type={'ERROR'}, message="Login failed.")
            except Exception:
                pass

        _LOGIN_STATE.stop.set()
        _LOGIN_STATE.active = False
        return None

    # keep pumping
    return 0.2


def _ensure_pump_registered():
    global _PUMP_REGISTERED
    if not _PUMP_REGISTERED:
        _PUMP_REGISTERED = True
        bpy.app.timers.register(_browser_login_pump, first_interval=0.2, persistent=False)


# -----------------------------------------------------------------------------
#  Authentication (password)
# -----------------------------------------------------------------------------
class SUPERLUMINAL_OT_Login(bpy.types.Operator):
    """Sign in to Superluminal"""
    bl_idname = "superluminal.login"
    bl_label = "Log in to Superluminal"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        wm = context.window_manager
        creds = getattr(wm, "sulu_wm", None)

        if creds is None:
            self.report({"ERROR"}, "Internal error: auth props not registered.")
            return {"CANCELLED"}

        url   = f"{POCKETBASE_URL}/api/collections/users/auth-with-password"
        data  = {"identity": creds.username.strip(), "password": creds.password}

        # --- 0) authenticate -------------------------------------------------
        try:
            r = Storage.session.post(url, json=data, timeout=Storage.timeout)
            if r.status_code in (401, 403):
                _flush_wm_credentials(wm)  # scrub both email+password on wrong creds
                self.report({"ERROR"}, "Invalid email or password.")
                return {"CANCELLED"}

            r.raise_for_status()
            payload = r.json()
            token = payload.get("token")
            if not token:
                _flush_wm_password(wm)
                self.report({"WARNING"}, "Login succeeded but no token returned.")
                return {"CANCELLED"}

            Storage.data["user_token"] = token

        except Exception as exc:
            _flush_wm_password(wm)
            return report_exception(self, exc, "Login failed")

        # --- 1) establish coherent session state ----------------------------
        # Always overwrite these so we don't carry stale values.
        Storage.data["projects"] = []
        Storage.data["org_id"] = ""
        Storage.data["user_key"] = ""
        Storage.data["jobs"] = {}

        projects = []
        try:
            projects = fetch_projects()
        except Exception as exc:
            self.report({"WARNING"}, f"Logged in but could not fetch projects: {exc}")
        finally:
            Storage.data["projects"] = projects or []

        if projects:
            try:
                project = projects[0]
                prefs.project_id = project["id"]
                org_id = project["organization_id"]

                # get queue key + jobs
                try:
                    user_key = get_render_queue_key(org_id)
                    Storage.data["org_id"] = org_id
                    Storage.data["user_key"] = user_key

                    jobs = fetch_jobs(org_id, user_key, prefs.project_id) or {}
                    Storage.data["jobs"] = jobs

                    # Best-effort: set default job id if prop exists
                    try:
                        if jobs and hasattr(context.scene, "superluminal_settings"):
                            # only set if property exists; ignore otherwise
                            if hasattr(context.scene.superluminal_settings, "job_id"):
                                context.scene.superluminal_settings.job_id = list(jobs.keys())[0]
                        # else ignore silently
                    except Exception:
                        pass

                except Exception as exc:
                    report_exception(self, exc, "Projects loaded, but could not fetch jobs")

            except Exception as exc:
                report_exception(self, exc, "Failed to initialize default project")

        # Persist coherent state
        Storage.save()

        # Scrub credentials from memory after successful login
        _flush_wm_credentials(wm)

        # --- refresh UI ------------------------------------------------------
        _redraw_properties_ui()

        self.report({"INFO"}, "Logged in and data preloaded.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_Logout(bpy.types.Operator):
    """Log out of Superluminal"""
    bl_idname = "superluminal.logout"
    bl_label = "Log out of Superluminal"

    def execute(self, context):
        Storage.clear()
        _flush_wm_credentials(context.window_manager)
        self.report({"INFO"}, "Logged out.")
        return {"FINISHED"}


# -----------------------------------------------------------------------------
#  Authentication (browser device-link) — NON-BLOCKING
# -----------------------------------------------------------------------------
class SUPERLUMINAL_OT_LoginBrowser(bpy.types.Operator):
    """Sign in via your default browser (non-blocking)"""
    bl_idname = "superluminal.login_browser"
    bl_label = "Sign in with Browser"

    def execute(self, context):
        # If a previous login is running, cancel it
        if _LOGIN_STATE.active:
            _LOGIN_STATE.stop.set()
            # let the previous timer tick once more and exit

        # 1) start pairing
        url = f"{POCKETBASE_URL}/api/cli/start"
        payload = {
            "device_hint": f"Blender {bpy.app.version_string} / {platform.system()}",
            "scope": "default",
        }
        try:
            r = Storage.session.post(url, json=payload, timeout=Storage.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            return report_exception(self, exc, "Could not start browser sign-in")

        txn = data.get("txn", "")
        if not txn:
            self.report({"ERROR"}, "Backend did not return a transaction id.")
            return {"CANCELLED"}

        interval = float(data.get("interval", 2.0))
        deadline = time.time() + float(data.get("expires_in", 480.0))
        verification_url = data.get("verification_uri_complete") or data.get("verification_uri")

        # 2) open browser (non-blocking)
        try:
            if verification_url:
                webbrowser.open(verification_url)
        except Exception:
            if verification_url:
                self.report({"INFO"}, f"Open this URL to approve: {verification_url}")

        # 3) kick off background polling thread
        _LOGIN_STATE.reset()
        _LOGIN_STATE.active = True
        _LOGIN_STATE.txn = txn
        _LOGIN_STATE.interval = interval
        _LOGIN_STATE.deadline = deadline

        t = threading.Thread(target=_browser_login_thread, args=(_LOGIN_STATE,), daemon=True)
        _LOGIN_STATE.thread = t
        t.start()

        # 4) ensure timer pump is running and finish immediately
        _ensure_pump_registered()
        self.report({"INFO"}, "Browser opened. Approve to connect; you can keep working.")
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
        Storage.save()

        self.report({"INFO"}, "Projects fetched.")
        return {"FINISHED"}
    

class SUPERLUMINAL_OT_OpenProjectsWebPage(bpy.types.Operator):
    """Fetch the project list from Superluminal."""
    bl_idname = "superluminal.open_projects_web_page"
    bl_label = "Fetch Project List"

    def execute(self, context):
        try:
            webbrowser.open(f"https://superlumin.al/p")
        except:
            pass
        
        self.report({"INFO"}, "Opened Web Browser")
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
            jobs = fetch_jobs(org_id, user_key, project_id) or {}
        except NotAuthenticated as exc:
            return report_exception(self, exc, str(exc))
        except Exception as exc:
            return report_exception(self, exc, "Error fetching jobs")

        Storage.data["jobs"] = jobs
        Storage.save()

        # Best-effort set active job id if present
        try:
            if jobs and hasattr(context.scene, "superluminal_settings"):
                if hasattr(context.scene.superluminal_settings, "job_id"):
                    context.scene.superluminal_settings.job_id = list(jobs.keys())[0]
        except Exception:
            pass

        _redraw_properties_ui()
        return {"FINISHED"}


class SUPERLUMINAL_OT_OpenBrowser(bpy.types.Operator):
    """Open the job in the browser."""
    bl_idname = "superluminal.open_browser"
    bl_label = "Open Job in Browser"
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
