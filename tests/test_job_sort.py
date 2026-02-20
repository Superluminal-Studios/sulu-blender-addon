"""
Test that job-list sorting by time columns uses raw timestamps
(chronological) rather than formatted display strings (lexicographic).

Fully self-contained — no bpy or add-on imports needed.
Exercises the exact sort logic from preferences.py against mock job items.
"""
from __future__ import annotations

import os, sys, unittest
from datetime import datetime

# ── Inline copy of format_submitted (from utils/date_utils.py) ──────────
def format_submitted(ts):
    if not ts:
        return "\u2014"
    dt  = datetime.fromtimestamp(ts)
    now = datetime.now()
    hour_fmt   = "%-I" if os.name != "nt" else "%#I"
    uses_ampm  = bool(dt.strftime("%p"))
    time_str   = (
        dt.strftime(f"{hour_fmt}:%M %p")
        if uses_ampm
        else dt.strftime("%H:%M")
    )
    if dt.date() == now.date():
        return time_str
    date_str = f"{dt.strftime('%b')} {dt.day}"
    if dt.year != now.year:
        date_str += f" {dt.year}"
    return f"{date_str}, {time_str}"


# ── Mock job item ───────────────────────────────────────────────────────
class FakeJobItem:
    def __init__(self, name, submit_ts, start_ts, end_ts, progress=0.0):
        self.name = name
        self.submission_time = format_submitted(submit_ts)
        self.started_time = format_submitted(start_ts)
        self.finished_time = format_submitted(end_ts)
        self.submission_time_raw = submit_ts or 0.0
        self.started_time_raw = start_ts or 0.0
        self.finished_time_raw = end_ts or 0.0
        self.progress = progress
        self.status = "done"


# ── NEW sort logic (uses _raw floats for time columns) ──────────────────
def sort_items(items, sort_col, ascending):
    _TIME_COLS = {"submission_time", "started_time", "finished_time"}

    def get_sort_key(item):
        if sort_col in _TIME_COLS:
            return getattr(item, sort_col + "_raw", 0.0)
        val = getattr(item, sort_col, "")
        if isinstance(val, str):
            return val.casefold()
        return val

    indexed = [(i, get_sort_key(it)) for i, it in enumerate(items)]
    indexed.sort(key=lambda x: x[1], reverse=not ascending)
    return [i for i, _ in indexed]


# ── OLD sort logic (lexicographic string compare — BROKEN) ──────────────
def sort_items_OLD(items, sort_col, ascending):
    def get_sort_key(item):
        val = getattr(item, sort_col, "")
        if isinstance(val, str):
            return val.casefold()
        return val

    indexed = [(i, get_sort_key(it)) for i, it in enumerate(items)]
    indexed.sort(key=lambda x: x[1], reverse=not ascending)
    return [i for i, _ in indexed]


# ── Tests ───────────────────────────────────────────────────────────────

class TestJobSortByTime(unittest.TestCase):
    """Verify chronological sorting using raw timestamps."""

    def setUp(self):
        # Jobs across different months — the key scenario that broke
        # lexicographic sorting (e.g. "Feb" < "Jun" alphabetically,
        # but Feb 2025 is AFTER Jun 2024 chronologically).
        self.jobs = [
            FakeJobItem("job_june",  1717502580, 1717502600, 1717502700),  # Jun  4 2024
            FakeJobItem("job_feb",   1739885000, 1739885100, 1739885200),  # Feb 18 2025
            FakeJobItem("job_jan",   1704100000, 1704100100, 1704100200),  # Jan  1 2024
            FakeJobItem("job_dec",   1733000000, 1733000100, 1733000200),  # Dec  1 2024
        ]
        # Chronological order (oldest → newest): jan, june, dec, feb
        self.chrono_names = ["job_jan", "job_june", "job_dec", "job_feb"]

    def test_ascending_submission_time(self):
        order = sort_items(self.jobs, "submission_time", ascending=True)
        names = [self.jobs[i].name for i in order]
        self.assertEqual(names, self.chrono_names,
                         "Ascending time sort should be oldest → newest")

    def test_descending_submission_time(self):
        order = sort_items(self.jobs, "submission_time", ascending=False)
        names = [self.jobs[i].name for i in order]
        self.assertEqual(names, list(reversed(self.chrono_names)),
                         "Descending time sort should be newest → oldest")

    def test_ascending_started_time(self):
        order = sort_items(self.jobs, "started_time", ascending=True)
        names = [self.jobs[i].name for i in order]
        self.assertEqual(names, self.chrono_names)

    def test_ascending_finished_time(self):
        order = sort_items(self.jobs, "finished_time", ascending=True)
        names = [self.jobs[i].name for i in order]
        self.assertEqual(names, self.chrono_names)

    def test_old_logic_is_broken(self):
        """Prove the old string-compare logic gives WRONG chronological order."""
        order = sort_items_OLD(self.jobs, "submission_time", ascending=True)
        names = [self.jobs[i].name for i in order]
        self.assertNotEqual(names, self.chrono_names,
                            "Old string-based sort should NOT be chronological")


class TestNonTimeColumnsUnaffected(unittest.TestCase):
    """Non-time columns should still sort normally."""

    def setUp(self):
        self.jobs = [
            FakeJobItem("Charlie", 100, 100, 100, progress=0.5),
            FakeJobItem("Alice",   200, 200, 200, progress=0.9),
            FakeJobItem("Bob",     150, 150, 150, progress=0.1),
        ]

    def test_sort_by_name_ascending(self):
        order = sort_items(self.jobs, "name", ascending=True)
        names = [self.jobs[i].name for i in order]
        self.assertEqual(names, ["Alice", "Bob", "Charlie"])

    def test_sort_by_name_descending(self):
        order = sort_items(self.jobs, "name", ascending=False)
        names = [self.jobs[i].name for i in order]
        self.assertEqual(names, ["Charlie", "Bob", "Alice"])

    def test_sort_by_progress(self):
        order = sort_items(self.jobs, "progress", ascending=True)
        names = [self.jobs[i].name for i in order]
        self.assertEqual(names, ["Bob", "Charlie", "Alice"])


class TestEdgeCases(unittest.TestCase):
    """Edge cases: missing timestamps, single job, etc."""

    def test_missing_timestamps_sort_to_start(self):
        jobs = [
            FakeJobItem("has_time", 1739885000, 1739885100, 1739885200),
            FakeJobItem("no_time",  None, None, None),
        ]
        order = sort_items(jobs, "submission_time", ascending=True)
        names = [jobs[i].name for i in order]
        self.assertEqual(names[0], "no_time",
                         "Jobs with no timestamp (0.0) should sort first ascending")

    def test_single_job(self):
        jobs = [FakeJobItem("only", 1000, 1000, 1000)]
        order = sort_items(jobs, "submission_time", ascending=True)
        self.assertEqual(order, [0])

    def test_empty_list(self):
        order = sort_items([], "submission_time", ascending=True)
        self.assertEqual(order, [])


if __name__ == "__main__":
    unittest.main()
