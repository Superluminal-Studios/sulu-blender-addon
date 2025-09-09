from __future__ import annotations

import bpy
from operator import setitem
import webbrowser
import time
import platform

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


# -----------------------------------------------------------------------------
#  Authentication (password)
# -----------------------------------------------------------------------------
class SUPERLIMINAL_OT_Login(bpy.types.Operator):
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
        for area in context.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()

        self.report({"INFO"}, "Logged in and data preloaded.")
        return {"FINISHED"}


class SUPERLIMINAL_OT_Logout(bpy.types.Operator):
    """Log out of Superluminal"""
    bl_idname = "superluminal.logout"
    bl_label = "Log out of Superluminal"

    def execute(self, context):
        Storage.clear()
        _flush_wm_credentials(context.window_manager)
        self.report({"INFO"}, "Logged out.")
        return {"FINISHED"}


# -----------------------------------------------------------------------------
#  Authentication (browser device-link)
# -----------------------------------------------------------------------------
class SUPERLIMINAL_OT_LoginBrowser(bpy.types.Operator):
    """Sign in via your default browser"""
    bl_idname = "superluminal.login_browser"
    bl_label = "Sign in with Browser"

    _timer = None
    _txn = ""
    _deadline = 0.0
    _interval = 2.0

    def execute(self, context):
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
            return report_exception(self, exc, "Could not start browser sign‑in")

        self._txn = data.get("txn", "")
        if not self._txn:
            self.report({"ERROR"}, "Backend did not return a transaction id.")
            return {"CANCELLED"}

        self._interval = float(data.get("interval", 2.0))
        self._deadline = time.time() + float(data.get("expires_in", 480.0))
        verification_url = data.get("verification_uri_complete") or data.get("verification_uri")

        # 2) open browser
        try:
            if verification_url:
                webbrowser.open(verification_url)
        except Exception:
            # allow copy-paste fallback if browser open fails for some envs
            if verification_url:
                self.report({"INFO"}, f"Open this URL to approve: {verification_url}")

        # 3) begin polling in a modal timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(self._interval, window=context.window)
        wm.modal_handler_add(self)
        self.report({"INFO"}, "Waiting for approval in browser…")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        # timeout?
        if time.time() >= self._deadline:
            self.report({"ERROR"}, "Sign‑in link expired. Please try again.")
            return self._finish(context, cancel=True)

        # poll token endpoint
        try:
            r = Storage.session.post(
                f"{POCKETBASE_URL}/api/cli/token",
                json={"txn": self._txn},
                timeout=Storage.timeout,
            )
            # 428 = authorization_pending → keep polling
            if r.status_code == 428:
                return {"RUNNING_MODAL"}
            # 400/404 = expired/invalid
            if r.status_code in (400, 404):
                try:
                    msg = r.json().get("message", "Denied or expired.")
                except Exception:
                    msg = "Denied or expired."
                self.report({"ERROR"}, msg)
                return self._finish(context, cancel=True)

            r.raise_for_status()
            auth = r.json()
            token = auth.get("token")
            if not token:
                self.report({"ERROR"}, "Approved but no token returned.")
                return self._finish(context, cancel=True)

            # success → set token and preload, mirroring password flow
            Storage.data["user_token"] = token
            Storage.data["projects"] = []
            Storage.data["org_id"] = ""
            Storage.data["user_key"] = ""
            Storage.data["jobs"] = {}

            prefs = context.preferences.addons[__package__].preferences

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

                    try:
                        user_key = get_render_queue_key(org_id)
                        Storage.data["org_id"] = org_id
                        Storage.data["user_key"] = user_key

                        jobs = fetch_jobs(org_id, user_key, prefs.project_id) or {}
                        Storage.data["jobs"] = jobs

                        # Best-effort: set default job id if prop exists
                        try:
                            if jobs and hasattr(context.scene, "superluminal_settings"):
                                if hasattr(context.scene.superluminal_settings, "job_id"):
                                    context.scene.superluminal_settings.job_id = list(jobs.keys())[0]
                        except Exception:
                            pass

                    except Exception as exc:
                        report_exception(self, exc, "Projects loaded, but could not fetch jobs")

                except Exception as exc:
                    report_exception(self, exc, "Failed to initialize default project")

            Storage.save()

            # scrub any in-memory creds and refresh UI
            _flush_wm_credentials(context.window_manager)
            for area in context.screen.areas:
                if area.type == "PROPERTIES":
                    area.tag_redraw()

            self.report({"INFO"}, "Logged in via browser.")
            return self._finish(context, cancel=False)

        except Exception as exc:
            # be resilient to transient network issues
            print("Polling error:", exc)
            return {"RUNNING_MODAL"}

    def _finish(self, context, cancel):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
        return {"CANCELLED" if cancel else "FINISHED"}


# -----------------------------------------------------------------------------
#  Project list utilities
# -----------------------------------------------------------------------------
class SUPERLIMINAL_OT_FetchProjects(bpy.types.Operator):
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


class SUPERLIMINAL_OT_FetchProjectJobs(bpy.types.Operator):
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

        for area in context.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()

        return {"FINISHED"}


class SUPERLIMINAL_OT_OpenBrowser(bpy.types.Operator):
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
    SUPERLIMINAL_OT_Login,
    SUPERLIMINAL_OT_Logout,
    SUPERLIMINAL_OT_LoginBrowser,      # ← NEW
    SUPERLIMINAL_OT_FetchProjects,
    SUPERLIMINAL_OT_FetchProjectJobs,
    SUPERLIMINAL_OT_OpenBrowser,
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
