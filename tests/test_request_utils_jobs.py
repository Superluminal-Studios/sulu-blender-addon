from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import importlib
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent

if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace(
        context=types.SimpleNamespace(
            preferences=types.SimpleNamespace(addons={}),
            window_manager=types.SimpleNamespace(windows=[]),
        ),
        app=types.SimpleNamespace(timers=types.SimpleNamespace(register=lambda *a, **k: None)),
    )

pkg = types.ModuleType("sulu_blender_addon")
pkg.__path__ = [str(_addon_dir)]
pkg.__file__ = str(_addon_dir / "__init__.py")
sys.modules.setdefault("sulu_blender_addon", pkg)

request_utils = importlib.import_module("sulu_blender_addon.utils.request_utils")
pocketbase_auth = importlib.import_module("sulu_blender_addon.pocketbase_auth")


class _FakeResponse:
    def __init__(self, payload, *, status_code=200, text="json"):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakePrefs:
    def __init__(self):
        self.jobs = []


class _StatusResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        raise AssertionError("Mapped statuses must not use the generic HTTP error")


class TestRequestUtilsJobs(unittest.TestCase):
    def test_pocketbase_status_exception_taxonomy(self):
        cases = (
            (401, pocketbase_auth.NotAuthenticated),
            (403, pocketbase_auth.NotAuthenticated),
            (404, pocketbase_auth.NotFound),
            (410, pocketbase_auth.NotFound),
            (500, pocketbase_auth.ServerError),
            (503, pocketbase_auth.ServerError),
        )

        for status_code, expected_exception in cases:
            with self.subTest(status_code=status_code):
                with self.assertRaises(expected_exception):
                    pocketbase_auth._raise_classified_status(
                        _StatusResponse(status_code)
                    )

    def test_logged_session_request_only_locks_the_shared_session(self):
        class _Session:
            def __init__(self):
                self.calls = 0

            def request(self, _method, _url, **_kwargs):
                self.calls += 1
                return _FakeResponse({})

        class _CountingLock:
            def __init__(self):
                self.entries = 0

            def __enter__(self):
                self.entries += 1

            def __exit__(self, _exc_type, _exc, _traceback):
                return False

        shared_session = _Session()
        isolated_session = _Session()
        session_lock = _CountingLock()

        with patch.object(pocketbase_auth.Storage, "session", shared_session), patch.object(
            pocketbase_auth.Storage,
            "session_lock",
            session_lock,
        ):
            pocketbase_auth.logged_session_request(
                shared_session,
                "GET",
                "https://example.invalid/shared",
            )
            pocketbase_auth.logged_session_request(
                isolated_session,
                "GET",
                "https://example.invalid/isolated",
            )

        self.assertEqual(session_lock.entries, 1)
        self.assertEqual(shared_session.calls, 1)
        self.assertEqual(isolated_session.calls, 1)

    def test_concurrent_isolated_requests_refresh_token_once_and_close_sessions(self):
        class _RefreshSession:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                return _FakeResponse({"token": "refreshed-token"})

        class _IsolatedSession:
            def __init__(self):
                self.authorization = ""
                self.closed = False

            def request(self, _method, _url, **kwargs):
                self.authorization = kwargs["headers"]["Authorization"]
                return _FakeResponse({"ok": True})

            def close(self):
                self.closed = True

        shared_session = _RefreshSession()
        isolated_sessions = []
        factory_lock = threading.Lock()
        start = threading.Barrier(2)

        def _new_isolated_session():
            session = _IsolatedSession()
            with factory_lock:
                isolated_sessions.append(session)
            return session

        def _request():
            start.wait(timeout=1)
            return pocketbase_auth.authorized_request(
                "GET",
                "https://example.invalid/jobs",
                isolated_session=True,
            )

        with patch.dict(
            pocketbase_auth.Storage.data,
            {"user_token": "expired-token", "user_token_time": 1},
        ), patch.object(
            pocketbase_auth.Storage,
            "session",
            shared_session,
        ), patch.object(
            pocketbase_auth.Storage,
            "session_lock",
            threading.Lock(),
        ), patch.object(
            pocketbase_auth.Storage,
            "save",
        ) as save, patch.object(
            pocketbase_auth,
            "_new_isolated_session",
            side_effect=_new_isolated_session,
        ), ThreadPoolExecutor(max_workers=2) as executor:
            responses = [executor.submit(_request) for _ in range(2)]
            for response in responses:
                self.assertEqual(response.result().json(), {"ok": True})

            self.assertEqual(
                pocketbase_auth.Storage.data["user_token"],
                "refreshed-token",
            )

        self.assertEqual(len(shared_session.calls), 1)
        self.assertEqual(shared_session.calls[0][0], "POST")
        self.assertTrue(shared_session.calls[0][1].endswith("/auth-refresh"))
        self.assertEqual(
            shared_session.calls[0][2]["headers"]["Authorization"],
            "expired-token",
        )
        save.assert_called_once_with()
        self.assertEqual(len(isolated_sessions), 2)
        self.assertTrue(all(session.closed for session in isolated_sessions))
        self.assertEqual(
            {session.authorization for session in isolated_sessions},
            {"refreshed-token"},
        )

    def test_stored_job_requests_reuse_one_serialized_session(self):
        class _StoredJobSession:
            def __init__(self):
                self.calls = []
                self.active_requests = 0
                self.max_active_requests = 0
                self.first_request_started = threading.Event()
                self.release_first_request = threading.Event()
                self.closed = False

            def request(self, method, url, **kwargs):
                self.active_requests += 1
                self.max_active_requests = max(
                    self.max_active_requests,
                    self.active_requests,
                )
                self.calls.append((method, url, kwargs))
                if len(self.calls) == 1:
                    self.first_request_started.set()
                    self.release_first_request.wait(timeout=1)
                self.active_requests -= 1
                return _FakeResponse({"ok": True})

            def close(self):
                self.closed = True

        session = _StoredJobSession()
        second_request_started = threading.Event()

        def _second_request():
            second_request_started.set()
            return pocketbase_auth.authorized_request(
                "GET",
                "https://example.invalid/jobs/second",
                stored_job_session=True,
            )

        pocketbase_auth.reset_stored_job_session()
        try:
            with patch.dict(
                pocketbase_auth.Storage.data,
                {"user_token": "token", "user_token_time": int(time.time())},
            ), patch.object(
                pocketbase_auth,
                "_new_isolated_session",
                return_value=session,
            ) as session_factory, ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(
                    pocketbase_auth.authorized_request,
                    "GET",
                    "https://example.invalid/jobs/first",
                    stored_job_session=True,
                )
                self.assertTrue(session.first_request_started.wait(timeout=1))
                second = executor.submit(_second_request)
                self.assertTrue(second_request_started.wait(timeout=1))
                self.assertEqual(len(session.calls), 1)
                session.release_first_request.set()
                self.assertEqual(first.result().json(), {"ok": True})
                self.assertEqual(second.result().json(), {"ok": True})

            session_factory.assert_called_once_with()
            self.assertEqual(session.max_active_requests, 1)
            self.assertFalse(session.closed)
            self.assertEqual(
                [call[2]["headers"]["Authorization"] for call in session.calls],
                ["token", "token"],
            )
        finally:
            pocketbase_auth.reset_stored_job_session()

        self.assertTrue(session.closed)

    def test_active_stored_job_session_is_retired_without_blocking_and_recreated(self):
        class _StoredJobSession:
            def __init__(self, *, block=False):
                self.block = block
                self.started = threading.Event()
                self.release = threading.Event()
                self.closed = False

            def request(self, _method, _url, **_kwargs):
                self.started.set()
                if self.block:
                    self.release.wait(timeout=5)
                return _FakeResponse({"ok": True})

            def close(self):
                self.closed = True

        first_session = _StoredJobSession(block=True)
        second_session = _StoredJobSession()
        pocketbase_auth.reset_stored_job_session()
        try:
            with patch.dict(
                pocketbase_auth.Storage.data,
                {"user_token": "token", "user_token_time": int(time.time())},
            ), patch.object(
                pocketbase_auth,
                "_new_isolated_session",
                side_effect=[first_session, second_session],
            ) as session_factory, ThreadPoolExecutor(max_workers=2) as executor:
                request = executor.submit(
                    pocketbase_auth.authorized_request,
                    "GET",
                    "https://example.invalid/jobs/active",
                    stored_job_session=True,
                )
                self.assertTrue(first_session.started.wait(timeout=1))

                reset = executor.submit(pocketbase_auth.reset_stored_job_session)
                self.assertIsNone(reset.result(timeout=0.5))
                self.assertFalse(first_session.closed)

                first_session.release.set()
                self.assertEqual(request.result().json(), {"ok": True})
                self.assertTrue(first_session.closed)

                response = pocketbase_auth.authorized_request(
                    "GET",
                    "https://example.invalid/jobs/recreated",
                    stored_job_session=True,
                )
                self.assertEqual(response.json(), {"ok": True})

            self.assertEqual(session_factory.call_count, 2)
        finally:
            first_session.release.set()
            pocketbase_auth.reset_stored_job_session()

        self.assertTrue(second_session.closed)

    def test_stored_job_unauthorized_response_clears_auth_and_session(self):
        class _StoredJobSession:
            def __init__(self):
                self.authorization = ""
                self.closed = False

            def request(self, _method, _url, **kwargs):
                self.authorization = kwargs["headers"]["Authorization"]
                return _StatusResponse(401)

            def close(self):
                self.closed = True

        session = _StoredJobSession()
        pocketbase_auth.reset_stored_job_session()
        try:
            with patch.dict(
                pocketbase_auth.Storage.data,
                {"user_token": "token", "user_token_time": int(time.time())},
            ), patch.object(
                pocketbase_auth,
                "_new_isolated_session",
                return_value=session,
            ), patch.object(
                pocketbase_auth.Storage,
                "clear",
            ) as clear:
                with self.assertRaisesRegex(
                    pocketbase_auth.NotAuthenticated,
                    "Session expired",
                ):
                    pocketbase_auth.authorized_request(
                        "GET",
                        "https://example.invalid/jobs",
                        stored_job_session=True,
                    )

            clear.assert_called_once_with()
            self.assertEqual(session.authorization, "token")
            self.assertTrue(session.closed)
        finally:
            pocketbase_auth.reset_stored_job_session()

    def test_fetch_projects_requests_every_pocketbase_page(self):
        payloads = [
            {
                "page": 1,
                "perPage": 2,
                "totalPages": 3,
                "items": [{"id": "project-1"}],
            },
            {
                "page": 2,
                "perPage": 2,
                "totalPages": 3,
                "items": [{"id": "project-2"}],
            },
            {
                "page": 3,
                "perPage": 2,
                "totalPages": 3,
                "items": [{"id": "project-3"}],
            },
        ]
        calls = []

        def _authorized_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse(payloads[len(calls) - 1])

        with (
            patch.object(request_utils, "_PROJECTS_PER_PAGE", 2),
            patch.object(
                request_utils,
                "authorized_request",
                side_effect=_authorized_request,
            ),
        ):
            projects = request_utils.fetch_projects()

        self.assertEqual(
            projects,
            [{"id": "project-1"}, {"id": "project-2"}, {"id": "project-3"}],
        )
        self.assertEqual(
            [call[2]["params"] for call in calls],
            [
                {"page": 1, "perPage": 2},
                {"page": 2, "perPage": 2},
                {"page": 3, "perPage": 2},
            ],
        )

    def test_fetch_projects_accepts_legacy_single_page_payload(self):
        with patch.object(
            request_utils,
            "authorized_request",
            return_value=_FakeResponse({"items": [{"id": "project-1"}]}),
        ):
            self.assertEqual(
                request_utils.fetch_projects(),
                [{"id": "project-1"}],
            )

    def test_selected_project_identity_returns_id_and_sqid(self):
        original = request_utils.Storage.data.get("projects")
        try:
            request_utils.Storage.data["projects"] = [
                {"id": "project-id", "sqid": "project-sqid"},
            ]

            self.assertEqual(
                request_utils._selected_project_identity("project-id"),
                ("project-id", "project-sqid"),
            )
            self.assertEqual(
                request_utils._selected_project_identity("project-sqid"),
                ("project-id", "project-sqid"),
            )
        finally:
            request_utils.Storage.data["projects"] = original

    def test_stored_jobs_request_is_project_scoped_and_bounded(self):
        with patch.object(
            request_utils,
            "authorized_request",
            return_value=_FakeResponse({"body": {}}),
        ) as authorized_request:
            request_utils._request_stored_jobs(
                "org-id",
                "project-id",
                37,
            )

        authorized_request.assert_called_once_with(
            "GET",
            f"{request_utils.POCKETBASE_URL}/api/jobs/org-id",
            params={
                "limit": 37,
                "view": "addon",
                "project_id": "project-id",
            },
            stored_job_session=True,
        )

    def test_request_jobs_fetches_stored_and_live_sources_concurrently(self):
        rendezvous = threading.Barrier(2)
        stored_call = {}

        def _stored(org_id, project_id, limit):
            stored_call["args"] = (org_id, project_id, limit)
            rendezvous.wait(timeout=1)
            return {}

        def _live(_org_id, _user_key):
            rendezvous.wait(timeout=1)
            return {}

        with patch.object(
            request_utils,
            "_selected_project_identity",
            return_value=("project-concurrent-stable", "project-concurrent-public"),
        ), patch.object(
            request_utils,
            "_request_stored_jobs",
            side_effect=_stored,
        ), patch.object(
            request_utils,
            "_request_live_jobs",
            side_effect=_live,
        ):
            jobs = request_utils.request_jobs(
                "org-concurrent",
                "user-key-concurrent",
                "project-concurrent-public",
            )

        self.assertEqual(jobs, {})
        self.assertEqual(
            stored_call["args"],
            (
                "org-concurrent",
                "project-concurrent-stable",
                request_utils._STORED_JOBS_LIMIT,
            ),
        )

    def test_request_jobs_shows_stored_results_before_slow_live_overlay(self):
        live_started = threading.Event()
        release_live = threading.Event()
        stored = {
            "job-deferred": {
                "id": "job-deferred",
                "project_id": "project-deferred-stable",
                "status": "finished",
            },
        }
        live = {
            "job-deferred": {
                "id": "job-deferred",
                "project_id": "project-deferred-stable",
                "status": "running",
                "tasks": {"running": 1},
            },
        }

        def _slow_live(_org_id, _user_key):
            live_started.set()
            if not release_live.wait(timeout=1):
                raise TimeoutError("test did not release live response")
            return live

        with patch.dict(
            request_utils.Storage.data,
            {
                "user_token": "token",
                "org_id": "org-deferred",
                "project_id": "project-deferred-public",
                "jobs": {},
            },
        ), patch.object(
            request_utils,
            "_selected_project_identity",
            return_value=("project-deferred-stable", "project-deferred-public"),
        ), patch.object(
            request_utils,
            "_request_stored_jobs",
            return_value=stored,
        ), patch.object(
            request_utils,
            "_request_live_jobs",
            side_effect=_slow_live,
        ):
            jobs = request_utils.request_jobs(
                "org-deferred",
                "user-key-deferred",
                "project-deferred-public",
            )

            try:
                self.assertTrue(live_started.wait(timeout=0.5))
                self.assertEqual(jobs["job-deferred"]["status"], "finished")
                self.assertEqual(
                    request_utils.Storage.data["jobs"]["job-deferred"]["status"],
                    "finished",
                )
            finally:
                release_live.set()

            deadline = time.monotonic() + 1
            while (
                request_utils.Storage.data["jobs"]["job-deferred"]["status"]
                != "running"
                and time.monotonic() < deadline
            ):
                request_utils.pulse()
                time.sleep(0.01)

            self.assertEqual(
                request_utils.Storage.data["jobs"]["job-deferred"]["status"],
                "running",
            )

    def test_overlapping_refreshes_for_same_context_are_coalesced(self):
        rendezvous = threading.Barrier(2)
        monotonic_lock = threading.Lock()
        monotonic_calls = 0
        real_monotonic = request_utils.time.monotonic

        def _monotonic():
            nonlocal monotonic_calls
            value = real_monotonic()
            with monotonic_lock:
                monotonic_calls += 1
                call_number = monotonic_calls
            if call_number <= 2:
                rendezvous.wait(timeout=1)
            return value

        result = {"job-1": {"status": "running"}}
        with patch.object(
            request_utils.time,
            "monotonic",
            side_effect=_monotonic,
        ), patch.object(
            request_utils,
            "_request_jobs_unlocked",
            return_value=result,
        ) as request_jobs_unlocked, ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    request_utils.request_jobs,
                    "org-coalesced",
                    "user-key-coalesced",
                    "project-coalesced",
                )
                for _ in range(2)
            ]
            results = [future.result() for future in futures]

        self.assertEqual(results, [result, result])
        request_jobs_unlocked.assert_called_once_with(
            "org-coalesced",
            "user-key-coalesced",
            "project-coalesced",
            refresh_identity=(
                request_utils._refresh_lifecycle_generation,
                request_utils._auth_session_generation,
            ),
        )

    def test_start_job_thread_keeps_a_single_refresh_loop(self):
        original_running = request_utils.job_thread_running
        original_generation = request_utils._job_thread_generation
        request_utils.job_thread_running = False
        try:
            with patch.object(request_utils.threading, "Thread") as thread_constructor:
                self.assertTrue(
                    request_utils._start_job_thread(
                        "org-id",
                        "user-key",
                        "project-id",
                    )
                )
                self.assertFalse(
                    request_utils._start_job_thread(
                        "org-id",
                        "user-key",
                        "project-id",
                    )
                )

            thread_constructor.assert_called_once()
            thread_constructor.return_value.start.assert_called_once_with()
        finally:
            request_utils.job_thread_running = original_running
            request_utils._job_thread_generation = original_generation

    def test_enabling_live_refresh_always_restores_redraw_timer(self):
        original_enabled = request_utils.Storage.enable_job_thread
        try:
            with patch.object(
                request_utils,
                "_start_job_thread",
                side_effect=[True, False],
            ) as start_job_thread, patch.object(
                request_utils,
                "_ensure_pulse_timer",
            ) as ensure_pulse_timer:
                request_utils.fetch_jobs(
                    "org-id",
                    "user-key",
                    "project-id",
                    live_update=True,
                )
                request_utils.fetch_jobs(
                    "org-id",
                    "user-key",
                    "project-id",
                    live_update=True,
                )

            self.assertEqual(start_job_thread.call_count, 2)
            self.assertEqual(ensure_pulse_timer.call_count, 2)
        finally:
            request_utils.Storage.enable_job_thread = original_enabled

    def test_job_loop_uses_current_context_and_work_plus_interval_cadence(self):
        original_enabled = request_utils.Storage.enable_job_thread
        original_running = request_utils.job_thread_running
        original_generation = request_utils._job_thread_generation
        lifecycle_generation = request_utils._refresh_lifecycle_generation
        stop_event = threading.Event()
        request_utils.Storage.enable_job_thread = True
        request_utils.job_thread_running = True
        request_utils._job_thread_generation = lifecycle_generation

        def _request_jobs(*_args):
            request_utils.Storage.enable_job_thread = False
            return {}

        try:
            with patch.dict(
                request_utils.Storage.data,
                {
                    "org_id": "org-current",
                    "user_key": "user-key-current",
                    "project_id": "project-current",
                },
            ), patch.object(
                request_utils,
                "request_jobs",
                side_effect=_request_jobs,
            ) as request_jobs, patch.object(
                stop_event,
                "wait",
                return_value=False,
            ) as wait:
                request_utils.request_job_loop(
                    "org-old",
                    "user-key-old",
                    "project-old",
                    lifecycle_generation,
                    stop_event,
                )

            request_jobs.assert_called_once_with(
                "org-current",
                "user-key-current",
                "project-current",
            )
            wait.assert_called_once_with(request_utils._JOB_REFRESH_INTERVAL_SECONDS)
        finally:
            request_utils.Storage.enable_job_thread = original_enabled
            request_utils.job_thread_running = original_running
            request_utils._job_thread_generation = original_generation

    def test_live_jobs_empty_response_preserves_wake_and_retry(self):
        responses = [
            _FakeResponse({}, text=""),
            _FakeResponse({"body": {"job-1": {"status": "running"}}}),
        ]
        with patch.object(
            request_utils,
            "authorized_request",
            side_effect=responses,
        ) as authorized_request, patch.object(
            request_utils,
            "_wake_queue_manager",
        ) as wake_queue_manager:
            jobs = request_utils._request_live_jobs("org-id", "user-key")

        self.assertEqual(jobs["job-1"]["status"], "running")
        wake_queue_manager.assert_called_once_with("org-id", "user-key")
        self.assertEqual(authorized_request.call_count, 2)
        for call in authorized_request.call_args_list:
            self.assertTrue(call.kwargs["isolated_session"])

    def test_aba_old_live_ticket_cannot_replace_newer_same_context(self):
        old_future = Future()
        old_future.set_result(
            {"job-a": {"project_id": "project-a", "status": "running"}}
        )
        new_future = Future()
        old_ticket = request_utils._LiveJobTicket(
            future=old_future,
            context=("org-a", "user-key-a"),
            request_generation=41,
            session_generation=7,
            lifecycle_generation=3,
        )

        with request_utils._live_job_future_lock:
            snapshot = (
                request_utils._refresh_infrastructure_enabled,
                request_utils._refresh_lifecycle_generation,
                request_utils._auth_session_generation,
                request_utils._live_job_future,
                request_utils._live_job_future_context,
                request_utils._live_job_future_generation,
                request_utils._pending_live_overlay,
            )
            request_utils._refresh_infrastructure_enabled = True
            request_utils._refresh_lifecycle_generation = 3
            request_utils._auth_session_generation = 7
            request_utils._live_job_future = new_future
            request_utils._live_job_future_context = ("org-a", "user-key-a")
            request_utils._live_job_future_generation = 42
            request_utils._pending_live_overlay = None

        try:
            with patch.dict(
                request_utils.Storage.data,
                {
                    "org_id": "org-a",
                    "user_key": "user-key-a",
                    "project_id": "project-a",
                    "jobs": {"job-a": {"status": "finished"}},
                },
            ):
                request_utils._apply_deferred_live_jobs(
                    old_future,
                    old_ticket,
                    "org-a",
                    "user-key-a",
                    "project-a",
                    "project-a",
                    "",
                )

                self.assertIsNone(request_utils._pending_live_overlay)
                self.assertEqual(
                    request_utils.Storage.data["jobs"]["job-a"]["status"],
                    "finished",
                )
        finally:
            with request_utils._live_job_future_lock:
                (
                    request_utils._refresh_infrastructure_enabled,
                    request_utils._refresh_lifecycle_generation,
                    request_utils._auth_session_generation,
                    request_utils._live_job_future,
                    request_utils._live_job_future_context,
                    request_utils._live_job_future_generation,
                    request_utils._pending_live_overlay,
                ) = snapshot

    def test_reauthentication_invalidates_deferred_live_ticket(self):
        future = Future()
        future.set_result(
            {"job-a": {"project_id": "project-a", "status": "running"}}
        )
        ticket = request_utils._LiveJobTicket(
            future=future,
            context=("org-a", "user-key-a"),
            request_generation=9,
            session_generation=2,
            lifecycle_generation=5,
        )

        with request_utils._live_job_future_lock:
            snapshot = (
                request_utils._refresh_infrastructure_enabled,
                request_utils._refresh_lifecycle_generation,
                request_utils._auth_session_generation,
                request_utils._live_job_future,
                request_utils._live_job_future_context,
                request_utils._live_job_future_generation,
                request_utils._pending_live_overlay,
            )
            request_utils._refresh_infrastructure_enabled = True
            request_utils._refresh_lifecycle_generation = 5
            request_utils._auth_session_generation = 3
            request_utils._live_job_future = future
            request_utils._live_job_future_context = ("org-a", "user-key-a")
            request_utils._live_job_future_generation = 9
            request_utils._pending_live_overlay = None

        try:
            request_utils._apply_deferred_live_jobs(
                future,
                ticket,
                "org-a",
                "user-key-a",
                "project-a",
                "project-a",
                "",
            )
            self.assertIsNone(request_utils._pending_live_overlay)
        finally:
            with request_utils._live_job_future_lock:
                (
                    request_utils._refresh_infrastructure_enabled,
                    request_utils._refresh_lifecycle_generation,
                    request_utils._auth_session_generation,
                    request_utils._live_job_future,
                    request_utils._live_job_future_context,
                    request_utils._live_job_future_generation,
                    request_utils._pending_live_overlay,
                ) = snapshot

    def test_auth_context_invalidation_resets_stored_job_session(self):
        old_live_redraw_pending = request_utils._live_job_redraw_pending.is_set()
        with request_utils._live_job_future_lock:
            snapshot = (
                request_utils._auth_session_generation,
                request_utils._observed_user_token,
                request_utils._live_job_future,
                request_utils._pending_live_overlay,
            )
            request_utils._live_job_future = None
            request_utils._pending_live_overlay = None

        try:
            with patch.object(
                request_utils,
                "reset_stored_job_session",
            ) as reset_stored_session, patch.object(
                request_utils,
                "_request_properties_redraw",
            ):
                request_utils.invalidate_job_refresh_context()

            reset_stored_session.assert_called_once_with()
            self.assertEqual(
                request_utils._auth_session_generation,
                snapshot[0] + 1,
            )
        finally:
            if old_live_redraw_pending:
                request_utils._live_job_redraw_pending.set()
            else:
                request_utils._live_job_redraw_pending.clear()
            with request_utils._live_job_future_lock:
                (
                    request_utils._auth_session_generation,
                    request_utils._observed_user_token,
                    request_utils._live_job_future,
                    request_utils._pending_live_overlay,
                ) = snapshot

    def test_refresh_infrastructure_can_unregister_and_register_again(self):
        old_executor = MagicMock()
        new_executor = MagicMock()
        old_stop_event = threading.Event()
        old_enabled = request_utils.Storage.enable_job_thread
        old_live_redraw_pending = request_utils._live_job_redraw_pending.is_set()
        old_properties_redraw_requested = (
            request_utils._properties_redraw_requested.is_set()
        )

        with request_utils._live_job_future_lock:
            snapshot = (
                request_utils._refresh_infrastructure_enabled,
                request_utils._refresh_lifecycle_generation,
                request_utils._auth_session_generation,
                request_utils._observed_user_token,
                request_utils._live_job_executor,
                request_utils._live_job_future,
                request_utils._pending_live_overlay,
                request_utils._job_loop_stop_event,
            )
            request_utils._refresh_infrastructure_enabled = True
            request_utils._live_job_executor = old_executor
            request_utils._live_job_future = Future()
            request_utils._pending_live_overlay = None
            request_utils._job_loop_stop_event = old_stop_event

        try:
            request_utils.Storage.enable_job_thread = True
            with patch.object(
                request_utils,
                "_unregister_pulse_timer",
            ) as unregister_timer, patch.object(
                request_utils,
                "reset_stored_job_session",
            ) as reset_stored_session, patch.object(
                request_utils,
                "_create_live_job_executor",
                return_value=new_executor,
            ), patch.object(
                request_utils,
                "_ensure_pulse_timer",
            ) as ensure_timer, patch.object(
                request_utils,
                "_request_properties_redraw",
            ):
                request_utils.unregister_job_refresh_infrastructure()
                self.assertFalse(request_utils._refresh_infrastructure_enabled)
                self.assertTrue(old_stop_event.is_set())
                old_executor.shutdown.assert_called_once_with(
                    wait=False,
                    cancel_futures=True,
                )
                reset_stored_session.assert_called_once_with()
                unregister_timer.assert_called_once_with()

                request_utils.register_job_refresh_infrastructure()

            self.assertTrue(request_utils._refresh_infrastructure_enabled)
            self.assertIs(request_utils._live_job_executor, new_executor)
            self.assertIsNot(request_utils._job_loop_stop_event, old_stop_event)
            ensure_timer.assert_called_once_with()
        finally:
            request_utils.Storage.enable_job_thread = old_enabled
            if old_live_redraw_pending:
                request_utils._live_job_redraw_pending.set()
            else:
                request_utils._live_job_redraw_pending.clear()
            if old_properties_redraw_requested:
                request_utils._properties_redraw_requested.set()
            else:
                request_utils._properties_redraw_requested.clear()
            with request_utils._live_job_future_lock:
                (
                    request_utils._refresh_infrastructure_enabled,
                    request_utils._refresh_lifecycle_generation,
                    request_utils._auth_session_generation,
                    request_utils._observed_user_token,
                    request_utils._live_job_executor,
                    request_utils._live_job_future,
                    request_utils._pending_live_overlay,
                    request_utils._job_loop_stop_event,
                ) = snapshot

    def test_redraw_is_scoped_to_properties_editors(self):
        properties_area = types.SimpleNamespace(type="PROPERTIES", tag_redraw=MagicMock())
        viewport_area = types.SimpleNamespace(type="VIEW_3D", tag_redraw=MagicMock())
        fake_context = types.SimpleNamespace(
            window_manager=types.SimpleNamespace(
                windows=[
                    types.SimpleNamespace(
                        screen=types.SimpleNamespace(
                            areas=[properties_area, viewport_area]
                        )
                    )
                ]
            )
        )

        with patch.object(request_utils.bpy, "context", fake_context):
            request_utils._redraw_properties_areas()

        properties_area.tag_redraw.assert_called_once_with()
        viewport_area.tag_redraw.assert_not_called()

    def test_merge_keeps_stored_history_and_overlays_live_job_fields(self):
        stored = {
            "old-finished": {
                "id": "old-finished",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Old Finished",
                "status": "finished",
                "tasks": {"finished": 10},
                "thumbnail": "stored-thumb",
            },
            "active": {
                "id": "active",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Stored Active",
                "status": "queued",
                "tasks": {"queued": 10, "finished": 0},
                "machine_time": 0,
            },
            "other-project": {
                "id": "other-project",
                "project_id": "other",
                "name": "Other",
                "status": "finished",
            },
        }
        live = {
            "active": {
                "id": "active",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Live Active",
                "status": "running",
                "tasks": {
                    "queued": 5,
                    "running": 1,
                    "finished": 4,
                    "paused": 0,
                    "errored": 0,
                },
                "machine_time": 42,
                "last_task": 4,
            },
            "live-only": {
                "id": "live-only",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Live Only",
                "status": "running",
            },
        }

        merged = request_utils._merge_job_sources(
            stored,
            live,
            "project-id",
            "project-sqid",
        )

        self.assertIn("old-finished", merged)
        self.assertEqual(merged["old-finished"]["status"], "finished")
        self.assertEqual(merged["old-finished"]["thumbnail"], "stored-thumb")
        self.assertEqual(merged["active"]["status"], "running")
        self.assertEqual(merged["active"]["name"], "Stored Active")
        self.assertEqual(merged["active"]["machine_time"], 42)
        self.assertEqual(merged["active"]["last_task"], 4)
        self.assertEqual(merged["active"]["tasks"]["queued"], 5)
        self.assertEqual(merged["active"]["tasks"]["running"], 1)
        self.assertEqual(merged["active"]["tasks"]["finished"], 4)
        self.assertEqual(merged["active"]["tasks"]["error"], 0)
        self.assertNotIn("live-only", merged)
        self.assertNotIn("other-project", merged)

    def test_merge_allows_live_only_jobs_only_when_stored_jobs_unavailable(self):
        live = {
            "live-only": {
                "id": "live-only",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Live Only",
                "status": "running",
            },
        }

        self.assertEqual(
            request_utils._merge_job_sources(
                {},
                live,
                "project-id",
                "project-sqid",
            ),
            {},
        )

        merged = request_utils._merge_job_sources(
            {},
            live,
            "project-id",
            "project-sqid",
            allow_live_only=True,
        )

        self.assertIn("live-only", merged)

    def test_request_jobs_uses_empty_stored_list_as_authoritative(self):
        prefs = _FakePrefs()
        live = {
            "live-only": {
                "id": "live-only",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Live Only",
                "status": "running",
            },
        }

        with patch.object(request_utils, "get_prefs", return_value=prefs), \
             patch.object(request_utils, "_selected_project_identity", return_value=("project-id", "project-sqid")), \
             patch.object(request_utils, "_request_stored_jobs", return_value={}), \
             patch.object(request_utils, "_request_live_jobs", return_value=live):
            jobs = request_utils.request_jobs("org-id", "user-key", "project-id")

        self.assertEqual(jobs, {})
        self.assertEqual(request_utils.Storage.data["jobs"], {})

    def test_request_jobs_keeps_stored_jobs_when_live_fetch_fails(self):
        prefs = _FakePrefs()
        stored = {
            "stored": {
                "id": "stored",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Stored",
                "status": "finished",
            },
        }

        with patch.object(request_utils, "get_prefs", return_value=prefs), \
             patch.object(request_utils, "_selected_project_identity", return_value=("project-id", "project-sqid")), \
             patch.object(request_utils, "_request_stored_jobs", return_value=stored), \
             patch.object(request_utils, "_request_live_jobs", side_effect=RuntimeError("farm down")):
            jobs = request_utils.request_jobs("org-id", "user-key", "project-id")

        self.assertEqual(jobs, stored)
        self.assertEqual(request_utils.Storage.data["jobs"], stored)

    def test_request_jobs_falls_back_to_live_when_stored_endpoint_is_unavailable(self):
        prefs = _FakePrefs()
        live = {
            "live-only": {
                "id": "live-only",
                "project_id": "project-id",
                "project_sqid": "project-sqid",
                "name": "Live Only",
                "status": "running",
            },
        }

        with patch.object(request_utils, "get_prefs", return_value=prefs), \
             patch.object(request_utils, "_selected_project_identity", return_value=("project-id", "project-sqid")), \
             patch.object(
                 request_utils,
                 "_request_stored_jobs",
                 side_effect=request_utils.NotFound("Resource not found"),
             ), \
             patch.object(request_utils, "_request_live_jobs", return_value=live):
            jobs = request_utils.request_jobs("org-id", "user-key", "project-id")

        self.assertEqual(jobs, live)
        self.assertEqual(request_utils.Storage.data["jobs"], live)

    def test_request_jobs_surfaces_stored_authentication_errors(self):
        with patch.object(request_utils, "_request_stored_jobs", side_effect=(
            request_utils.NotAuthenticated("Resource not found")
        )), patch.object(request_utils, "_request_live_jobs") as live_request:
            with self.assertRaises(request_utils.NotAuthenticated):
                request_utils.request_jobs(
                    "org-stored-auth",
                    "user-key-stored-auth",
                    "project-stored-auth",
                )

        self.assertEqual(
            request_utils._live_job_future_context,
            ("org-stored-auth", "user-key-stored-auth"),
        )

    def test_request_jobs_keeps_stored_jobs_on_live_authentication_errors(self):
        stored = {
            "stored": {
                "id": "stored",
                "project_id": "project-live-auth",
                "status": "finished",
            },
        }
        with patch.object(
            request_utils,
            "_request_stored_jobs",
            return_value=stored,
        ), patch.object(
            request_utils,
            "_request_live_jobs",
            side_effect=request_utils.NotAuthenticated("Session expired"),
        ):
            jobs = request_utils.request_jobs(
                "org-live-auth",
                "user-key-live-auth",
                "project-live-auth",
            )

        self.assertEqual(jobs, stored)

    def test_request_jobs_surfaces_live_auth_when_stored_jobs_are_unavailable(self):
        with patch.object(
            request_utils,
            "_request_stored_jobs",
            side_effect=RuntimeError("stored unavailable"),
        ), patch.object(
            request_utils,
            "_request_live_jobs",
            side_effect=request_utils.NotAuthenticated("Session expired"),
        ):
            with self.assertRaises(request_utils.NotAuthenticated):
                request_utils.request_jobs(
                    "org-live-auth-unavailable",
                    "user-key-live-auth-unavailable",
                    "project-live-auth-unavailable",
                )


if __name__ == "__main__":
    unittest.main()
