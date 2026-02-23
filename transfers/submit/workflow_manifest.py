"""Manifest construction and validation helpers for submit workflow."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .workflow_types import ManifestBuildResult


def build_project_manifest_from_map(
    *,
    fmap: Dict[Any, Any],
    abs_blend: str,
    common_path: str,
    ok_files_cache: set[str],
    logger,
    report,
    samepath_fn: Callable[[str, str], bool],
    relpath_safe_fn: Callable[[str, str], str],
    clean_key_fn: Callable[[str], str],
) -> ManifestBuildResult:
    rel_manifest: List[str] = []
    manifest_source_map: Dict[str, str] = {}
    dependency_total_size = 0
    ok_count = 0
    pack_idx = 0

    for src_path, _dst_path in fmap.items():
        src_str = str(src_path).replace("\\", "/")

        # Main blend is uploaded as a dedicated step.
        if samepath_fn(src_str, abs_blend):
            continue

        # Stage-1 readability cache avoids rechecking filesystem state.
        if src_str not in ok_files_cache:
            continue

        pack_idx += 1
        ok_count += 1

        size = 0
        try:
            size = os.path.getsize(src_str)
            dependency_total_size += size
        except Exception:
            pass

        logger.pack_entry(pack_idx, src_str, size=size, status="ok")

        rel = relpath_safe_fn(src_str, common_path)
        rel = clean_key_fn(rel)
        if rel:
            rel_manifest.append(rel)
            if rel not in manifest_source_map:
                manifest_source_map[rel] = src_str
            report.add_pack_entry(src_str, rel, file_size=size, status="ok")

    return ManifestBuildResult(
        rel_manifest=rel_manifest,
        manifest_source_map=manifest_source_map,
        dependency_total_size=dependency_total_size,
        ok_count=ok_count,
    )


def apply_manifest_validation(
    *,
    rel_manifest: List[str],
    common_path: str,
    manifest_source_map: Dict[str, str],
    validate_manifest_entries,
    logger,
    report,
    prompt_continue_with_reports,
    open_folder_fn,
    clean_key_fn: Callable[[str], str],
    metadata_manifest_entry_count: str,
    metadata_manifest_source_match_count: str,
    metadata_manifest_validation_stats: str,
) -> Tuple[List[str], bool]:
    manifest_validation = validate_manifest_entries(
        rel_manifest,
        source_root=common_path,
        source_map=manifest_source_map,
        clean_key=clean_key_fn,
    )
    normalized_manifest = manifest_validation.normalized_entries
    report.set_metadata(metadata_manifest_entry_count, len(normalized_manifest))
    report.set_metadata(
        metadata_manifest_source_match_count,
        int(manifest_validation.stats.get("source_match_count", 0)),
    )
    report.set_metadata(metadata_manifest_validation_stats, manifest_validation.stats)

    for code in manifest_validation.issue_codes:
        report.add_issue_code(code, manifest_validation.actions.get(code))
    for warning in manifest_validation.warnings:
        logger.warning(warning)

    if not manifest_validation.has_blocking_risk:
        return normalized_manifest, True

    keep_going = prompt_continue_with_reports(
        logger=logger,
        report=report,
        prompt="Manifest/source mapping risk detected. Continue anyway?",
        choice_label="Manifest validation risk found",
        open_folder_fn=open_folder_fn,
        default="n",
        followup_default="n",
        followup_choice_label="Continue after manifest risk report?",
    )
    return normalized_manifest, keep_going


def write_manifest_file(filelist_path: Path, rel_manifest: List[str]) -> None:
    with filelist_path.open("w", encoding="utf-8") as fp:
        for rel in rel_manifest:
            fp.write(f"{rel}\\n")


def validate_manifest_writeback(
    *,
    filelist_path: Path,
    expected_count: int,
    report,
    debug_enabled_fn: Callable[[], bool],
    log_fn: Callable[[str], None],
) -> None:
    try:
        written_lines = filelist_path.read_text("utf-8").splitlines()
        written_count = len([line for line in written_lines if line.strip()])
        if written_count != expected_count:
            if debug_enabled_fn():
                log_fn(
                    f"WARNING: Manifest line count mismatch — expected {expected_count}, "
                    f"got {written_count}"
                )
            report.set_metadata("manifest_validation", "mismatch")
            report.set_metadata("manifest_expected", expected_count)
            report.set_metadata("manifest_written", written_count)
        else:
            report.set_metadata("manifest_validation", "ok")
    except Exception as exc:
        if debug_enabled_fn():
            log_fn(f"WARNING: Could not validate manifest: {exc}")
        report.set_metadata("manifest_validation", f"error: {exc}")
