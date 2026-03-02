from __future__ import annotations

from typing import Callable, Iterable


REQUIRED_PROJECT_FIELDS = ("id", "organization_id", "sqid")


class ProjectContextError(RuntimeError):
    """Raised when selected project context cannot be resolved safely."""

    def __init__(self, message: str, *, missing_fields: list[str] | None = None):
        super().__init__(message)
        self.missing_fields = list(missing_fields or [])


def _project_value_missing(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _find_project(projects: Iterable[dict], project_id: str) -> dict | None:
    if not project_id:
        return None
    for project in projects:
        if project.get("id") == project_id:
            return project
    return None


def validate_project_identity(project: dict | None) -> tuple[bool, list[str]]:
    """
    Return (is_valid, missing_fields) for required project identity fields.
    """
    if not project:
        return False, list(REQUIRED_PROJECT_FIELDS)

    missing = [field for field in REQUIRED_PROJECT_FIELDS if _project_value_missing(project.get(field))]
    return len(missing) == 0, missing


def resolve_selected_project(
    project_id: str,
    cached_projects: Iterable[dict] | None,
    fetch_projects_fn: Callable[[], Iterable[dict]],
) -> tuple[dict | None, list[dict], bool]:
    """
    Resolve selected project from cache and force one refresh if needed.

    Returns:
      (project, projects_snapshot, did_refresh_projects)
    """
    projects = list(cached_projects or [])
    project = _find_project(projects, project_id)
    is_valid, _ = validate_project_identity(project)
    if project is not None and is_valid:
        return project, projects, False

    refreshed_projects = list(fetch_projects_fn() or [])
    refreshed_project = _find_project(refreshed_projects, project_id)
    return refreshed_project, refreshed_projects, True


def resolve_org_context(
    project: dict | None,
    get_render_queue_key_fn: Callable[[str], str],
) -> tuple[str, str]:
    """
    Resolve (org_id, user_key) from a validated project.
    """
    is_valid, missing = validate_project_identity(project)
    if not is_valid:
        raise ProjectContextError(
            "Selected project is missing required identity fields.",
            missing_fields=missing,
        )

    org_id = str(project["organization_id"]).strip()
    user_key = str(get_render_queue_key_fn(org_id) or "").strip()
    if not user_key:
        raise ProjectContextError(
            f"Could not resolve render queue key for organization '{org_id}'."
        )
    return org_id, user_key
