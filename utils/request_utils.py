import threading
import time
import re
from urllib.parse import quote

import bpy

from ..environment import active_profile
from ..pocketbase_auth import (
    NotAuthenticated,
    authorized_request,
    reset_stored_job_session,
)
from ..storage import Storage
from .project_context import ProjectContextError
from .job_list import job_project_ids, selected_project_ids
from .version_utils import update_deployed_blender_versions

job_thread_running = False

_job_thread_state_lock = threading.Lock()
_job_refresh_lock = threading.Lock()
_last_job_refresh_context: tuple[int, int, str, str] | None = None
_last_job_refresh_completed_at = 0.0
_last_job_refresh_result: dict = {}
_refresh_state_lock = threading.Lock()
_refresh_infrastructure_enabled = True
_refresh_lifecycle_generation = 0
_observed_user_token = str(Storage.data.get("user_token") or "")
_auth_session_generation = 0
_properties_redraw_requested = threading.Event()
_pulse_timer_registered = False
_job_loop_stop_event = threading.Event()
_job_thread_generation: int | None = None


_PROJECTS_PER_PAGE = 100
_JOB_REFRESH_INTERVAL_SECONDS = 1.0
_PULSE_ACTIVE_INTERVAL_SECONDS = 0.5
_PULSE_IDLE_INTERVAL_SECONDS = 2.0


def _selected_project_identity(project_id: str) -> tuple[str, str]:
    """Return the selected project's stable id and public sqid when available."""
    projects = Storage.data.get("projects", []) or []
    ids = selected_project_ids(projects, project_id)
    if not ids:
        return "", ""
    for project in Storage.data.get("projects", []) or []:
        project_identity = {
            str(project.get("id") or "").strip(),
            str(project.get("sqid") or "").strip(),
        }
        project_identity.discard("")
        if project_identity == ids:
            return str(project.get("id") or "").strip(), str(project.get("sqid") or "").strip()
    return "", ""


def _job_matches_project(job: dict, project_id: str, project_sqid: str = "") -> bool:
    project_ids = {str(project_id or "").strip(), str(project_sqid or "").strip()}
    project_ids.discard("")
    if not project_ids:
        return True
    return not project_ids.isdisjoint(job_project_ids(job))


def _filter_jobs_for_project(jobs: dict, project_id: str, project_sqid: str = "") -> dict:
    if not project_id and not project_sqid:
        return dict(jobs or {})
    return {
        job_id: job
        for job_id, job in (jobs or {}).items()
        if isinstance(job, dict) and _job_matches_project(job, project_id, project_sqid)
    }


def fetch_projects():
    """Return all visible projects."""
    api_url = active_profile().api_url
    projects = []
    page = 1
    seen_ids = set()

    while True:
        resp = authorized_request(
            "GET",
            f"{api_url}/api/collections/projects/records",
            params={"page": page, "perPage": _PROJECTS_PER_PAGE},
        )
        payload = resp.json() or {}
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise ProjectContextError("Project listing returned an invalid page.")
        fresh = [item for item in items if isinstance(item, dict) and item.get("id") not in seen_ids]
        if items and not fresh:
            raise ProjectContextError("Project listing repeated a page; refresh projects to try again.")
        projects.extend(fresh)
        seen_ids.update(item.get("id") for item in fresh)

        try:
            total_pages = int(payload.get("totalPages") or -1)
        except (TypeError, ValueError):
            total_pages = -1

        # skipTotal=1 deliberately returns -1. Never interpret that as the end
        # of the list: with unknown totals a short page is the terminal signal.
        if total_pages >= 0:
            if page >= total_pages:
                break
        elif len(items) < _PROJECTS_PER_PAGE:
            break

        page += 1

    return projects


def fetch_storage_profiles(org_id: str, auth_context=None) -> dict:
    """Refresh choices outside panel drawing, scoped to the active login."""
    auth_context = auth_context or Storage.auth_context()
    response = authorized_request(
        "GET", f"{active_profile().api_url}/api/render/v1/storage-profiles",
        params={"organization_id": org_id},
    )
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        raise ProjectContextError("Storage listing returned an invalid response.")
    profiles = payload["profiles"]
    if not profiles or any(not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key] for key in ("id", "name", "provider")) for item in profiles):
        raise ProjectContextError("No storage choices are available.")
    if payload.get("default_profile") not in {item["id"] for item in profiles}:
        raise ProjectContextError("The default storage choice is unavailable.")
    environment, generation, token, _ = auth_context
    with Storage._lock:
        if not Storage.auth_context_matches(environment, generation, token):
            raise ProjectContextError("Your Sulu session changed. Refresh storage choices.")
        Storage.data.setdefault("storage_profiles", {})[org_id] = payload
    return payload


def fetch_blender_versions() -> list[dict]:
    """Refresh the deployed farm Blender versions advertised by PocketBase."""
    api_url = active_profile().api_url
    resp = authorized_request(
        "GET",
        f"{api_url}/api/collections/blender_versions/records",
        params={
            "filter": "enabled=true && deployed=true",
            "sort": "sort_order,identifier",
            "perPage": 200,
        },
    )
    payload = resp.json() or {}
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise ProjectContextError("Blender version listing returned an invalid page.")
    if not update_deployed_blender_versions(items):
        raise ProjectContextError("No deployed Blender versions were returned.")
    return items


def _observe_user_token_locked() -> None:
    """Advance the auth epoch when a login/logout token change is observed."""
    global _auth_session_generation
    global _observed_user_token

    current_token = str(Storage.data.get("user_token") or "")
    if current_token == _observed_user_token:
        return

    _observed_user_token = current_token
    _auth_session_generation += 1
    reset_stored_job_session()


def _current_refresh_identity() -> tuple[int, int]:
    """Return the lifecycle/auth epochs that make a refresh result publishable."""
    with _refresh_state_lock:
        _observe_user_token_locked()
        return (_refresh_lifecycle_generation, _auth_session_generation)


def invalidate_job_refresh_context() -> None:
    """Invalidate in-flight reads at a login/logout or another session boundary."""
    global _auth_session_generation
    global _observed_user_token

    with _refresh_state_lock:
        _auth_session_generation += 1
        _observed_user_token = str(Storage.data.get("user_token") or "")
    reset_stored_job_session()
    _request_properties_redraw()


def _storage_context_values_match(
    org_id: str,
    project_id: str,
    selected_project_id: str,
    selected_project_sqid: str,
) -> bool:
    current_org_id = str(Storage.data.get("org_id") or "").strip()
    if current_org_id != str(org_id or "").strip():
        return False

    current_project_id = str(Storage.data.get("project_id") or "").strip()
    valid_project_ids = {
        str(project_id or "").strip(),
        str(selected_project_id or "").strip(),
        str(selected_project_sqid or "").strip(),
    }
    valid_project_ids.discard("")
    return current_project_id in valid_project_ids


def _request_jobs_unlocked(
    org_id: str,
    project_id: str,
    *,
    refresh_identity: tuple[int, int] | None = None,
) -> dict:
    """Read the canonical project snapshot through the authenticated facade."""
    if refresh_identity is None:
        refresh_identity = _current_refresh_identity()
    org = str(org_id or "").strip()
    requested_project = str(project_id or "").strip()
    project, project_sqid = _selected_project_identity(requested_project)
    project = project or requested_project
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", org) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", project):
        raise ProjectContextError("Select an accessible organization and project before loading jobs.")
    jobs, cursors, cursor = {}, set(), None
    api_url = active_profile().api_url
    while True:
        params = {"project_id": project, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        response = authorized_request("GET", f"{api_url}/api/render/v1/browser/jobs/{quote(org, safe='')}", params=params, stored_job_session=True)
        payload = response.json()
        page = payload.get("body") if isinstance(payload, dict) else None
        if not isinstance(page, dict) or len(page) > 200:
            raise ProjectContextError("Render discovery returned an invalid page.")
        for job_id, job in page.items():
            if not isinstance(job, dict) or job_id in jobs:
                raise ProjectContextError("Render discovery repeated an item. Refresh to retry.")
            jobs[job_id] = job
        cursor = payload.get("next_cursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in cursors:
            raise ProjectContextError("Render discovery repeated a page. Refresh to retry.")
        cursors.add(cursor)
    jobs = _filter_jobs_for_project(jobs, project, project_sqid)
    with Storage._lock:
        if refresh_identity == _current_refresh_identity() and _storage_context_values_match(org, requested_project, project, project_sqid):
            Storage.data["jobs"] = jobs
            _request_properties_redraw()
    return jobs


def request_jobs(org_id: str, project_id: str):
    """Return project jobs through the authenticated pure render facade."""
    global _last_job_refresh_context
    global _last_job_refresh_completed_at
    global _last_job_refresh_result

    refresh_started_at = time.monotonic()
    lifecycle_generation, session_generation = _current_refresh_identity()
    refresh_context = (
        lifecycle_generation,
        session_generation,
        str(org_id or "").strip(),
        str(project_id or "").strip(),
    )

    # Manual/project refreshes and the auto-refresh loop share one request slot.
    # If an identical refresh completed while this caller waited, reuse it.
    with _job_refresh_lock:
        if (
            _last_job_refresh_context == refresh_context
            and _last_job_refresh_completed_at >= refresh_started_at
        ):
            return _last_job_refresh_result

        jobs = _request_jobs_unlocked(
            org_id,
            project_id,
            refresh_identity=(lifecycle_generation, session_generation),
        )
        _last_job_refresh_context = refresh_context
        _last_job_refresh_completed_at = time.monotonic()
        _last_job_refresh_result = jobs
        return jobs


def _request_properties_redraw() -> None:
    """Signal a redraw without touching Blender data from worker threads."""
    _properties_redraw_requested.set()
    if threading.current_thread() is threading.main_thread():
        _ensure_pulse_timer()


def _redraw_properties_areas() -> None:
    window_manager = getattr(getattr(bpy, "context", None), "window_manager", None)
    for window in getattr(window_manager, "windows", []):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", []):
            if getattr(area, "type", "") == "PROPERTIES":
                area.tag_redraw()


def pulse():
    global _pulse_timer_registered

    with _refresh_state_lock:
        if not _refresh_infrastructure_enabled:
            _pulse_timer_registered = False
            return None

    if _properties_redraw_requested.is_set():
        _properties_redraw_requested.clear()
        _redraw_properties_areas()

    if (
        Storage.enable_job_thread
        or Storage.jobs_updating
        or Storage.projects_updating
    ):
        return _PULSE_ACTIVE_INTERVAL_SECONDS
    return _PULSE_IDLE_INTERVAL_SECONDS


def _ensure_pulse_timer() -> None:
    """Register the main-thread redraw handoff once for the active lifecycle."""
    global _pulse_timer_registered

    if threading.current_thread() is not threading.main_thread():
        return
    with _refresh_state_lock:
        if not _refresh_infrastructure_enabled or _pulse_timer_registered:
            return
        _pulse_timer_registered = True

    timers = bpy.app.timers
    is_registered = getattr(timers, "is_registered", None)
    try:
        if not callable(is_registered) or not is_registered(pulse):
            timers.register(pulse, first_interval=_PULSE_ACTIVE_INTERVAL_SECONDS)
    except Exception:
        with _refresh_state_lock:
            _pulse_timer_registered = False
        raise


def register_job_refresh_infrastructure() -> None:
    """Enable refresh workers and the main-thread handoff after add-on register."""
    global _auth_session_generation
    global _job_loop_stop_event
    global _observed_user_token
    global _refresh_infrastructure_enabled
    global _refresh_lifecycle_generation

    with _refresh_state_lock:
        if not _refresh_infrastructure_enabled:
            _refresh_lifecycle_generation += 1
            _auth_session_generation += 1
            _observed_user_token = str(Storage.data.get("user_token") or "")
            _job_loop_stop_event = threading.Event()
            _refresh_infrastructure_enabled = True
    _ensure_pulse_timer()
    _request_properties_redraw()


def _unregister_pulse_timer() -> None:
    global _pulse_timer_registered

    timers = bpy.app.timers
    is_registered = getattr(timers, "is_registered", None)
    unregister_timer = getattr(timers, "unregister", None)
    try:
        if callable(unregister_timer) and (
            not callable(is_registered) or is_registered(pulse)
        ):
            unregister_timer(pulse)
    except (ReferenceError, RuntimeError, ValueError):
        pass
    finally:
        _pulse_timer_registered = False


def unregister_job_refresh_infrastructure() -> None:
    """Stop refresh ownership without waiting for in-flight network timeouts."""
    global _auth_session_generation
    global _observed_user_token
    global _refresh_infrastructure_enabled
    global _refresh_lifecycle_generation

    Storage.enable_job_thread = False
    _job_loop_stop_event.set()
    with _refresh_state_lock:
        _refresh_infrastructure_enabled = False
        _refresh_lifecycle_generation += 1
        _auth_session_generation += 1
        _observed_user_token = str(Storage.data.get("user_token") or "")
    reset_stored_job_session()

    _properties_redraw_requested.clear()
    _unregister_pulse_timer()


def _refresh_lifecycle_is_active(lifecycle_generation: int) -> bool:
    with _refresh_state_lock:
        return (
            _refresh_infrastructure_enabled
            and lifecycle_generation == _refresh_lifecycle_generation
        )


def request_job_loop(
    lifecycle_generation: int | None = None,
    stop_event: threading.Event | None = None,
):
    global job_thread_running
    global _job_thread_generation

    if lifecycle_generation is None:
        lifecycle_generation = _refresh_lifecycle_generation
    if stop_event is None:
        stop_event = _job_loop_stop_event

    try:
        while (
            Storage.enable_job_thread
            and not stop_event.is_set()
            and _refresh_lifecycle_is_active(lifecycle_generation)
        ):
            current_context = (
                str(Storage.data.get("org_id") or "").strip(),
                str(Storage.data.get("project_id") or "").strip(),
            )
            if not all(current_context):
                if stop_event.wait(_JOB_REFRESH_INTERVAL_SECONDS):
                    break
                continue

            try:
                request_jobs(*current_context)
            except NotAuthenticated as exc:
                Storage.enable_job_thread = False
                print(f"Stopping job updates: {exc}")
                break
            except Exception as exc:
                print(f"Could not auto-refresh jobs: {exc}")

            if stop_event.wait(_JOB_REFRESH_INTERVAL_SECONDS):
                break
    finally:
        with _job_thread_state_lock:
            if _job_thread_generation == lifecycle_generation:
                job_thread_running = False
                _job_thread_generation = None

        # A quick off/on toggle can race the old loop's shutdown. Ensure the
        # requested enabled state still owns one (and only one) loop.
        if (
            Storage.enable_job_thread
            and not stop_event.is_set()
            and _refresh_lifecycle_is_active(lifecycle_generation)
        ):
            _start_job_thread()


def _start_job_thread() -> bool:
    global job_thread_running
    global _job_thread_generation

    with _refresh_state_lock:
        if not _refresh_infrastructure_enabled:
            return False
        lifecycle_generation = _refresh_lifecycle_generation
        stop_event = _job_loop_stop_event

    with _job_thread_state_lock:
        if job_thread_running and _job_thread_generation == lifecycle_generation:
            return False
        job_thread_running = True
        _job_thread_generation = lifecycle_generation

    try:
        threading.Thread(
            target=request_job_loop,
            args=(
                lifecycle_generation,
                stop_event,
            ),
            daemon=True,
        ).start()
    except Exception:
        with _job_thread_state_lock:
            if _job_thread_generation == lifecycle_generation:
                job_thread_running = False
                _job_thread_generation = None
        raise
    return True


def fetch_jobs(org_id: str, project_id: str, live_update: bool = False):
    if live_update:
        Storage.enable_job_thread = True
        _ensure_pulse_timer()
        if _start_job_thread():
            print("starting job thread")
    else:
        return request_jobs(org_id, project_id)
