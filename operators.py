from __future__ import annotations

import bpy
import sys
import traceback
import webbrowser
import time
import platform
import threading

from .constants import POCKETBASE_URL
from .environment import (
    active_environment,
    active_profile,
    job_page_url,
    projects_page_url,
    url_uses_origin,
)
from .pocketbase_auth import logged_session_request
from .storage import Storage
from .utils.request_utils import (
    _ensure_pulse_timer,
    fetch_projects,
    invalidate_job_refresh_context,
)
from .utils.project_context import ProjectContextError
from .preferences import apply_project_context


def report_exception(
    op: bpy.types.Operator,
    exc: Exception,
    message: str,
    cleanup=None,
):
    """Log the traceback, report a concise UI error, and run optional cleanup."""
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    op.report({"ERROR"}, message)
    if callable(cleanup):
        cleanup()
    return {"CANCELLED"}


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


def _start_background_job_refresh(project_id: str) -> None:
    if Storage.jobs_updating:
        return

    Storage.jobs_updating = True
    Storage.last_refresh_error = ""
    _ensure_pulse_timer()
    _redraw_properties_ui()
    result = {"message": "Jobs updated."}
    auth_context = Storage.auth_context()

    def _worker():
        try:
            apply_project_context(
                project_id,
                refresh_jobs=True,
                auth_context=auth_context,
            )
        except Exception as exc:
            if Storage.auth_context_matches(
                auth_context[0], auth_context[1], auth_context[2]
            ):
                Storage.last_refresh_error = str(exc)
            result["message"] = f"Error fetching jobs: {exc}"

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    def _poll_worker():
        if worker.is_alive():
            return 0.05
        if Storage.auth_context_matches(
            auth_context[0], auth_context[1], auth_context[2]
        ):
            Storage.jobs_updating = False
            Storage.projects_updating = False
            print(result["message"])
            _redraw_properties_ui()
        return None

    bpy.app.timers.register(_poll_worker, first_interval=0.05)


def _browser_login_thread_v2(
    txn,
    result,
    deadline,
    environment="production",
    api_url=POCKETBASE_URL,
    expected_auth_context=None,
):
    token_url = f"{api_url}/api/cli/token"
    while time.monotonic() < deadline:
        if (
            active_environment() != environment
            or (
                expected_auth_context is not None
                and not Storage.auth_context_matches(
                    expected_auth_context[0],
                    expected_auth_context[1],
                    expected_auth_context[2],
                )
            )
        ):
            raise RuntimeError("Sulu environment changed. Start sign-in again.")
        response = logged_session_request(
            Storage.session,
            "POST",
            token_url,
            json={"txn": txn},
            timeout=Storage.timeout,
        )

        if response.status_code == 428:
            time.sleep(0.2)
            continue

        response.raise_for_status()
        payload = response.json()

        token = payload.get("token")
        if token:
            if (
                active_environment() != environment
                or (
                    expected_auth_context is not None
                    and not Storage.auth_context_matches(
                        expected_auth_context[0],
                        expected_auth_context[1],
                        expected_auth_context[2],
                    )
                )
            ):
                raise RuntimeError("Sulu environment changed. Start sign-in again.")
            result["token"] = token
            result["environment"] = environment
            return token

        time.sleep(0.2)

    raise TimeoutError("Browser sign-in timed out. Try again.")


def _user_email_from_auth_payload(payload) -> str:
    try:
        record = payload.get("record") or {}
        return str(record.get("email") or "").strip()
    except Exception:
        return ""


def _fetch_user_email_for_token(token: str, api_url: str | None = None) -> str:
    if not token:
        return ""
    try:
        res = Storage.session.post(
            f"{api_url or active_profile().api_url}/api/collections/users/auth-refresh",
            headers={"Authorization": token},
            timeout=Storage.timeout,
        )
        if res.status_code != 200:
            return ""
        return _user_email_from_auth_payload(res.json())
    except Exception:
        return ""


def first_login(
    token,
    user_email: str = "",
    *,
    expected_environment: str | None = None,
    api_url: str | None = None,
    expected_auth_context=None,
):
    environment = expected_environment or active_environment()
    Storage.enable_job_thread = False
    invalidate_job_refresh_context()
    _ensure_pulse_timer()
    auth_context = Storage.begin_authenticated_session(
        environment,
        token,
        user_email,
        expected_context=expected_auth_context,
    )
    try:
        resolved_email = (
            user_email or _fetch_user_email_for_token(token, api_url)
        ).strip().lower()
        projects = fetch_projects() or []
        if not Storage.complete_authenticated_session(
            auth_context,
            user_email=resolved_email,
            projects=projects,
        ):
            raise RuntimeError("Sulu environment changed. Start sign-in again.")
    except Exception:
        Storage.clear_if_auth_context_matches(
            auth_context[0], auth_context[1], auth_context[2]
        )
        raise

    prefs = bpy.context.preferences.addons[__package__].preferences
    selected_project_id = projects[0].get("id", "") if projects else ""
    previous_project_id = prefs.project_id
    if selected_project_id != previous_project_id:
        prefs.project_id = selected_project_id
    print("First login project:", selected_project_id)

    if not selected_project_id:
        return

    if selected_project_id == previous_project_id:
        try:
            apply_project_context(
                selected_project_id,
                refresh_jobs=True,
                auth_context=auth_context,
            )
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

        login_context = Storage.auth_context()
        profile = active_profile()
        url = f"{profile.api_url}/api/collections/users/auth-with-password"
        data  = {"identity": creds.username.strip(), "password": creds.password}

        try:
            r = logged_session_request(
                Storage.session,
                "POST",
                url,
                json=data,
                timeout=Storage.timeout,
            )
            if r.status_code in (401, 403):
                _flush_wm_credentials(wm)  # scrub both email+password on wrong creds
                self.report({"ERROR"}, "Invalid email or password.")
                return {"CANCELLED"}

            r.raise_for_status()
            payload = r.json()
            token = payload.get("token")
            if token:
                first_login(
                    token,
                    _user_email_from_auth_payload(payload) or creds.username,
                    expected_environment=profile.key,
                    api_url=profile.api_url,
                    expected_auth_context=login_context,
                )
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
        Storage.enable_job_thread = False
        invalidate_job_refresh_context()
        Storage.clear()
        _flush_wm_credentials(context.window_manager)
        self.report({"INFO"}, "Signed out.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_LoginBrowser(bpy.types.Operator):
    """Sign in via your default browser"""
    bl_idname = "superluminal.login_browser"
    bl_label = "Sign In with Browser"

    def execute(self, context):
        login_context = Storage.auth_context()
        profile = active_profile()
        url = f"{profile.api_url}/api/cli/start"
        payload = {"device_hint": f"Blender {bpy.app.version_string} / {platform.system()}", "scope": "default"}

        try:
            response = logged_session_request(
                Storage.session,
                "POST",
                url,
                json=payload,
                timeout=Storage.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return report_exception(self, exc, "Could not start browser sign-in")

        txn = data.get("txn", "")
        if not txn:
            self.report({"ERROR"}, "Sign-in unavailable. Try again later.")
            return {"CANCELLED"}
        
        verification_url = data.get("verification_uri_complete") or data.get("verification_uri")
        if not url_uses_origin(verification_url, profile.web_url):
            self.report(
                {"ERROR"},
                "Sign-in returned a page outside the selected Sulu environment.",
            )
            return {"CANCELLED"}

        try:
            if verification_url:
                webbrowser.open(verification_url)
        except Exception:
            if verification_url:
                self.report({"INFO"}, f"Open this URL to approve: {verification_url}")

        Storage.last_refresh_error = ""
        result = {"token": "", "error": "", "environment": profile.key}
        deadline = time.monotonic() + 5 * 60

        def _worker():
            try:
                _browser_login_thread_v2(
                    txn,
                    result,
                    deadline,
                    profile.key,
                    profile.api_url,
                    login_context,
                )
            except Exception as exc:
                result["error"] = str(exc)

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        def _poll_worker():
            if (
                active_environment() != result.get("environment")
                or not Storage.auth_context_matches(
                    login_context[0], login_context[1], login_context[2]
                )
            ):
                return None
            if worker.is_alive():
                if time.monotonic() < deadline:
                    return 0.1
                Storage.last_refresh_error = "Browser sign-in timed out. Try again."
                _redraw_properties_ui()
                return None

            error = result.get("error", "")
            token = result.get("token", "")
            if error:
                Storage.last_refresh_error = error
            elif token:
                try:
                    if active_environment() != result.get("environment"):
                        raise RuntimeError(
                            "Sulu environment changed. Start sign-in again."
                        )
                    first_login(
                        token,
                        expected_environment=profile.key,
                        api_url=profile.api_url,
                        expected_auth_context=login_context,
                    )
                    Storage.last_refresh_error = ""
                except Exception as exc:
                    Storage.last_refresh_error = f"Browser sign-in failed: {exc}"
            else:
                Storage.last_refresh_error = "Browser sign-in did not return a token."
            _redraw_properties_ui()
            return None

        bpy.app.timers.register(_poll_worker, first_interval=0.1)


        self.report({"INFO"}, "Browser opened. Approve the connection to continue.")
        return {"FINISHED"}


class SUPERLUMINAL_OT_FetchProjects(bpy.types.Operator):
    """Refresh the project list"""
    bl_idname = "superluminal.fetch_projects"
    bl_label = "Refresh Projects"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        previous_project_id = prefs.project_id
        auth_context = Storage.auth_context()

        if Storage.projects_updating:
            self.report({"INFO"}, "Projects are already updating.")
            return {"FINISHED"}

        Storage.projects_updating = True
        Storage.jobs_updating = True
        Storage.last_refresh_error = ""
        _ensure_pulse_timer()
        _redraw_properties_ui()
        result = {"selected_project_id": "", "message": "Projects updated."}

        def _worker():
            try:
                projects = fetch_projects()
                if not Storage.auth_context_matches(
                    auth_context[0], auth_context[1], auth_context[2]
                ):
                    raise RuntimeError("Sulu environment changed during refresh.")
                with Storage._lock:
                    if not Storage.auth_context_matches(
                        auth_context[0], auth_context[1], auth_context[2]
                    ):
                        raise RuntimeError("Sulu environment changed during refresh.")
                    Storage.data["projects"] = projects
                if previous_project_id and any(p.get("id") == previous_project_id for p in projects):
                    result["selected_project_id"] = previous_project_id
                else:
                    result["selected_project_id"] = projects[0].get("id", "") if projects else ""

                if not result["selected_project_id"]:
                    with Storage._lock:
                        if not Storage.auth_context_matches(
                            auth_context[0], auth_context[1], auth_context[2]
                        ):
                            raise RuntimeError(
                                "Sulu environment changed during refresh."
                            )
                        Storage.data["project_id"] = ""
                        Storage.data["org_id"] = ""
                        Storage.data["user_key"] = ""
                        Storage.data["jobs"] = {}
                        Storage.save()
                else:
                    apply_project_context(
                        result["selected_project_id"],
                        refresh_jobs=True,
                        auth_context=auth_context,
                    )
            except Exception as exc:
                result["selected_project_id"] = ""
                if Storage.auth_context_matches(
                    auth_context[0], auth_context[1], auth_context[2]
                ):
                    Storage.last_refresh_error = str(exc)
                result["message"] = f"Error updating projects: {exc}"

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        def _poll_worker():
            if worker.is_alive():
                return 0.05
            if not Storage.auth_context_matches(
                auth_context[0], auth_context[1], auth_context[2]
            ):
                return None
            selected_project_id = result["selected_project_id"]
            if selected_project_id:
                Storage.suppress_project_callback = True
                try:
                    prefs.project_id = selected_project_id
                finally:
                    Storage.suppress_project_callback = False
            Storage.projects_updating = False
            Storage.jobs_updating = False
            Storage.save()
            print(result["message"])
            _redraw_properties_ui()
            return None

        bpy.app.timers.register(_poll_worker, first_interval=0.05)
        self.report({"INFO"}, "Updating projects...")
        return {"FINISHED"}
    

class SUPERLUMINAL_OT_OpenProjectsWebPage(bpy.types.Operator):
    """Open projects page in browser"""
    bl_idname = "superluminal.open_projects_web_page"
    bl_label = "Open Projects Page"

    def execute(self, context):
        try:
            webbrowser.open(projects_page_url(active_environment()))
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

        if Storage.jobs_updating:
            self.report({"INFO"}, "Jobs are already updating.")
            return {"FINISHED"}

        _start_background_job_refresh(project_id)
        self.report({"INFO"}, "Updating jobs...")
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
        project = next(
            (
                item
                for item in Storage.data.get("projects", [])
                if str(item.get("id") or "") == str(self.project_id or "")
            ),
            None,
        )
        project_ref = str((project or {}).get("sqid") or self.project_id or "")
        webbrowser.open(
            job_page_url(active_environment(), project_ref, self.job_id)
        )
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
