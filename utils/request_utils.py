from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time

import bpy

from ..constants import POCKETBASE_URL
from ..pocketbase_auth import NotAuthenticated, NotFound, authorized_request
from ..storage import Storage
from .project_context import ProjectContextError
from .job_list import int_value as _int_value, job_project_ids, selected_project_ids
from .prefs import get_prefs

job_thread_running = False

_job_thread_state_lock = threading.Lock()
_job_refresh_lock = threading.Lock()
_last_job_refresh_context: tuple[int, int, str, str, str] | None = None
_last_job_refresh_completed_at = 0.0
_last_job_refresh_result: dict = {}
_live_job_future_lock = threading.Lock()
_refresh_infrastructure_enabled = True
_refresh_lifecycle_generation = 0
_observed_user_token = str(Storage.data.get("user_token") or "")
_auth_session_generation = 0
_live_job_request_generation = 0
_live_job_executor: ThreadPoolExecutor | None = None
_live_job_future: Future | None = None
_live_job_future_context: tuple[str, str] | None = None
_live_job_future_generation = 0
_live_job_future_session_generation = 0
_live_job_future_lifecycle_generation = 0
_pending_live_overlay = None
_live_job_redraw_pending = threading.Event()
_properties_redraw_requested = threading.Event()
_pulse_timer_registered = False
_job_loop_stop_event = threading.Event()
_job_thread_generation: int | None = None


def _create_live_job_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="sulu-live-job-source",
    )


_live_job_executor = _create_live_job_executor()


@dataclass(frozen=True)
class _LiveJobTicket:
    future: Future
    context: tuple[str, str]
    request_generation: int
    session_generation: int
    lifecycle_generation: int


@dataclass(frozen=True)
class _DeferredLiveOverlay:
    ticket: _LiveJobTicket
    org_id: str
    user_key: str
    requested_project_id: str
    selected_project_id: str
    selected_project_sqid: str
    live_jobs: dict


LIVE_JOB_OVERLAY_FIELDS = {
    "status",
    "thumbnail",
    "baseThumb",
    "base_thumb",
    "s3_bucket",
    "s3_access_key_id",
    "s3_secret_access_key",
    "s3_session_token",
    "start_time",
    "end_time",
    "iteration",
    "last_task",
    "machine_time",
    "machine_count",
    "total_tasks",
    "stop_watch",
    "rolling_task_time",
    "rolling_task_mask",
}

_PROJECTS_PER_PAGE = 100
_STORED_JOBS_LIMIT = 100
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


def _normalize_task_counts(job: dict) -> dict:
    tasks = job.get("tasks", {}) or {}
    if not isinstance(tasks, dict):
        tasks = {}
    error_value = tasks.get("error", tasks.get("errored", 0))
    return {
        "queued": _int_value(tasks.get("queued"), 0),
        "running": _int_value(tasks.get("running"), 0),
        "finished": _int_value(tasks.get("finished"), 0),
        "paused": _int_value(tasks.get("paused"), 0),
        "error": _int_value(error_value, 0),
    }


def _merge_stored_job_with_live_overlay(stored_job: dict, live_job: dict | None) -> dict:
    if not isinstance(live_job, dict):
        return dict(stored_job)

    merged = dict(stored_job)
    for field in LIVE_JOB_OVERLAY_FIELDS:
        if field in live_job:
            merged[field] = live_job[field]

    if isinstance(live_job.get("tasks"), dict):
        merged["tasks"] = _normalize_task_counts(live_job)

    return merged


def _merge_job_sources(
    stored_jobs: dict,
    live_jobs: dict,
    project_id: str,
    project_sqid: str = "",
    *,
    allow_live_only: bool = False,
) -> dict:
    """
    Use persisted jobs as history, then overlay live farm fields for known jobs.

    The live farm process can lose old finished jobs after a process/db reset; the
    persisted jobs endpoint is the source of truth for the downloads list.
    """
    merged = _filter_jobs_for_project(stored_jobs, project_id, project_sqid)
    live_scoped = _filter_jobs_for_project(live_jobs, project_id, project_sqid)
    for job_id, stored_job in list(merged.items()):
        merged[job_id] = _merge_stored_job_with_live_overlay(
            stored_job,
            live_scoped.get(job_id),
        )

    if allow_live_only:
        for job_id, live_job in live_scoped.items():
            if job_id in merged:
                continue
            merged[job_id] = live_job

    return merged


def fetch_projects():
    """Return all visible projects."""
    projects = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        resp = authorized_request(
            "GET",
            f"{POCKETBASE_URL}/api/collections/projects/records",
            params={"page": page, "perPage": _PROJECTS_PER_PAGE},
        )
        payload = resp.json() or {}
        projects.extend(payload.get("items") or [])

        try:
            total_pages = int(payload.get("totalPages") or 1)
        except (TypeError, ValueError):
            total_pages = 1

        page += 1

    return projects


def get_render_queue_key(org_id: str) -> str:
    """Return the ``user_key`` for *org_id*'s render‑queue."""
    rq_resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/collections/render_queues/records",
        params={"filter": f"(organization_id='{org_id}')"},
    )
    payload = rq_resp.json() or {}
    items = payload.get("items") or []
    if not items:
        raise ProjectContextError(
            f"No render queue is available for organization '{org_id}'."
        )

    user_key = str(items[0].get("user_key") or "").strip()
    if not user_key:
        raise ProjectContextError(
            f"Render queue user_key is missing for organization '{org_id}'."
        )
    return user_key


def _request_stored_jobs(
    org_id: str,
    project_id: str = "",
    limit: int = _STORED_JOBS_LIMIT,
) -> dict:
    # The persisted job payload also feeds the web admin and can contain large
    # scene manifests.  Blender only needs the compact list/download snapshot;
    # older backends safely ignore this opt-in query parameter.
    params = {"limit": max(1, int(limit)), "view": "addon"}
    if project_id := str(project_id or "").strip():
        params["project_id"] = project_id

    resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/jobs/{org_id}",
        params=params,
        isolated_session=True,
    )
    if resp.status_code == 200 and resp.text:
        return resp.json().get("body", {}) or {}
    return {}


def _wake_queue_manager(org_id: str, user_key: str) -> None:
    authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/farm_status/{org_id}",
        headers={"Auth-Token": user_key},
        isolated_session=True,
    )
    print("Starting queue manager")


def _request_live_jobs(
    org_id: str,
    user_key: str,
    *,
    allow_queue_manager_wake: bool = True,
) -> dict:
    jobs_resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/farm/{org_id}/api/job_list",
        headers={"Auth-Token": user_key},
        isolated_session=True,
    )
    if jobs_resp.status_code == 200 and jobs_resp.text:
        return jobs_resp.json().get("body", {}) or {}
    if jobs_resp.status_code == 200 and allow_queue_manager_wake:
        _wake_queue_manager(org_id, user_key)
        return _request_live_jobs(
            org_id,
            user_key,
            allow_queue_manager_wake=False,
        )
    return {}


def _retire_live_job_future_locked() -> Future | None:
    """Invalidate the current farm request while the caller holds its state lock."""
    global _live_job_future
    global _pending_live_overlay

    retired_future = _live_job_future
    _live_job_future = None
    _pending_live_overlay = None
    _live_job_redraw_pending.clear()
    return retired_future


def _observe_user_token_locked() -> Future | None:
    """Advance the auth epoch when a login/logout token change is observed."""
    global _auth_session_generation
    global _observed_user_token

    current_token = str(Storage.data.get("user_token") or "")
    if current_token == _observed_user_token:
        return None

    _observed_user_token = current_token
    _auth_session_generation += 1
    return _retire_live_job_future_locked()


def _cancel_retired_future(future: Future | None) -> None:
    if future is not None and not future.done():
        future.cancel()


def _current_refresh_identity() -> tuple[int, int]:
    """Return the lifecycle/auth epochs that make a refresh result publishable."""
    with _live_job_future_lock:
        retired_future = _observe_user_token_locked()
        identity = (_refresh_lifecycle_generation, _auth_session_generation)
    _cancel_retired_future(retired_future)
    return identity


def invalidate_job_refresh_context() -> None:
    """Retire deferred results before login/logout or another session boundary."""
    global _auth_session_generation
    global _observed_user_token

    with _live_job_future_lock:
        _auth_session_generation += 1
        _observed_user_token = str(Storage.data.get("user_token") or "")
        retired_future = _retire_live_job_future_locked()
    _cancel_retired_future(retired_future)
    _request_properties_redraw()


def _ticket_is_current_locked(ticket: _LiveJobTicket) -> bool:
    return (
        _refresh_infrastructure_enabled
        and ticket.lifecycle_generation == _refresh_lifecycle_generation
        and ticket.session_generation == _auth_session_generation
        and ticket.request_generation == _live_job_future_generation
        and ticket.context == _live_job_future_context
        and ticket.future is _live_job_future
    )


def _ticket_is_current(ticket: _LiveJobTicket) -> bool:
    with _live_job_future_lock:
        return _ticket_is_current_locked(ticket)


def _get_or_start_live_jobs_future(
    org_id: str,
    user_key: str,
    *,
    refresh_identity: tuple[int, int] | None = None,
) -> _LiveJobTicket:
    """Keep one current farm request, identified by lifecycle, auth, and context."""
    global _live_job_executor
    global _live_job_future
    global _live_job_future_context
    global _live_job_future_generation
    global _live_job_future_lifecycle_generation
    global _live_job_future_session_generation
    global _live_job_request_generation

    context = (str(org_id or "").strip(), str(user_key or "").strip())
    retired_future = None
    ticket = None
    identity_error = False
    with _live_job_future_lock:
        token_retired_future = _observe_user_token_locked()
        if token_retired_future is not None:
            retired_future = token_retired_future

        current_identity = (
            _refresh_lifecycle_generation,
            _auth_session_generation,
        )
        if refresh_identity is None:
            refresh_identity = current_identity

        lifecycle_generation, session_generation = refresh_identity
        identity_error = (
            not _refresh_infrastructure_enabled
            or refresh_identity != current_identity
        )
        if not identity_error:
            if (
                _live_job_future_context == context
                and _live_job_future is not None
                and not _live_job_future.done()
                and _live_job_future_lifecycle_generation == lifecycle_generation
                and _live_job_future_session_generation == session_generation
            ):
                ticket = _LiveJobTicket(
                    future=_live_job_future,
                    context=context,
                    request_generation=_live_job_future_generation,
                    session_generation=session_generation,
                    lifecycle_generation=lifecycle_generation,
                )
            else:
                context_retired_future = _retire_live_job_future_locked()
                if context_retired_future is not None:
                    retired_future = context_retired_future

                if _live_job_executor is None:
                    _live_job_executor = _create_live_job_executor()

                _live_job_request_generation += 1
                _live_job_future_generation = _live_job_request_generation
                _live_job_future_lifecycle_generation = lifecycle_generation
                _live_job_future_session_generation = session_generation
                _live_job_future_context = context
                _live_job_redraw_pending.set()
                _live_job_future = _live_job_executor.submit(
                    _request_live_jobs,
                    org_id,
                    user_key,
                )
                ticket = _LiveJobTicket(
                    future=_live_job_future,
                    context=context,
                    request_generation=_live_job_future_generation,
                    session_generation=session_generation,
                    lifecycle_generation=lifecycle_generation,
                )

    _cancel_retired_future(retired_future)
    if identity_error or ticket is None:
        raise RuntimeError("Job refresh request was superseded")
    return ticket


def _complete_live_jobs_ticket(ticket: _LiveJobTicket) -> None:
    with _live_job_future_lock:
        if _ticket_is_current_locked(ticket):
            _retire_live_job_future_locked()
    _request_properties_redraw()


def _request_stored_jobs_while_live_starts(
    org_id: str,
    user_key: str,
    project_id: str,
    *,
    refresh_identity: tuple[int, int] | None = None,
) -> tuple[dict, bool, _LiveJobTicket]:
    """Fetch bounded persisted history without waiting for the slower farm list."""
    live_ticket = _get_or_start_live_jobs_future(
        org_id,
        user_key,
        refresh_identity=refresh_identity,
    )
    stored_jobs = {}
    stored_error: Exception | None = None

    try:
        stored_jobs = _request_stored_jobs(
            org_id,
            project_id,
            _STORED_JOBS_LIMIT,
        )
    except Exception as exc:
        stored_error = exc

    if isinstance(stored_error, NotAuthenticated):
        live_ticket.future.add_done_callback(
            lambda _completed: _complete_live_jobs_ticket(live_ticket)
        )
        raise stored_error

    stored_jobs_available = stored_error is None
    if isinstance(stored_error, NotFound):
        print(
            "Stored jobs endpoint unavailable, falling back to live job list: "
            f"{stored_error}"
        )
    elif stored_error is not None:
        print(f"Could not fetch stored jobs, falling back to live job list: {stored_error}")

    return stored_jobs, stored_jobs_available, live_ticket


def _resolve_live_jobs(
    future: Future,
    *,
    stored_jobs_available: bool,
) -> tuple[dict, Exception | None]:
    try:
        return future.result(), None
    except Exception as exc:
        if not stored_jobs_available:
            raise
        print(f"Could not fetch live jobs; using stored jobs only: {exc}")
        return {}, exc


def _apply_deferred_live_jobs(
    future: Future,
    ticket: _LiveJobTicket,
    org_id: str,
    user_key: str,
    requested_project_id: str,
    selected_project_id: str,
    selected_project_sqid: str,
) -> None:
    """Queue a farm overlay for validated publication by Blender's main timer."""
    global _pending_live_overlay

    live_jobs, live_error = _resolve_live_jobs(
        future,
        stored_jobs_available=True,
    )
    if live_error is not None:
        _complete_live_jobs_ticket(ticket)
        return

    with _live_job_future_lock:
        if not _ticket_is_current_locked(ticket):
            return
        _pending_live_overlay = _DeferredLiveOverlay(
            ticket=ticket,
            org_id=org_id,
            user_key=user_key,
            requested_project_id=requested_project_id,
            selected_project_id=selected_project_id,
            selected_project_sqid=selected_project_sqid,
            live_jobs=live_jobs,
        )
    _request_properties_redraw()


def _request_job_sources(
    org_id: str,
    user_key: str,
    project_id: str,
) -> tuple[dict, bool, dict]:
    """Compatibility helper used by focused tests and fallback callers."""
    stored_jobs, stored_jobs_available, live_ticket = (
        _request_stored_jobs_while_live_starts(
            org_id,
            user_key,
            project_id,
        )
    )
    try:
        live_jobs, _ = _resolve_live_jobs(
            live_ticket.future,
            stored_jobs_available=stored_jobs_available,
        )
    finally:
        _complete_live_jobs_ticket(live_ticket)
    return stored_jobs, stored_jobs_available, live_jobs


def _storage_context_values_match(
    org_id: str,
    user_key: str,
    project_id: str,
    selected_project_id: str,
    selected_project_sqid: str,
) -> bool:
    current_org_id = str(Storage.data.get("org_id") or "").strip()
    if current_org_id and current_org_id != str(org_id or "").strip():
        return False

    current_user_key = str(Storage.data.get("user_key") or "").strip()
    if current_user_key and current_user_key != str(user_key or "").strip():
        return False

    current_project_id = str(Storage.data.get("project_id") or "").strip()
    valid_project_ids = {
        str(project_id or "").strip(),
        str(selected_project_id or "").strip(),
        str(selected_project_sqid or "").strip(),
    }
    valid_project_ids.discard("")
    return not current_project_id or current_project_id in valid_project_ids


def _storage_context_matches(
    org_id: str,
    user_key: str,
    project_id: str,
    selected_project_id: str,
    selected_project_sqid: str,
    ticket: _LiveJobTicket,
) -> bool:
    return _ticket_is_current(ticket) and _storage_context_values_match(
        org_id,
        user_key,
        project_id,
        selected_project_id,
        selected_project_sqid,
    )


def _request_jobs_unlocked(
    org_id: str,
    user_key: str,
    project_id: str,
    *,
    refresh_identity: tuple[int, int] | None = None,
) -> dict:
    # Worker threads update Storage only; Blender collections are rebuilt on the main thread.
    if refresh_identity is None:
        refresh_identity = _current_refresh_identity()
    requested_project_id = str(project_id or "").strip()
    selected_project_id, selected_project_sqid = _selected_project_identity(
        requested_project_id
    )
    if not selected_project_id and not selected_project_sqid:
        selected_project_id = requested_project_id

    stored_query_project_id = selected_project_id or selected_project_sqid
    stored_jobs, stored_jobs_available, live_ticket = (
        _request_stored_jobs_while_live_starts(
            org_id,
            user_key,
            stored_query_project_id,
            refresh_identity=refresh_identity,
        )
    )

    defer_live_overlay = stored_jobs_available and not live_ticket.future.done()
    live_jobs = {}
    if not defer_live_overlay:
        live_jobs, _ = _resolve_live_jobs(
            live_ticket.future,
            stored_jobs_available=stored_jobs_available,
        )

    jobs = _merge_job_sources(
        stored_jobs,
        live_jobs,
        selected_project_id,
        selected_project_sqid,
        allow_live_only=not stored_jobs_available,
    )
    if _storage_context_matches(
        org_id,
        user_key,
        requested_project_id,
        selected_project_id,
        selected_project_sqid,
        live_ticket,
    ):
        Storage.data["jobs"] = jobs
        _request_properties_redraw()
    if defer_live_overlay:
        live_ticket.future.add_done_callback(
            lambda completed: _apply_deferred_live_jobs(
                completed,
                live_ticket,
                org_id,
                user_key,
                requested_project_id,
                selected_project_id,
                selected_project_sqid,
            )
        )
        _request_properties_redraw()
    else:
        _complete_live_jobs_ticket(live_ticket)
    return jobs


def request_jobs(org_id: str, user_key: str, project_id: str):
    """Return persisted project jobs with live farm state overlaid when available."""
    global _last_job_refresh_context
    global _last_job_refresh_completed_at
    global _last_job_refresh_result

    refresh_started_at = time.monotonic()
    lifecycle_generation, session_generation = _current_refresh_identity()
    refresh_context = (
        lifecycle_generation,
        session_generation,
        str(org_id or "").strip(),
        str(user_key or "").strip(),
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
            user_key,
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


def _publish_pending_live_overlay() -> bool:
    """Commit one validated deferred result from Blender's main timer."""
    global _pending_live_overlay

    with _live_job_future_lock:
        overlay = _pending_live_overlay
        if overlay is None:
            return False

        _pending_live_overlay = None
        if (
            _ticket_is_current_locked(overlay.ticket)
            and _storage_context_values_match(
                overlay.org_id,
                overlay.user_key,
                overlay.requested_project_id,
                overlay.selected_project_id,
                overlay.selected_project_sqid,
            )
        ):
            current_jobs = Storage.data.get("jobs", {}) or {}
            Storage.data["jobs"] = _merge_job_sources(
                current_jobs,
                overlay.live_jobs,
                overlay.selected_project_id,
                overlay.selected_project_sqid,
                allow_live_only=False,
            )

        if _ticket_is_current_locked(overlay.ticket):
            _retire_live_job_future_locked()
    return True


def pulse():
    global _pulse_timer_registered

    with _live_job_future_lock:
        if not _refresh_infrastructure_enabled:
            _pulse_timer_registered = False
            return None

    published_overlay = _publish_pending_live_overlay()
    if published_overlay:
        _properties_redraw_requested.set()

    if _properties_redraw_requested.is_set():
        _properties_redraw_requested.clear()
        _redraw_properties_areas()

    if (
        Storage.enable_job_thread
        or Storage.jobs_updating
        or Storage.projects_updating
        or _live_job_redraw_pending.is_set()
    ):
        return _PULSE_ACTIVE_INTERVAL_SECONDS
    return _PULSE_IDLE_INTERVAL_SECONDS


def _ensure_pulse_timer() -> None:
    """Register the main-thread redraw handoff once for the active lifecycle."""
    global _pulse_timer_registered

    if threading.current_thread() is not threading.main_thread():
        return
    with _live_job_future_lock:
        if not _refresh_infrastructure_enabled or _pulse_timer_registered:
            return
        _pulse_timer_registered = True

    timers = bpy.app.timers
    is_registered = getattr(timers, "is_registered", None)
    try:
        if not callable(is_registered) or not is_registered(pulse):
            timers.register(pulse, first_interval=_PULSE_ACTIVE_INTERVAL_SECONDS)
    except Exception:
        with _live_job_future_lock:
            _pulse_timer_registered = False
        raise


def register_job_refresh_infrastructure() -> None:
    """Enable refresh workers and the main-thread handoff after add-on register."""
    global _auth_session_generation
    global _job_loop_stop_event
    global _live_job_executor
    global _observed_user_token
    global _refresh_infrastructure_enabled
    global _refresh_lifecycle_generation

    with _live_job_future_lock:
        if not _refresh_infrastructure_enabled:
            _refresh_lifecycle_generation += 1
            _auth_session_generation += 1
            _observed_user_token = str(Storage.data.get("user_token") or "")
            _job_loop_stop_event = threading.Event()
            _refresh_infrastructure_enabled = True
        if _live_job_executor is None:
            _live_job_executor = _create_live_job_executor()

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
    global _live_job_executor
    global _observed_user_token
    global _refresh_infrastructure_enabled
    global _refresh_lifecycle_generation

    Storage.enable_job_thread = False
    _job_loop_stop_event.set()
    with _live_job_future_lock:
        _refresh_infrastructure_enabled = False
        _refresh_lifecycle_generation += 1
        _auth_session_generation += 1
        _observed_user_token = str(Storage.data.get("user_token") or "")
        retired_future = _retire_live_job_future_locked()
        retired_executor = _live_job_executor
        _live_job_executor = None

    _cancel_retired_future(retired_future)
    if retired_executor is not None:
        retired_executor.shutdown(wait=False, cancel_futures=True)

    _properties_redraw_requested.clear()
    _unregister_pulse_timer()


def _refresh_lifecycle_is_active(lifecycle_generation: int) -> bool:
    with _live_job_future_lock:
        return (
            _refresh_infrastructure_enabled
            and lifecycle_generation == _refresh_lifecycle_generation
        )


def request_job_loop(
    org_id: str,
    user_key: str,
    project_id: str,
    lifecycle_generation: int | None = None,
    stop_event: threading.Event | None = None,
):
    global job_thread_running
    global _job_thread_generation

    if lifecycle_generation is None:
        lifecycle_generation = _refresh_lifecycle_generation
    if stop_event is None:
        stop_event = _job_loop_stop_event

    initial_context = (org_id, user_key, project_id)
    try:
        while (
            Storage.enable_job_thread
            and not stop_event.is_set()
            and _refresh_lifecycle_is_active(lifecycle_generation)
        ):
            current_context = (
                str(Storage.data.get("org_id") or "").strip(),
                str(Storage.data.get("user_key") or "").strip(),
                str(Storage.data.get("project_id") or "").strip(),
            )
            if not all(current_context):
                current_context = initial_context

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
            current_context = (
                str(Storage.data.get("org_id") or org_id).strip(),
                str(Storage.data.get("user_key") or user_key).strip(),
                str(Storage.data.get("project_id") or project_id).strip(),
            )
            _start_job_thread(*current_context)


def _start_job_thread(org_id: str, user_key: str, project_id: str) -> bool:
    global job_thread_running
    global _job_thread_generation

    with _live_job_future_lock:
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
                org_id,
                user_key,
                project_id,
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


def fetch_jobs(org_id: str, user_key: str, project_id: str, live_update: bool = False):
    if live_update:
        Storage.enable_job_thread = True
        _ensure_pulse_timer()
        if _start_job_thread(org_id, user_key, project_id):
            print("starting job thread")
    else:
        return request_jobs(org_id, user_key, project_id)
