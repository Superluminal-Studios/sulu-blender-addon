from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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
_API_URL = pocketbase_auth.profile_for_environment("production").api_url


class _FakeResponse:
    def __init__(self, payload, *, status_code=200, text="json"):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _StatusResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        raise AssertionError("Mapped statuses must not use the generic HTTP error")


class TestRequestUtilsJobs(unittest.TestCase):


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
                f"{_API_URL}/jobs",
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
                        f"{_API_URL}/jobs",
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


    def test_get_render_queue_key_repairs_missing_record_via_farm_status(self):
        responses = [
            _FakeResponse({"items": []}),
            _FakeResponse({"ready": True}),
            _FakeResponse({"items": [{"user_key": "recovered-user-key"}]}),
        ]
        with patch.object(
            request_utils,
            "authorized_request",
            side_effect=responses,
        ) as request:
            self.assertEqual(
                request_utils.get_render_queue_key("org-id"),
                "recovered-user-key",
            )

        self.assertEqual(request.call_count, 3)
        self.assertEqual(
            request.call_args_list[1].args,
            (
                "GET",
                f"{request_utils.POCKETBASE_URL}/api/farm_status/org-id",
            ),
        )
        self.assertEqual(
            request.call_args_list[1].kwargs,
            {"isolated_session": True},
        )


class TestCoordinatedJobReads(unittest.TestCase):
    def setUp(self):
        profile = pocketbase_auth.profile_for_environment("test")
        patcher = patch.object(request_utils, "active_profile", return_value=profile)
        patcher.start()
        self.addCleanup(patcher.stop)


    def test_repeated_cursor_and_account_change_cannot_publish_a_partial_listing(self):
        pages = [_FakeResponse({"body": {}, "next_cursor": "repeat"}), _FakeResponse({"body": {}, "next_cursor": "repeat"})]
        with patch.object(request_utils, "authorized_request", side_effect=pages), \
             patch.object(request_utils, "_selected_project_identity", return_value=("project", "sqid")):
            with self.assertRaises(request_utils.ProjectContextError):
                request_utils.request_jobs("organization", "", "project")
        with patch.object(request_utils, "authorized_request", return_value=_FakeResponse({"body": {"job-a": {"project_id": "project"}}})), \
             patch.object(request_utils, "_selected_project_identity", return_value=("project", "sqid")), \
             patch.object(request_utils, "_current_refresh_identity", side_effect=[(1, 1), (1, 2)]), \
             patch.dict(request_utils.Storage.data, {"jobs": {"other-user-job": {}}}):
            request_utils._request_jobs_unlocked("organization", "", "project")
            self.assertEqual(request_utils.Storage.data["jobs"], {"other-user-job": {}})


if __name__ == "__main__":
    unittest.main()


