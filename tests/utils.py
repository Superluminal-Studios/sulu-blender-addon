"""
Shared test utilities for Sulu + BAT tests.

Provides:
- Path logic functions (matching submit_worker.py exactly)
- Cross-platform path simulation
- S3 key validation
- Unicode normalization helpers
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import List, Tuple, Optional, Any


# ═══════════════════════════════════════════════════════════════════════════════
# PATH LOGIC FUNCTIONS (must match submit_worker.py / bat_utils.py exactly)
# These are duplicated here for testing without importing the actual modules
# ═══════════════════════════════════════════════════════════════════════════════

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]+")


def is_win_drive_path(p: str) -> bool:
    """Check if path looks like a Windows drive path (C:/ or C:\\)."""
    return bool(_WIN_DRIVE_RE.match(str(p)))


def get_drive(path: str) -> str:
    """
    Return a drive token representing the path's root device for cross-drive checks.

    - Windows letters: "C:", "D:", ...
    - UNC: "UNC"
    - macOS volumes: "/Volumes/NAME"
    - Linux removable/media: "/media/USER/NAME" or "/mnt/NAME"
    - Otherwise POSIX root "/"
    """
    p = str(path).replace("\\", "/")
    if is_win_drive_path(p):
        return (p[:2]).upper()  # "C:"
    if p.startswith("//") or p.startswith("\\\\"):
        return "UNC"
    if os.name == "nt":
        drv = os.path.splitdrive(p)[0].upper()
        if drv:
            return drv

    # macOS volumes
    if p.startswith("/Volumes/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return "/Volumes/" + parts[2]
        return "/Volumes"

    # Linux common mounts
    if p.startswith("/media/"):
        parts = p.split("/")
        if len(parts) >= 4:
            return f"/media/{parts[2]}/{parts[3]}"
        return "/media"

    if p.startswith("/mnt/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return f"/mnt/{parts[2]}"
        return "/mnt"

    # Fallback: POSIX root
    return "/"


def norm_path(path: str) -> str:
    """Normalize path for comparison, preserving Windows-style paths on POSIX."""
    p = str(path).replace("\\", "/")
    if is_win_drive_path(p) or p.startswith("//") or p.startswith("\\\\"):
        return p
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/")


def relpath_safe(child: str, base: str) -> str:
    """Safe relpath (POSIX separators). Caller must ensure same 'drive'."""
    return os.path.relpath(child, start=base).replace("\\", "/")


def s3key_clean(key: str) -> str:
    """
    Ensure S3 keys / manifest lines are clean and relative:
    - collapse duplicate slashes
    - strip any leading slash
    - normalize '.' and '..'
    """
    k = str(key).replace("\\", "/")
    k = re.sub(r"/+", "/", k)  # collapse duplicate slashes
    k = k.lstrip("/")  # forbid leading slash
    k = os.path.normpath(k).replace("\\", "/")
    if k == ".":
        return ""  # do not allow '.' as a key
    return k


def samepath(a: str, b: str) -> bool:
    """Case-insensitive, normalized equality check suitable for Windows/POSIX."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
        os.path.normpath(b)
    )


def nfc(s: str) -> str:
    """NFC normalize (critical for cross-platform Unicode)."""
    return unicodedata.normalize("NFC", str(s))


def nfd(s: str) -> str:
    """NFD normalize (macOS HFS+/APFS style)."""
    return unicodedata.normalize("NFD", str(s))


# ═══════════════════════════════════════════════════════════════════════════════
# PATH PROCESSING SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# S3 KEY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


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

    # Check for URL-unsafe characters that might cause issues
    # (most UTF-8 is actually fine in S3, but some chars cause tooling issues)

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


