"""Trace-stage helpers for project upload validation wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def apply_project_validation(
    *,
    validate_project_upload,
    blend_path: str,
    project_root: Path,
    dep_paths: List[Path],
    raw_usages: List[Any],
    missing_set,
    unreadable_dict,
    optional_set,
    cross_drive_deps: List[Path],
    absolute_path_deps: List[Path],
    out_of_root_ok_files: List[Path],
    report,
    metadata_project_validation_version: str,
    metadata_project_validation_stats: str,
    validation_version: str,
):
    result = validate_project_upload(
        blend_path=Path(blend_path),
        project_root=project_root,
        dep_paths=dep_paths,
        raw_usages=raw_usages,
        missing_set=missing_set,
        unreadable_dict=unreadable_dict,
        optional_set=optional_set,
        cross_drive_files=list(cross_drive_deps),
        absolute_path_files=list(absolute_path_deps),
        out_of_root_files=list(out_of_root_ok_files),
    )
    report.set_metadata(metadata_project_validation_version, validation_version)
    report.set_metadata(metadata_project_validation_stats, result.stats)
    for code in result.issue_codes:
        report.add_issue_code(code, result.actions.get(code))
    return result
