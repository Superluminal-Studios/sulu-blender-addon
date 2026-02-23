from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

from utils.refresh_service import RefreshService


def _wait_until(predicate, timeout: float = 1.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestRefreshService(unittest.TestCase):
    def test_stale_job_result_is_dropped_after_project_switch(self):
        applied: list[tuple[str, dict]] = []

        def jobs_fetcher(org_id, user_key, project_id, session):
            if project_id == "project-a":
                time.sleep(0.08)
            return {"result_for": project_id}

        service = RefreshService(
            jobs_fetcher=jobs_fetcher,
            projects_fetcher=lambda session: [],
            session_factory=lambda: object(),
            on_jobs_success=lambda project_id, jobs, source: applied.append((project_id, jobs)),
            auto_refresh_interval=0.05,
        )

        try:
            service.set_credentials("org-1", "key-1")
            service.set_active_project("project-a")
            self.assertTrue(service.request_jobs_refresh(source="manual"))

            service.set_active_project("project-b")
            self.assertTrue(service.request_jobs_refresh(source="manual"))

            ok = _wait_until(
                lambda: (
                    service.apply_pending_results() or len(applied) >= 1
                )
                and len(applied) >= 1
            )
            self.assertTrue(ok, "Timed out waiting for job refresh results")
        finally:
            service.stop()

        self.assertEqual(1, len(applied))
        self.assertEqual("project-b", applied[0][0])
        self.assertEqual({"result_for": "project-b"}, applied[0][1])

    def test_auto_refresh_retargets_when_active_project_changes(self):
        calls: list[str] = []

        def jobs_fetcher(org_id, user_key, project_id, session):
            calls.append(project_id)
            return {}

        service = RefreshService(
            jobs_fetcher=jobs_fetcher,
            projects_fetcher=lambda session: [],
            session_factory=lambda: object(),
            auto_refresh_interval=0.05,
        )

        try:
            service.set_credentials("org-1", "key-1")
            service.set_active_project("project-a")
            service.set_auto_refresh(True)
            service.start()

            ok_a = _wait_until(lambda: "project-a" in calls)
            self.assertTrue(ok_a, "Auto-refresh never fetched project-a")

            service.set_active_project("project-b")
            ok_b = _wait_until(lambda: "project-b" in calls)
            self.assertTrue(ok_b, "Auto-refresh never retargeted to project-b")
        finally:
            service.stop()

        self.assertIn("project-a", calls)
        self.assertIn("project-b", calls)
        self.assertEqual("project-b", calls[-1])

    def test_jobs_fetcher_keyword_only_session_is_supported(self):
        applied: list[tuple[str, dict]] = []

        def jobs_fetcher(org_id, user_key, project_id, *, session=None):
            self.assertIsNotNone(session)
            return {"ok": True, "project_id": project_id}

        service = RefreshService(
            jobs_fetcher=jobs_fetcher,
            projects_fetcher=lambda session: [],
            session_factory=lambda: object(),
            on_jobs_success=lambda project_id, jobs, source: applied.append((project_id, jobs)),
            auto_refresh_interval=0.05,
        )

        try:
            service.set_credentials("org-1", "key-1")
            service.set_active_project("project-a")
            self.assertTrue(service.request_jobs_refresh(source="manual"))

            ok = _wait_until(
                lambda: (
                    service.apply_pending_results() or len(applied) >= 1
                )
                and len(applied) >= 1
            )
            self.assertTrue(ok, "Timed out waiting for keyword-only session refresh result")
        finally:
            service.stop()

        self.assertEqual(1, len(applied))
        self.assertEqual("project-a", applied[0][0])
        self.assertEqual({"ok": True, "project_id": "project-a"}, applied[0][1])


if __name__ == "__main__":
    unittest.main()
