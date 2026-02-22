from __future__ import annotations

import random
import threading
import time
from queue import Empty, Queue
from typing import Optional

import bpy
import requests

from ..constants import POCKETBASE_URL
from ..pocketbase_auth import authorized_request
from ..storage import Storage
from .worker_utils import requests_retry_session

job_thread_running = False

_job_thread_lock = threading.Lock()
_job_target = {
    "org_id": "",
    "user_key": "",
    "project_id": "",
}
_job_results: Queue[tuple[str, dict]] = Queue()
_apply_timer_running = False
_thread_session: Optional[requests.Session] = None

def fetch_projects():
    """Return all visible projects."""
    resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/collections/projects/records",
    )
    return resp.json()["items"]


def get_render_queue_key(org_id: str) -> str:
    """Return the ``user_key`` for *org_id*'s render‑queue."""
    rq_resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/collections/render_queues/records",
        params={"filter": f"(organization_id='{org_id}')"},
    )
    items = rq_resp.json().get("items", [])
    if not items:
        raise RuntimeError(f"No render queue found for organization '{org_id}'")

    user_key = items[0].get("user_key")
    if not user_key:
        raise RuntimeError(f"Render queue key missing for organization '{org_id}'")
    return user_key


def _tag_redraw() -> None:
    """Best-effort redraw request for all visible Blender areas."""
    try:
        wm = bpy.context.window_manager
    except Exception:
        return

    for window in getattr(wm, "windows", []):
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            area.tag_redraw()


def _record_refresh_success(project_id: str, jobs: dict) -> None:
    Storage.data["jobs"] = jobs
    Storage.panel_data["last_jobs_refresh_at"] = time.time()
    Storage.panel_data["jobs_refresh_error"] = ""
    Storage.panel_data["jobs_refresh_project_id"] = project_id


def _record_refresh_error(project_id: str, error: str) -> None:
    Storage.panel_data["last_jobs_refresh_at"] = time.time()
    Storage.panel_data["jobs_refresh_error"] = str(error)
    Storage.panel_data["jobs_refresh_project_id"] = project_id


def _get_thread_session() -> requests.Session:
    global _thread_session
    if _thread_session is None:
        _thread_session = requests_retry_session()
    return _thread_session


def _drain_job_results() -> bool:
    """Apply pending thread results on Blender's main thread."""
    changed = False
    while True:
        try:
            kind, payload = _job_results.get_nowait()
        except Empty:
            break

        project_id = str(payload.get("project_id", "") or "")
        if kind == "jobs":
            _record_refresh_success(project_id, payload.get("jobs", {}))
            changed = True
        elif kind == "error":
            _record_refresh_error(project_id, payload.get("error", "Unknown error"))
            changed = True

    if changed:
        _tag_redraw()
    return changed


def _apply_results_timer():
    global _apply_timer_running

    _drain_job_results()
    if not Storage.enable_job_thread and _job_results.empty():
        _apply_timer_running = False
        return None

    return 0.5


def _ensure_apply_timer() -> None:
    global _apply_timer_running
    if _apply_timer_running:
        return
    bpy.app.timers.register(_apply_results_timer, first_interval=0.1)
    _apply_timer_running = True


def request_jobs(
    org_id: str,
    user_key: str,
    project_id: str,
    *,
    session: Optional[requests.Session] = None,
):
    """Fetch jobs from the farm API (network-only, no bpy mutations)."""
    jobs_resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/farm/{org_id}/api/job_list",
        headers={"Auth-Token": user_key},
        session=session,
    )
    if jobs_resp.status_code != 200:
        return {}

    if jobs_resp.text == "":
        return {}

    jobs = jobs_resp.json().get("body", {})
    return jobs if isinstance(jobs, dict) else {}

def pulse():
    _tag_redraw()
    if not Storage.enable_job_thread:
        return None
    return 2


def _sleep_with_jitter(seconds: float) -> None:
    jittered = max(0.25, seconds + random.uniform(-0.3, 0.3))
    time.sleep(jittered)


def request_job_loop(org_id: str, user_key: str, project_id: str):
    global job_thread_running
    with _job_thread_lock:
        _job_target["org_id"] = org_id
        _job_target["user_key"] = user_key
        _job_target["project_id"] = project_id

    consecutive_failures = 0
    while Storage.enable_job_thread:
        with _job_thread_lock:
            target_org = _job_target["org_id"]
            target_key = _job_target["user_key"]
            target_project = _job_target["project_id"]

        if not target_org or not target_key or not target_project:
            _sleep_with_jitter(1.0)
            continue

        try:
            jobs = request_jobs(
                target_org,
                target_key,
                target_project,
                session=_get_thread_session(),
            )
            _job_results.put(
                (
                    "jobs",
                    {
                        "project_id": target_project,
                        "jobs": jobs,
                    },
                )
            )
            consecutive_failures = 0
            _sleep_with_jitter(2.0)
        except Exception as exc:
            consecutive_failures += 1
            backoff = min(10.0, 2.0 * (2 ** (consecutive_failures - 1)))
            _job_results.put(
                (
                    "error",
                    {
                        "project_id": target_project,
                        "error": str(exc),
                    },
                )
            )
            _sleep_with_jitter(backoff)

    job_thread_running = False


def stop_live_job_updates() -> None:
    Storage.enable_job_thread = False
    _ensure_apply_timer()


def fetch_jobs(org_id: str, user_key: str, project_id: str, live_update: bool = False):
    if live_update:
        global job_thread_running
        with _job_thread_lock:
            _job_target["org_id"] = org_id
            _job_target["user_key"] = user_key
            _job_target["project_id"] = project_id

        Storage.enable_job_thread = True
        _ensure_apply_timer()
        if not job_thread_running:
            threading.Thread(
                target=request_job_loop,
                args=(org_id, user_key, project_id),
                daemon=True,
            ).start()
            job_thread_running = True
        return None

    try:
        jobs = request_jobs(org_id, user_key, project_id)
    except Exception as exc:
        _record_refresh_error(project_id, str(exc))
        raise

    _record_refresh_success(project_id, jobs)
    return jobs
