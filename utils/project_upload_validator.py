from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set


def _unique(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _safe_relpath(child: str, base: str) -> str:
    try:
        return os.path.relpath(child, start=base).replace("\\", "/")
    except Exception:
        return str(child).replace("\\", "/")


def _is_outside_root(child: str, base: str) -> bool:
    rel = _safe_relpath(child, base)
    return rel == ".." or rel.startswith("../")


@dataclass
class ValidationResult:
    has_blocking_risk: bool = False
    warnings: List[str] = field(default_factory=list)
    issue_codes: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    details: Dict[str, List[str]] = field(default_factory=dict)
    actions: Dict[str, str] = field(default_factory=dict)


@dataclass
class ManifestValidationResult:
    normalized_entries: List[str] = field(default_factory=list)
    has_blocking_risk: bool = False
    warnings: List[str] = field(default_factory=list)
    issue_codes: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    invalid_entries: List[str] = field(default_factory=list)
    source_mismatches: List[str] = field(default_factory=list)
    actions: Dict[str, str] = field(default_factory=dict)


def validate_project_upload(
    *,
    blend_path: Path,
    project_root: Path,
    dep_paths: List[Path],
    raw_usages: List[Any],
    missing_set: Set[Path],
    unreadable_dict: Dict[Path, str],
    optional_set: Set[Path],
    cross_drive_files: Optional[List[Path]] = None,
    absolute_path_files: Optional[List[Path]] = None,
    out_of_root_files: Optional[List[Path]] = None,
) -> ValidationResult:
    """
    Validate Project-upload path safety before upload.

    Detects path classes that commonly cause "works locally, missing on farm":
    - absolute path references in blend datablocks
    - dependencies outside selected project root
    - root-escaping relative mappings
    """
    res = ValidationResult()

    missing_norm = {os.path.normpath(str(p)) for p in (missing_set or set())}
    unreadable_norm = {os.path.normpath(str(p)) for p in (unreadable_dict or {}).keys()}
    optional_norm = {os.path.normpath(str(p)) for p in (optional_set or set())}
    excluded_norm = missing_norm | unreadable_norm | optional_norm

    if absolute_path_files is None:
        abs_paths: List[str] = []
        for usage in raw_usages or []:
            try:
                if getattr(usage, "is_optional", False):
                    continue
                if usage.asset_path.is_blendfile_relative():
                    continue
                abs_path = str(usage.abspath)
                norm = os.path.normpath(abs_path)
                if norm in excluded_norm:
                    continue
                abs_paths.append(abs_path)
            except Exception:
                continue
        absolute_path_files_list = _unique(abs_paths)
    else:
        absolute_path_files_list = _unique(str(p) for p in absolute_path_files)

    if out_of_root_files is None:
        out: List[str] = []
        root_s = str(project_root)
        for dep in dep_paths or []:
            dep_s = str(dep)
            dep_norm = os.path.normpath(dep_s)
            if dep_norm in excluded_norm:
                continue
            if _is_outside_root(dep_s, root_s):
                out.append(dep_s)
        out_of_root_files_list = _unique(out)
    else:
        out_of_root_files_list = _unique(str(p) for p in out_of_root_files)

    root_escape_files: List[str] = []
    root_s = str(project_root)
    for dep in out_of_root_files_list:
        rel = _safe_relpath(dep, root_s)
        if rel == ".." or rel.startswith("../"):
            root_escape_files.append(dep)
    root_escape_files = _unique(root_escape_files)

    cross_drive_files_list = _unique(str(p) for p in (cross_drive_files or []))

    stats = {
        "absolute_path_count": len(absolute_path_files_list),
        "out_of_root_count": len(out_of_root_files_list),
        "root_escape_count": len(root_escape_files),
        "cross_drive_count": len(cross_drive_files_list),
        "missing_count": len(missing_set or set()),
        "unreadable_count": len(unreadable_dict or {}),
    }
    res.stats.update(stats)
    res.details["absolute_path_files"] = absolute_path_files_list
    res.details["out_of_root_files"] = out_of_root_files_list
    res.details["root_escape_files"] = root_escape_files
    res.details["cross_drive_files"] = cross_drive_files_list

    if absolute_path_files_list:
        res.issue_codes.append("PROJECT_ABSOLUTE_PATH_REFERENCE")
        res.actions["PROJECT_ABSOLUTE_PATH_REFERENCE"] = (
            "Make all asset paths relative or switch to Zip upload."
        )
        res.warnings.append(
            "Project upload references absolute paths that farm workers cannot resolve."
        )

    if out_of_root_files_list:
        res.issue_codes.append("PROJECT_OUT_OF_ROOT_EXCLUDED")
        res.actions["PROJECT_OUT_OF_ROOT_EXCLUDED"] = (
            "Broaden project root or switch to Zip upload."
        )
        res.warnings.append(
            "Some required dependencies are outside the selected project root."
        )

    if root_escape_files:
        res.issue_codes.append("PROJECT_ROOT_ESCAPE")
        res.actions["PROJECT_ROOT_ESCAPE"] = (
            "Fix path traversal outside project root before Project upload."
        )
        res.warnings.append(
            "At least one dependency resolves outside project root via relative traversal."
        )

    res.has_blocking_risk = bool(
        absolute_path_files_list or out_of_root_files_list or root_escape_files
    )
    return res


def validate_manifest_entries(
    entries: List[str],
    *,
    source_root: str,
    source_map: Optional[Dict[str, str]] = None,
    clean_key: Optional[Callable[[str], str]] = None,
    path_exists: Optional[Callable[[str], bool]] = None,
) -> ManifestValidationResult:
    """
    Normalize and validate manifest entries before upload.

    Ensures keys are non-empty, relative, de-duplicated, and mappable to source files.
    """
    res = ManifestValidationResult()
    source_map = source_map or {}
    path_exists = path_exists or os.path.exists

    def _clean(key: str) -> str:
        k = str(key).replace("\\", "/").strip()
        if clean_key is not None:
            k = clean_key(k)
        return str(k).replace("\\", "/")

    seen: Set[str] = set()
    duplicate_count = 0

    for raw in entries or []:
        cleaned = _clean(raw)

        invalid = (
            not cleaned
            or cleaned == "."
            or cleaned == ".."
            or cleaned.startswith("/")
            or cleaned.startswith("../")
            or "/../" in cleaned
        )
        if invalid:
            res.invalid_entries.append(str(raw))
            continue

        if cleaned in seen:
            duplicate_count += 1
            continue
        seen.add(cleaned)
        res.normalized_entries.append(cleaned)

    for rel in res.normalized_entries:
        src = source_map.get(rel)
        if not src:
            src = os.path.join(source_root, rel.replace("/", os.sep))
        if not path_exists(str(src)):
            res.source_mismatches.append(rel)

    if res.invalid_entries:
        res.issue_codes.append("MANIFEST_ENTRY_INVALID")
        res.actions["MANIFEST_ENTRY_INVALID"] = (
            "Regenerate manifest from a valid project root."
        )
        res.warnings.append(
            f"{len(res.invalid_entries)} manifest entries were invalid and ignored."
        )

    if res.source_mismatches:
        res.issue_codes.append("MANIFEST_SOURCE_MISMATCH")
        res.actions["MANIFEST_SOURCE_MISMATCH"] = (
            "Manifest entries did not map to readable local files."
        )
        res.warnings.append(
            f"{len(res.source_mismatches)} manifest entries do not match local source files."
        )

    res.has_blocking_risk = bool(res.invalid_entries or res.source_mismatches)
    res.stats.update(
        {
            "manifest_entries_in": len(entries or []),
            "manifest_entries_out": len(res.normalized_entries),
            "duplicate_entries_removed": duplicate_count,
            "invalid_entry_count": len(res.invalid_entries),
            "source_mismatch_count": len(res.source_mismatches),
            "source_match_count": len(res.normalized_entries)
            - len(res.source_mismatches),
        }
    )
    return res
