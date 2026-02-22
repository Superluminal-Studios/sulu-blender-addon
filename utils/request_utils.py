from __future__ import annotations

import threading
import time
from typing import Optional

import bpy
import requests

from ..constants import POCKETBASE_URL
from ..pocketbase_auth import (
    AuthorizationError,
    NotAuthenticated,
    ResourceNotFound,
    TransportError,
    UpstreamServiceError,
    authorized_request,
)
from ..storage import Storage
from .refresh_service import RefreshService
from .worker_utils import requests_retry_session

job_thread_running = False  # legacy compatibility flag

_refresh_service: Optional[RefreshService] = None
_service_lock = threading.Lock()


def _addon_root(addon_package: str = "") -> str:
    if addon_package:
        return addon_package
    pkg = (__package__ or "").split(".")
    return pkg[0] if pkg else ""


def _get_addon_prefs(addon_package: str = ""):
    root = _addon_root(addon_package)
    if not root:
        return None
    try:
        container = bpy.context.preferences.addons.get(root)
        return container and container.preferences
    except Exception:
        return None


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
    Storage.panel_data["refresh_service_state"] = "running"


def _record_refresh_error(project_id: str, error: str) -> None:
    Storage.panel_data["last_jobs_refresh_at"] = time.time()
    Storage.panel_data["jobs_refresh_error"] = str(error)
    Storage.panel_data["jobs_refresh_project_id"] = project_id
    Storage.panel_data["refresh_service_state"] = "error"


def _record_projects_refresh_error(error: str) -> None:
    Storage.panel_data["projects_refresh_at"] = time.time()
    Storage.panel_data["projects_refresh_error"] = str(error)
    Storage.panel_data["refresh_service_state"] = "error"


def _raise_mapped_response_error(response: requests.Response) -> None:
    code = int(getattr(response, "status_code", 0) or 0)
    reason = getattr(response, "reason", "") or ""

    if code == 401:
        raise NotAuthenticated("Session expired. Sign in again.")
    if code == 403:
        raise AuthorizationError(f"Access denied (HTTP 403 {reason}).".strip())
    if code == 404:
        raise ResourceNotFound(f"Resource not found (HTTP 404 {reason}).".strip())
    if code >= 500:
        raise UpstreamServiceError(f"Service unavailable (HTTP {code} {reason}).".strip())
    if code >= 400:
        raise RuntimeError(f"Request failed (HTTP {code} {reason}).".strip())


def _authorized_request_with_token(
    method: str,
    url: str,
    *,
    token: str,
    session: Optional[requests.Session] = None,
    **kwargs,
) -> requests.Response:
    req_session = session or Storage.session
    headers = (kwargs.pop("headers", {}) or {}).copy()
    headers["Authorization"] = token

    try:
        response = req_session.request(
            method,
            url,
            headers=headers,
            timeout=Storage.timeout,
            **kwargs,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise TransportError(str(exc)) from exc
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            _raise_mapped_response_error(response)
        raise TransportError(str(exc)) from exc

    _raise_mapped_response_error(response)
    return response


def fetch_projects(session: Optional[requests.Session] = None):
    """Return all visible projects."""
    resp = authorized_request(
        "GET",
        f"{POCKETBASE_URL}/api/collections/projects/records",
        session=session,
    )
    return resp.json().get("items", [])


def get_render_queue_key(
    org_id: str,
    *,
    session: Optional[requests.Session] = None,
    token: Optional[str] = None,
) -> str:
    """Return the ``user_key`` for *org_id*'s render-queue."""
    if token:
        rq_resp = _authorized_request_with_token(
            "GET",
            f"{POCKETBASE_URL}/api/collections/render_queues/records",
            token=token,
            session=session,
            params={"filter": f"(organization_id='{org_id}')"},
        )
    else:
        rq_resp = authorized_request(
            "GET",
            f"{POCKETBASE_URL}/api/collections/render_queues/records",
            params={"filter": f"(organization_id='{org_id}')"},
            session=session,
        )

    items = rq_resp.json().get("items", [])
    if not items:
        raise RuntimeError(f"No render queue found for organization '{org_id}'")

    user_key = items[0].get("user_key")
    if not user_key:
        raise RuntimeError(f"Render queue key missing for organization '{org_id}'")
    return user_key


def request_jobs(
    org_id: str,
    user_key: str,
    project_id: str,
    *,
    session: Optional[requests.Session] = None,
    token: Optional[str] = None,
):
    """Fetch jobs from the farm API (network-only, no bpy mutations)."""
    if token:
        jobs_resp = _authorized_request_with_token(
            "GET",
            f"{POCKETBASE_URL}/farm/{org_id}/api/job_list",
            token=token,
            session=session,
            headers={"Auth-Token": user_key},
        )
    else:
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


def _scene_live_updates_enabled() -> bool:
    try:
        wm_settings = getattr(getattr(bpy.context, "scene", None), "sulu_wm_settings", None)
        return bool(getattr(wm_settings, "live_job_updates", False))
    except Exception:
        return False


def _current_project_from_prefs() -> str:
    prefs = _get_addon_prefs()
    if not prefs:
        return ""
    return str(getattr(prefs, "project_id", "") or "")


def _service_for_callbacks() -> Optional[RefreshService]:
    global _refresh_service
    return _refresh_service


def _on_jobs_success(project_id: str, jobs: dict, _source: str) -> None:
    _record_refresh_success(project_id, jobs if isinstance(jobs, dict) else {})


def _on_jobs_error(project_id: str, error: str, _source: str) -> None:
    _record_refresh_error(project_id, error)


def _on_projects_success(projects: list[dict], _source: str) -> None:
    normalized = projects if isinstance(projects, list) else []
    Storage.data["projects"] = normalized
    Storage.panel_data["projects_refresh_error"] = ""
    Storage.panel_data["projects_refresh_at"] = time.time()
    Storage.panel_data["refresh_service_state"] = "running"

    ids = {str(p.get("id", "") or "") for p in normalized}
    prefs = _get_addon_prefs()
    current_project = str(getattr(prefs, "project_id", "") or "") if prefs else ""
    if current_project and current_project in ids:
        selected_project_id = current_project
    elif normalized:
        selected_project_id = str(normalized[0].get("id", "") or "")
    else:
        selected_project_id = ""

    if prefs and str(getattr(prefs, "project_id", "") or "") != selected_project_id:
        prefs.project_id = selected_project_id

    service = _service_for_callbacks()
    if service:
        service.set_active_project(selected_project_id)
    Storage.save()


def _on_projects_error(error: str, _source: str) -> None:
    _record_projects_refresh_error(error)


def _login_bootstrap_fetcher(token: str, session: Optional[requests.Session]) -> dict:
    projects_resp = _authorized_request_with_token(
        "GET",
        f"{POCKETBASE_URL}/api/collections/projects/records",
        token=token,
        session=session,
    )
    projects = projects_resp.json().get("items", [])
    if not isinstance(projects, list):
        projects = []

    payload = {
        "projects": projects,
        "project_id": "",
        "org_id": "",
        "user_key": "",
        "jobs": {},
    }
    if not projects:
        return payload

    project = projects[0]
    project_id = str(project.get("id", "") or "")
    org_id = str(project.get("organization_id", "") or "")
    payload["project_id"] = project_id
    payload["org_id"] = org_id

    if not org_id or not project_id:
        return payload

    user_key = get_render_queue_key(org_id, token=token, session=session)
    payload["user_key"] = user_key
    payload["jobs"] = request_jobs(
        org_id,
        user_key,
        project_id,
        session=session,
        token=token,
    ) or {}
    return payload


def _on_login_success(payload: dict, _source: str) -> None:
    token = str(payload.get("token", "") or "")
    projects = payload.get("projects", [])
    project_id = str(payload.get("project_id", "") or "")
    org_id = str(payload.get("org_id", "") or "")
    user_key = str(payload.get("user_key", "") or "")
    jobs = payload.get("jobs", {})
    addon_package = str(payload.get("addon_package", "") or "")

    Storage.data["user_token"] = token
    Storage.data["user_token_time"] = int(time.time())
    Storage.data["projects"] = projects if isinstance(projects, list) else []
    Storage.data["org_id"] = org_id
    Storage.data["user_key"] = user_key
    Storage.data["jobs"] = jobs if isinstance(jobs, dict) else {}

    if project_id:
        _record_refresh_success(project_id, Storage.data["jobs"])
    else:
        _record_refresh_success("", {})

    Storage.panel_data["projects_refresh_error"] = ""
    Storage.panel_data["projects_refresh_at"] = time.time()
    Storage.panel_data["login_error"] = ""
    Storage.panel_data["refresh_service_state"] = "running"
    Storage.save()

    prefs = _get_addon_prefs(addon_package)
    if prefs is not None and str(getattr(prefs, "project_id", "") or "") != project_id:
        prefs.project_id = project_id

    service = _service_for_callbacks()
    if service:
        service.set_credentials(org_id, user_key)
        service.set_active_project(project_id)
        service.set_auto_refresh(_scene_live_updates_enabled())


def _on_login_error(error: str, _source: str) -> None:
    Storage.panel_data["login_error"] = str(error)
    _record_projects_refresh_error(error)


def _build_refresh_service() -> RefreshService:
    return RefreshService(
        jobs_fetcher=request_jobs,
        projects_fetcher=fetch_projects,
        session_factory=requests_retry_session,
        login_bootstrap_fetcher=_login_bootstrap_fetcher,
        on_jobs_success=_on_jobs_success,
        on_jobs_error=_on_jobs_error,
        on_projects_success=_on_projects_success,
        on_projects_error=_on_projects_error,
        on_login_success=_on_login_success,
        on_login_error=_on_login_error,
        on_ui_dirty=_tag_redraw,
        auto_refresh_interval=2.0,
    )


def _get_refresh_service() -> RefreshService:
    global _refresh_service
    with _service_lock:
        if _refresh_service is None:
            _refresh_service = _build_refresh_service()
    return _refresh_service


def start_refresh_service() -> None:
    service = _get_refresh_service()
    service.set_credentials(
        str(Storage.data.get("org_id", "") or ""),
        str(Storage.data.get("user_key", "") or ""),
    )
    service.set_active_project(_current_project_from_prefs())
    service.start()
    service.set_auto_refresh(_scene_live_updates_enabled())
    Storage.enable_job_thread = service.auto_refresh_enabled()
    Storage.panel_data["refresh_service_state"] = "running"


def stop_refresh_service() -> None:
    global _refresh_service
    with _service_lock:
        service = _refresh_service
        _refresh_service = None

    if service is not None:
        service.stop()
    Storage.enable_job_thread = False
    Storage.panel_data["refresh_service_state"] = "stopped"


def set_refresh_context(org_id: str, user_key: str, project_id: str) -> None:
    service = _get_refresh_service()
    service.set_credentials(org_id, user_key)
    service.set_active_project(project_id)


def set_active_project(project_id: str) -> None:
    _get_refresh_service().set_active_project(project_id)


def set_auto_refresh(enabled: bool) -> None:
    service = _get_refresh_service()
    service.set_auto_refresh(enabled)
    Storage.enable_job_thread = service.auto_refresh_enabled()


def request_jobs_refresh(
    *,
    org_id: Optional[str] = None,
    user_key: Optional[str] = None,
    project_id: Optional[str] = None,
    reason: str = "manual",
) -> bool:
    service = _get_refresh_service()

    if org_id is not None or user_key is not None:
        service.set_credentials(
            str(Storage.data.get("org_id", "") if org_id is None else org_id),
            str(Storage.data.get("user_key", "") if user_key is None else user_key),
        )
    if project_id is not None:
        service.set_active_project(project_id)

    return service.request_jobs_refresh(source=reason)


def request_projects_refresh(*, reason: str = "manual") -> bool:
    return _get_refresh_service().request_projects_refresh(source=reason)


def queue_login_bootstrap(token: str, *, addon_package: str = "") -> bool:
    return _get_refresh_service().queue_login_bootstrap(
        token,
        source="login",
        addon_package=_addon_root(addon_package),
    )


def stop_live_job_updates() -> None:
    set_auto_refresh(False)


def fetch_jobs(org_id: str, user_key: str, project_id: str, live_update: bool = False):
    if live_update:
        set_refresh_context(org_id, user_key, project_id)
        set_auto_refresh(True)
        request_jobs_refresh(reason="live-enable")
        return None

    try:
        jobs = request_jobs(org_id, user_key, project_id)
    except Exception as exc:
        _record_refresh_error(project_id, str(exc))
        raise

    _record_refresh_success(project_id, jobs)
    return jobs


def fetch_projects_async() -> bool:
    return request_projects_refresh(reason="manual")


def pulse():
    _tag_redraw()
    return 2 if Storage.enable_job_thread else None
