from __future__ import annotations

import unittest
from types import SimpleNamespace

from utils.job_list import (
    get_indexed_item,
    iter_project_jobs,
    sort_job_entries,
    sort_job_item_indices,
)


class TestJobListSorting(unittest.TestCase):
    def test_iter_project_jobs_filters_by_project_id_and_sqid(self):
        projects = [{"id": "project-id", "sqid": "project-sqid"}]
        jobs = {
            "id-match": {"project_id": "project-id", "name": "ID"},
            "sqid-match": {"project_sqid": "project-sqid", "name": "SQID"},
            "other": {"project_id": "other", "name": "Other"},
        }

        self.assertEqual(
            [job_id for job_id, _ in iter_project_jobs(jobs, projects, "project-id")],
            ["id-match", "sqid-match"],
        )

    def test_iter_project_jobs_returns_no_jobs_for_stale_selected_project(self):
        jobs = {"job-1": {"project_id": "project-id", "name": "Job"}}

        self.assertEqual(list(iter_project_jobs(jobs, [], "missing-project")), [])

    def test_sort_job_entries_uses_raw_submit_time_and_keeps_missing_times_last(self):
        jobs = [
            ("old", {"name": "Old", "submit_time": 100}),
            ("missing", {"name": "Missing"}),
            ("new", {"name": "New", "submit_time": 300}),
            ("middle", {"name": "Middle", "submit_time": 200}),
        ]

        descending = sort_job_entries(jobs, "submission_time", ascending=False)
        ascending = sort_job_entries(jobs, "submission_time", ascending=True)

        self.assertEqual([job_id for job_id, _ in descending], ["new", "middle", "old", "missing"])
        self.assertEqual([job_id for job_id, _ in ascending], ["old", "middle", "new", "missing"])

    def test_sort_job_item_indices_uses_hidden_time_sort_value_not_display_label(self):
        items = [
            SimpleNamespace(
                id="old",
                name="Old",
                submission_time="Jun 4, 9:00 AM",
                submission_time_sort=100,
            ),
            SimpleNamespace(
                id="new",
                name="New",
                submission_time="9:00 AM",
                submission_time_sort=300,
            ),
            SimpleNamespace(
                id="middle",
                name="Middle",
                submission_time="Jun 5, 9:00 AM",
                submission_time_sort=200,
            ),
        ]

        order = sort_job_item_indices(items, "submission_time", ascending=False)

        self.assertEqual([items[index].id for index in order], ["new", "middle", "old"])

    def test_get_indexed_item_returns_active_collection_item(self):
        items = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]

        self.assertEqual(get_indexed_item(items, 1).id, "b")
        self.assertIsNone(get_indexed_item(items, -1))
        self.assertIsNone(get_indexed_item(items, 2))


if __name__ == "__main__":
    unittest.main()
