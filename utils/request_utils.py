from ..constants import POCKETBASE_URL
from ..pocketbase_auth import NotAuthenticated, NotFound, authorized_request
from ..storage import Storage
from .project_context import ProjectContextError
from .job_list import int_value as _int_value, job_project_ids, selected_project_ids
from .prefs import get_prefs
import time
import threading
import bpy
job_thread_running = False


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


def _request_stored_jobs(org_id: str) -> dict:
    resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/jobs/{org_id}",
    )
    if resp.status_code == 200 and resp.text:
        return resp.json().get("body", {}) or {}
    return {}


def _wake_queue_manager(org_id: str, user_key: str) -> None:
    authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/farm_status/{org_id}",
        headers={"Auth-Token": user_key},
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


def request_jobs(org_id: str, user_key: str, project_id: str):
    """Return persisted project jobs with live farm state overlaid when available."""
    # Worker threads update Storage only; Blender collections are rebuilt on the main thread.
    selected_project_id, selected_project_sqid = _selected_project_identity(project_id)

    stored_jobs = {}
    stored_jobs_available = False
    try:
        stored_jobs = _request_stored_jobs(org_id)
        stored_jobs_available = True
    except NotFound as exc:
        print(f"Stored jobs endpoint unavailable, falling back to live job list: {exc}")
    except NotAuthenticated:
        raise
    except Exception as exc:
        print(f"Could not fetch stored jobs, falling back to live job list: {exc}")

    live_jobs = {}
    try:
        live_jobs = _request_live_jobs(org_id, user_key)
    except Exception as exc:
        if not stored_jobs_available:
            raise
        print(f"Could not fetch live jobs; using stored jobs only: {exc}")

    jobs = _merge_job_sources(
        stored_jobs,
        live_jobs,
        selected_project_id,
        selected_project_sqid,
        allow_live_only=not stored_jobs_available,
    )
    Storage.data["jobs"] = jobs
    return jobs

def pulse():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    if not Storage.enable_job_thread:
        bpy.app.timers.unregister(pulse)
        return None
    return 2

def request_job_loop(org_id: str, user_key: str, project_id: str):
    global job_thread_running
    while Storage.enable_job_thread:
        request_jobs(org_id, user_key, project_id)
        time.sleep(2)
    job_thread_running = False

def fetch_jobs(org_id: str, user_key: str, project_id: str, live_update: bool = False):
    if live_update:
        global job_thread_running
        if not job_thread_running:
            bpy.app.timers.register(pulse, first_interval=0.5)
            print("starting job thread")
            Storage.enable_job_thread = True
            threading.Thread(target=request_job_loop, args=(org_id, user_key, project_id), daemon=True).start()
            job_thread_running = True
    else:
        return request_jobs(org_id, user_key, project_id)
