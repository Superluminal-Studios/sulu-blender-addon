from __future__ import annotations

from functools import cmp_to_key
from typing import Any, Iterable, Iterator, Sequence


TIME_SOURCE_FIELDS = {
    "submission_time": "submit_time",
    "started_time": "start_time",
    "finished_time": "end_time",
}

TIME_SORT_ATTRS = {
    "submission_time": "submission_time_sort",
    "started_time": "started_time_sort",
    "finished_time": "finished_time_sort",
}

NUMERIC_COLUMNS = {"start_frame", "end_frame", "progress", "finished_frames"}
TEXT_COLUMNS = {"name", "status", "blender_version", "type"}


def selected_project_ids(projects: Iterable[dict[str, Any]], project_id: str) -> set[str]:
    project_id = str(project_id or "").strip()
    selected_project = next(
        (
            project
            for project in projects or []
            if str(project.get("id") or "").strip() == project_id
            or str(project.get("sqid") or "").strip() == project_id
        ),
        None,
    )
    if not selected_project:
        return set()

    ids = {
        str(selected_project.get("id") or "").strip(),
        str(selected_project.get("sqid") or "").strip(),
    }
    ids.discard("")
    return ids


def job_project_ids(job: dict[str, Any]) -> set[str]:
    ids = {
        str(job.get("project_id") or "").strip(),
        str(job.get("project_sqid") or "").strip(),
    }
    ids.discard("")
    return ids


def iter_project_jobs(
    jobs: dict[str, Any],
    projects: Iterable[dict[str, Any]],
    project_id: str,
) -> Iterator[tuple[str, dict[str, Any]]]:
    ids = selected_project_ids(projects, project_id)
    if not ids:
        return
    for job_id, job in (jobs or {}).items():
        if not isinstance(job, dict):
            continue
        if ids and ids.isdisjoint(job_project_ids(job)):
            continue
        yield str(job_id), job


def number_value(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def int_value(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def timestamp_value(value: Any) -> tuple[float, bool]:
    timestamp = number_value(value, 0.0)
    return timestamp, timestamp <= 0


def job_progress(job: dict[str, Any]) -> float:
    tasks = job.get("tasks", {}) or {}
    if not isinstance(tasks, dict):
        tasks = {}
    finished = number_value(tasks.get("finished"), 0.0)
    total = number_value(job.get("total_tasks"), 0.0)
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, finished / total))


def job_type_label(job: dict[str, Any]) -> str:
    return "Zip" if job.get("zip", True) else "Project"


def _text_value(value: Any) -> tuple[str, bool]:
    text = str(value or "").strip()
    return text.casefold(), text == ""


def _raw_sort_value(job_id: str, job: dict[str, Any], column: str) -> tuple[Any, bool]:
    if column in TIME_SOURCE_FIELDS:
        return timestamp_value(job.get(TIME_SOURCE_FIELDS[column]))
    if column == "start_frame":
        return int_value(job.get("start"), 0), False
    if column == "end_frame":
        return int_value(job.get("end"), 0), False
    if column == "progress":
        return job_progress(job), False
    if column == "finished_frames":
        tasks = job.get("tasks", {}) or {}
        if not isinstance(tasks, dict):
            tasks = {}
        return int_value(tasks.get("finished"), 0), False
    if column == "type":
        return _text_value(job_type_label(job))
    if column in TEXT_COLUMNS:
        return _text_value(job.get(column))
    return _text_value(job.get("name") or job_id)


def _item_sort_value(item: Any, column: str) -> tuple[Any, bool]:
    if column in TIME_SORT_ATTRS:
        return timestamp_value(getattr(item, TIME_SORT_ATTRS[column], 0.0))
    if column in NUMERIC_COLUMNS:
        return number_value(getattr(item, column, 0.0), 0.0), False
    if column in TEXT_COLUMNS:
        return _text_value(getattr(item, column, ""))
    return _text_value(getattr(item, "name", "") or getattr(item, "id", ""))


def _compare_values(
    left: tuple[Any, bool],
    right: tuple[Any, bool],
    ascending: bool,
) -> int:
    left_value, left_missing = left
    right_value, right_missing = right

    if left_missing != right_missing:
        return 1 if left_missing else -1
    if left_value == right_value:
        return 0
    result = -1 if left_value < right_value else 1
    return result if ascending else -result


def _compare_tiebreaker(left: tuple[str, str], right: tuple[str, str]) -> int:
    if left == right:
        return 0
    return -1 if left < right else 1


def sort_job_entries(
    entries: Sequence[tuple[str, dict[str, Any]]],
    sort_column: str,
    ascending: bool,
) -> list[tuple[str, dict[str, Any]]]:
    def compare(left: tuple[str, dict[str, Any]], right: tuple[str, dict[str, Any]]) -> int:
        value_cmp = _compare_values(
            _raw_sort_value(left[0], left[1], sort_column),
            _raw_sort_value(right[0], right[1], sort_column),
            ascending,
        )
        if value_cmp:
            return value_cmp
        return _compare_tiebreaker(
            (str(left[1].get("name") or "").casefold(), left[0].casefold()),
            (str(right[1].get("name") or "").casefold(), right[0].casefold()),
        )

    return sorted(entries, key=cmp_to_key(compare))


def sort_job_item_indices(items: Sequence[Any], sort_column: str, ascending: bool) -> list[int]:
    def compare(left_index: int, right_index: int) -> int:
        left = items[left_index]
        right = items[right_index]
        value_cmp = _compare_values(
            _item_sort_value(left, sort_column),
            _item_sort_value(right, sort_column),
            ascending,
        )
        if value_cmp:
            return value_cmp
        return _compare_tiebreaker(
            (
                str(getattr(left, "name", "") or "").casefold(),
                str(getattr(left, "id", "") or "").casefold(),
            ),
            (
                str(getattr(right, "name", "") or "").casefold(),
                str(getattr(right, "id", "") or "").casefold(),
            ),
        )

    return sorted(range(len(items)), key=cmp_to_key(compare))


def get_indexed_item(items: Sequence[Any], index: int) -> Any | None:
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    if 0 <= index < len(items):
        return items[index]
    return None
