"""Upload-stage helpers for manifest handling and transfer diagnostics."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def split_manifest_by_first_dir(rel_manifest: List[str]) -> Dict[str, List[str]]:
    """Group manifest entries by first path component."""
    groups: Dict[str, List[str]] = {}
    for rel in rel_manifest:
        slash_pos = rel.find("/")
        if slash_pos > 0:
            first_dir = rel[:slash_pos]
            remainder = rel[slash_pos + 1 :]
        else:
            first_dir = ""
            remainder = rel
        groups.setdefault(first_dir, []).append(remainder)
    return groups


def record_manifest_touch_mismatch(
    *,
    logger,
    report,
    total_touched: int,
    manifest_count: int,
    issue_code: str,
    issue_action: str,
    debug_enabled_fn: Callable[[], bool],
    log_fn: Callable[[str], None],
) -> None:
    if total_touched <= 0 or total_touched >= manifest_count:
        return

    mismatch_msg = (
        f"rclone touched {total_touched} of {manifest_count} "
        "manifest files; some dependencies may have been skipped."
    )
    logger.warning(mismatch_msg)
    if debug_enabled_fn():
        log_fn(f"WARNING: {mismatch_msg}")
    report.add_issue_code(issue_code, issue_action)


def run_addons_upload_step(
    *,
    data: Dict[str, Any],
    job_id: str,
    step: int,
    total_steps: int,
    bucket: str,
    base_cmd: List[str],
    rclone_settings: List[str],
    run_rclone: Callable[..., Any],
    rclone_bytes_fn: Callable[[Any], int],
    rclone_stats_fn: Callable[[Any], Optional[Dict[str, Any]]],
    log_upload_result_fn: Callable[..., None],
    check_rclone_errors_fn: Callable[..., None],
    logger,
    report,
) -> None:
    packed_addons_path = data.get("packed_addons_path")
    if not packed_addons_path:
        return

    logger.upload_step(step, total_steps, "Uploading add-ons")
    report.start_upload_step(
        step,
        total_steps,
        "Uploading add-ons",
        source=packed_addons_path,
        destination=f":s3:{bucket}/{job_id}/addons/",
        verb="moveto",
    )
    rclone_result = run_rclone(
        base_cmd,
        "moveto",
        packed_addons_path,
        f":s3:{bucket}/{job_id}/addons/",
        extra=rclone_settings,
        logger=logger,
    )
    logger.upload_complete("Add-ons uploaded")
    log_upload_result_fn(rclone_result, label="Add-ons: ")
    check_rclone_errors_fn(rclone_result, label="Add-ons")
    report.complete_upload_step(
        bytes_transferred=rclone_bytes_fn(rclone_result),
        rclone_stats=rclone_stats_fn(rclone_result),
    )
