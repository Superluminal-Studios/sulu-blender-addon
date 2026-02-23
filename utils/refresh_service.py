from __future__ import annotations

import threading
import time
from queue import Empty, Queue
from typing import Callable, Optional

import requests

try:
    import bpy  # type: ignore
except Exception:  # pragma: no cover - bpy unavailable in unit tests
    bpy = None


JobsFetcher = Callable[..., dict]
ProjectsFetcher = Callable[[Optional[requests.Session]], list[dict]]
LoginBootstrapFetcher = Callable[[str, Optional[requests.Session]], dict]

JobsSuccessCallback = Callable[[str, dict, str], None]
JobsErrorCallback = Callable[[str, str, str], None]
ProjectsSuccessCallback = Callable[[list[dict], str], None]
ProjectsErrorCallback = Callable[[str, str], None]
LoginSuccessCallback = Callable[[dict, str], None]
LoginErrorCallback = Callable[[str, str], None]
UIDirtyCallback = Callable[[], None]


class RefreshService:
    """Queue-driven worker that fetches projects/jobs and applies results on main thread."""

    def __init__(
        self,
        *,
        jobs_fetcher: JobsFetcher,
        projects_fetcher: ProjectsFetcher,
        session_factory: Callable[[], requests.Session],
        login_bootstrap_fetcher: Optional[LoginBootstrapFetcher] = None,
        on_jobs_success: Optional[JobsSuccessCallback] = None,
        on_jobs_error: Optional[JobsErrorCallback] = None,
        on_projects_success: Optional[ProjectsSuccessCallback] = None,
        on_projects_error: Optional[ProjectsErrorCallback] = None,
        on_login_success: Optional[LoginSuccessCallback] = None,
        on_login_error: Optional[LoginErrorCallback] = None,
        on_ui_dirty: Optional[UIDirtyCallback] = None,
        auto_refresh_interval: float = 2.0,
    ):
        self._jobs_fetcher = jobs_fetcher
        self._projects_fetcher = projects_fetcher
        self._login_bootstrap_fetcher = login_bootstrap_fetcher
        self._session_factory = session_factory

        self._on_jobs_success = on_jobs_success
        self._on_jobs_error = on_jobs_error
        self._on_projects_success = on_projects_success
        self._on_projects_error = on_projects_error
        self._on_login_success = on_login_success
        self._on_login_error = on_login_error
        self._on_ui_dirty = on_ui_dirty

        self._auto_refresh_interval = max(0.5, float(auto_refresh_interval))
        self._state_lock = threading.Lock()
        self._commands: Queue[dict] = Queue()
        self._results: Queue[dict] = Queue()
        self._stop_event = threading.Event()

        self._worker: Optional[threading.Thread] = None
        self._timer_running = False
        self._running = False

        self._org_id = ""
        self._user_key = ""
        self._project_id = ""
        self._auto_refresh = False

        self._jobs_req_id = 0
        self._jobs_latest_id = 0
        self._projects_req_id = 0
        self._projects_latest_id = 0
        self._login_req_id = 0
        self._login_latest_id = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            self._ensure_apply_timer()
            return

        self._stop_event.clear()
        self._running = True
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="sulu-refresh-service",
            daemon=True,
        )
        self._worker.start()
        self._ensure_apply_timer()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        self._commands.put({"kind": "stop"})

        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.0)
        self._worker = None

        with self._state_lock:
            self._auto_refresh = False

        self.apply_pending_results()

    # ------------------------------------------------------------------
    # Context and request APIs
    # ------------------------------------------------------------------
    def set_credentials(self, org_id: str, user_key: str) -> None:
        with self._state_lock:
            self._org_id = str(org_id or "")
            self._user_key = str(user_key or "")

    def set_active_project(self, project_id: str) -> None:
        with self._state_lock:
            next_project_id = str(project_id or "")
            if next_project_id != self._project_id:
                # Invalidate in-flight job responses for the previous project.
                self._jobs_req_id += 1
                self._jobs_latest_id = self._jobs_req_id
            self._project_id = next_project_id

    def set_auto_refresh(self, enabled: bool) -> None:
        with self._state_lock:
            self._auto_refresh = bool(enabled)
        if enabled:
            self.start()
            self._ensure_apply_timer()

    def auto_refresh_enabled(self) -> bool:
        with self._state_lock:
            return bool(self._auto_refresh)

    def request_jobs_refresh(self, *, source: str = "manual") -> bool:
        with self._state_lock:
            org_id = self._org_id
            user_key = self._user_key
            project_id = self._project_id
            if not org_id or not user_key or not project_id:
                return False
            self._jobs_req_id += 1
            req_id = self._jobs_req_id
            self._jobs_latest_id = req_id

        self.start()
        self._commands.put(
            {
                "kind": "jobs",
                "request_id": req_id,
                "org_id": org_id,
                "user_key": user_key,
                "project_id": project_id,
                "source": source,
            }
        )
        self._ensure_apply_timer()
        return True

    def request_projects_refresh(self, *, source: str = "manual") -> bool:
        with self._state_lock:
            self._projects_req_id += 1
            req_id = self._projects_req_id
            self._projects_latest_id = req_id

        self.start()
        self._commands.put(
            {
                "kind": "projects",
                "request_id": req_id,
                "source": source,
            }
        )
        self._ensure_apply_timer()
        return True

    def queue_login_bootstrap(
        self,
        token: str,
        *,
        source: str = "login",
        addon_package: str = "",
    ) -> bool:
        if not self._login_bootstrap_fetcher or not token:
            return False

        with self._state_lock:
            self._login_req_id += 1
            req_id = self._login_req_id
            self._login_latest_id = req_id

        self.start()
        self._commands.put(
            {
                "kind": "login_bootstrap",
                "request_id": req_id,
                "source": source,
                "token": token,
                "addon_package": addon_package,
            }
        )
        self._ensure_apply_timer()
        return True

    # ------------------------------------------------------------------
    # Main-thread result application
    # ------------------------------------------------------------------
    def apply_pending_results(self) -> bool:
        changed = False

        while True:
            try:
                result = self._results.get_nowait()
            except Empty:
                break

            kind = result.get("kind", "")
            req_id = int(result.get("request_id") or 0)
            source = str(result.get("source", "") or "")

            if kind in {"jobs_success", "jobs_error"}:
                project_id = str(result.get("project_id", "") or "")
                with self._state_lock:
                    active_project = self._project_id
                    latest_id = self._jobs_latest_id

                if req_id < latest_id:
                    continue
                if active_project and project_id and active_project != project_id:
                    continue

                if kind == "jobs_success":
                    if self._on_jobs_success:
                        self._on_jobs_success(
                            project_id,
                            result.get("jobs", {}) or {},
                            source,
                        )
                else:
                    if self._on_jobs_error:
                        self._on_jobs_error(
                            project_id,
                            str(result.get("error", "Unknown error")),
                            source,
                        )
                changed = True
                continue

            if kind in {"projects_success", "projects_error"}:
                with self._state_lock:
                    latest_id = self._projects_latest_id

                if req_id < latest_id:
                    continue

                if kind == "projects_success":
                    if self._on_projects_success:
                        self._on_projects_success(result.get("projects", []) or [], source)
                else:
                    if self._on_projects_error:
                        self._on_projects_error(
                            str(result.get("error", "Unknown error")),
                            source,
                        )
                changed = True
                continue

            if kind in {"login_success", "login_error"}:
                with self._state_lock:
                    latest_id = self._login_latest_id

                if req_id < latest_id:
                    continue

                if kind == "login_success":
                    if self._on_login_success:
                        self._on_login_success(result.get("payload", {}) or {}, source)
                else:
                    if self._on_login_error:
                        self._on_login_error(
                            str(result.get("error", "Unknown error")),
                            source,
                        )
                changed = True

        if changed and self._on_ui_dirty:
            self._on_ui_dirty()
        return changed

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        session = self._session_factory()
        next_auto_at = time.monotonic()

        while not self._stop_event.is_set():
            timeout = 0.5
            should_auto = False
            auto_org = ""
            auto_key = ""
            auto_project = ""

            with self._state_lock:
                if self._auto_refresh and self._org_id and self._user_key and self._project_id:
                    should_auto = True
                    auto_org = self._org_id
                    auto_key = self._user_key
                    auto_project = self._project_id

            if should_auto:
                timeout = max(0.0, next_auto_at - time.monotonic())

            try:
                cmd = self._commands.get(timeout=timeout)
            except Empty:
                if should_auto:
                    with self._state_lock:
                        self._jobs_req_id += 1
                        req_id = self._jobs_req_id
                        self._jobs_latest_id = req_id
                    self._run_jobs_request(
                        req_id=req_id,
                        org_id=auto_org,
                        user_key=auto_key,
                        project_id=auto_project,
                        source="auto",
                        session=session,
                    )
                    next_auto_at = time.monotonic() + self._auto_refresh_interval
                continue

            kind = cmd.get("kind")
            if kind == "stop":
                break

            if kind == "jobs":
                self._run_jobs_request(
                    req_id=int(cmd.get("request_id") or 0),
                    org_id=str(cmd.get("org_id", "") or ""),
                    user_key=str(cmd.get("user_key", "") or ""),
                    project_id=str(cmd.get("project_id", "") or ""),
                    source=str(cmd.get("source", "manual") or "manual"),
                    session=session,
                )
                next_auto_at = time.monotonic() + self._auto_refresh_interval
                continue

            if kind == "projects":
                self._run_projects_request(
                    req_id=int(cmd.get("request_id") or 0),
                    source=str(cmd.get("source", "manual") or "manual"),
                    session=session,
                )
                continue

            if kind == "login_bootstrap":
                self._run_login_bootstrap(
                    req_id=int(cmd.get("request_id") or 0),
                    source=str(cmd.get("source", "login") or "login"),
                    token=str(cmd.get("token", "") or ""),
                    addon_package=str(cmd.get("addon_package", "") or ""),
                    session=session,
                )

    def _run_jobs_request(
        self,
        *,
        req_id: int,
        org_id: str,
        user_key: str,
        project_id: str,
        source: str,
        session: requests.Session,
    ) -> None:
        try:
            # Pass session by keyword to support fetchers that declare it keyword-only.
            jobs = self._jobs_fetcher(
                org_id,
                user_key,
                project_id,
                session=session,
            )
            self._results.put(
                {
                    "kind": "jobs_success",
                    "request_id": req_id,
                    "source": source,
                    "project_id": project_id,
                    "jobs": jobs if isinstance(jobs, dict) else {},
                }
            )
        except Exception as exc:  # pragma: no cover - exercised via unit tests
            self._results.put(
                {
                    "kind": "jobs_error",
                    "request_id": req_id,
                    "source": source,
                    "project_id": project_id,
                    "error": str(exc),
                }
            )

    def _run_projects_request(
        self,
        *,
        req_id: int,
        source: str,
        session: requests.Session,
    ) -> None:
        try:
            projects = self._projects_fetcher(session)
            self._results.put(
                {
                    "kind": "projects_success",
                    "request_id": req_id,
                    "source": source,
                    "projects": projects if isinstance(projects, list) else [],
                }
            )
        except Exception as exc:  # pragma: no cover - exercised via unit tests
            self._results.put(
                {
                    "kind": "projects_error",
                    "request_id": req_id,
                    "source": source,
                    "error": str(exc),
                }
            )

    def _run_login_bootstrap(
        self,
        *,
        req_id: int,
        source: str,
        token: str,
        addon_package: str,
        session: requests.Session,
    ) -> None:
        if not self._login_bootstrap_fetcher:
            return

        try:
            payload = self._login_bootstrap_fetcher(token, session)
            payload = payload if isinstance(payload, dict) else {}
            payload["token"] = token
            payload["addon_package"] = addon_package
            self._results.put(
                {
                    "kind": "login_success",
                    "request_id": req_id,
                    "source": source,
                    "payload": payload,
                }
            )
        except Exception as exc:  # pragma: no cover - exercised via unit tests
            self._results.put(
                {
                    "kind": "login_error",
                    "request_id": req_id,
                    "source": source,
                    "error": str(exc),
                }
            )

    # ------------------------------------------------------------------
    # Timer integration
    # ------------------------------------------------------------------
    def _ensure_apply_timer(self) -> None:
        if self._timer_running:
            return
        if bpy is None:
            return
        try:
            bpy.app.timers.register(self._timer_tick, first_interval=0.1)
            self._timer_running = True
        except Exception:
            self._timer_running = False

    def _timer_tick(self):
        self.apply_pending_results()
        if self._running or not self._results.empty():
            return 0.25
        self._timer_running = False
        return None
