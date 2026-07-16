from __future__ import annotations

import importlib
import sys
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


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


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

    def test_request_jobs_does_not_message_match_authentication_errors(self):
        with patch.object(request_utils, "_request_stored_jobs", side_effect=(
            request_utils.NotAuthenticated("Resource not found")
        )), patch.object(request_utils, "_request_live_jobs") as live_request:
            with self.assertRaises(request_utils.NotAuthenticated):
                request_utils.request_jobs("org-id", "user-key", "project-id")

        live_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
