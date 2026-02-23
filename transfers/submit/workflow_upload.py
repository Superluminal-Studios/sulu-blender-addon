"""Upload-stage helpers for manifest handling and transfer diagnostics."""

from __future__ import annotations

from typing import Callable, Dict, List


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
