from __future__ import annotations

import unittest

from utils.project_context import (
    ProjectContextError,
    resolve_org_context,
    resolve_selected_project,
    validate_project_identity,
)


class TestProjectContext(unittest.TestCase):
    def test_uses_cache_when_project_identity_is_complete(self):
        cached = [
            {
                "id": "proj_1",
                "name": "Project One",
                "organization_id": "org_1",
                "sqid": "sqid_1",
            }
        ]
        called = {"fetch": 0}

        def _fetch():
            called["fetch"] += 1
            return []

        project, projects, did_refresh = resolve_selected_project("proj_1", cached, _fetch)
        self.assertFalse(did_refresh)
        self.assertEqual(project["organization_id"], "org_1")
        self.assertEqual(projects, cached)
        self.assertEqual(called["fetch"], 0)

    def test_refreshes_when_cached_project_is_missing_identity(self):
        cached = [{"id": "proj_1", "name": "Project One", "organization_id": "", "sqid": ""}]
        refreshed = [
            {
                "id": "proj_1",
                "name": "Project One",
                "organization_id": "org_1",
                "sqid": "sqid_1",
            }
        ]

        project, projects, did_refresh = resolve_selected_project(
            "proj_1", cached, lambda: refreshed
        )
        self.assertTrue(did_refresh)
        self.assertEqual(project["organization_id"], "org_1")
        self.assertEqual(project["sqid"], "sqid_1")
        self.assertEqual(projects, refreshed)

    def test_refreshes_when_selected_project_missing_from_cache(self):
        cached = [
            {"id": "proj_a", "name": "Project A", "organization_id": "org_a", "sqid": "sqid_a"}
        ]
        refreshed = [
            {"id": "proj_a", "name": "Project A", "organization_id": "org_a", "sqid": "sqid_a"},
            {"id": "proj_b", "name": "Project B", "organization_id": "org_b", "sqid": "sqid_b"},
        ]

        project, projects, did_refresh = resolve_selected_project(
            "proj_b", cached, lambda: refreshed
        )
        self.assertTrue(did_refresh)
        self.assertEqual(project["id"], "proj_b")
        self.assertEqual(project["organization_id"], "org_b")
        self.assertEqual(projects, refreshed)

    def test_validate_project_identity_reports_missing_fields(self):
        valid, missing = validate_project_identity(
            {"id": "proj_1", "organization_id": "", "sqid": None}
        )
        self.assertFalse(valid)
        self.assertEqual(missing, ["organization_id", "sqid"])

    def test_resolve_org_context_raises_for_missing_fields(self):
        with self.assertRaises(ProjectContextError) as ctx:
            resolve_org_context({"id": "proj_1", "organization_id": "", "sqid": "sqid_1"}, lambda _org_id: "key")
        self.assertEqual(ctx.exception.missing_fields, ["organization_id"])

    def test_resolve_org_context_raises_if_user_key_missing(self):
        with self.assertRaises(ProjectContextError):
            resolve_org_context(
                {"id": "proj_1", "organization_id": "org_1", "sqid": "sqid_1"},
                lambda _org_id: "",
            )

    def test_resolve_org_context_success(self):
        org_id, user_key = resolve_org_context(
            {"id": "proj_1", "organization_id": "org_1", "sqid": "sqid_1"},
            lambda _org_id: "user_key_1",
        )
        self.assertEqual(org_id, "org_1")
        self.assertEqual(user_key, "user_key_1")


if __name__ == "__main__":
    unittest.main()
