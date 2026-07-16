"""Shared test helpers for Sulu + BAT tests."""

from __future__ import annotations

import os
import unicodedata
from typing import List, Tuple

# Path logic under test must be the production implementation so the suite
# exercises the exact code the workers run.
from utils.worker_utils import (
    get_drive,
    is_win_drive_path,
    norm_abs_for_detection,
    relpath_safe,
    s3key_clean,
    samepath,
)

norm_path = norm_abs_for_detection

__all__ = [
    "get_drive",
    "is_win_drive_path",
    "norm_abs_for_detection",
    "norm_path",
    "relpath_safe",
    "s3key_clean",
    "samepath",
    "nfc",
    "nfd",
    "process_for_upload",
    "validate_s3_key",
    "is_s3_safe",
    "is_absolute_path",
]


def nfc(s: str) -> str:
    """NFC normalize (critical for cross-platform Unicode)."""
    return unicodedata.normalize("NFC", str(s))


def nfd(s: str) -> str:
    """NFD normalize (macOS HFS+/APFS style)."""
    return unicodedata.normalize("NFD", str(s))


def process_for_upload(
    blend_path: str,
    project_root: str,
    dependencies: List[str],
) -> Tuple[str, List[str], List[str]]:
    """
    Simulate the full upload path processing pipeline.

    Returns: (main_blend_s3_key, dependency_keys, issues)
    """
    issues = []

    # Normalize inputs
    blend_norm = blend_path.replace("\\", "/")
    root_norm = project_root.replace("\\", "/")

    # Compute main blend S3 key
    try:
        blend_rel = relpath_safe(blend_norm, root_norm)
        main_key = s3key_clean(blend_rel) or os.path.basename(blend_norm)
    except ValueError as e:
        issues.append(f"Failed to compute blend key: {e}")
        main_key = os.path.basename(blend_norm)

    # NFC normalize for consistent encoding
    main_key = nfc(main_key)

    # Process dependencies
    dep_keys = []
    for dep in dependencies:
        dep_norm = dep.replace("\\", "/")
        try:
            dep_rel = relpath_safe(dep_norm, root_norm)
            dep_key = s3key_clean(dep_rel)
            if dep_key:
                dep_keys.append(nfc(dep_key))
        except ValueError as e:
            issues.append(f"Failed to compute dep key for {dep}: {e}")

    return main_key, dep_keys, issues


def validate_s3_key(key: str) -> List[str]:
    """
    Validate an S3 key and return list of issues (empty = valid).
    """
    issues = []

    # No absolute paths
    if key.startswith("/"):
        issues.append("starts with /")
    if is_win_drive_path(key):
        issues.append("has Windows drive letter")
    if "\\" in key:
        issues.append("contains backslash")

    # No temp directories
    temp_indicators = ["Temp", "tmp", "temp", "TEMP", "AppData/Local/Temp", "var/folders", "bat_packroot"]
    for t in temp_indicators:
        if t in key:
            issues.append(f"contains temp indicator: {t}")

    # No problematic patterns
    if key.startswith("."):
        issues.append("starts with dot (hidden file)")
    if ".." in key:
        issues.append("contains parent reference (..)")

    return issues


def is_s3_safe(key: str) -> bool:
    """Check if S3 key is safe for upload."""
    return len(validate_s3_key(key)) == 0


def is_absolute_path(path: str) -> bool:
    """Check if path looks like an absolute path."""
    if path.startswith("/"):
        return True
    if is_win_drive_path(path):
        return True
    if path.startswith("\\\\"):
        return True
    if ":" in path and not path.startswith("http"):
        return True
    return False
