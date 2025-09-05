# utils/version_utils.py
from __future__ import annotations
import bpy
from typing import Dict, List, Tuple

# ────────────────────────────────────────────────────────────────
# Single source of truth for Blender version selection
# ────────────────────────────────────────────────────────────────

# (enum_key, label, description)
blender_version_items: List[Tuple[str, str, str]] = [
    ("BLENDER40", "Blender 4.0", "Use Blender 4.0 on the farm"),
    ("BLENDER41", "Blender 4.1", "Use Blender 4.1 on the farm"),
    ("BLENDER42", "Blender 4.2", "Use Blender 4.2 on the farm"),
    ("BLENDER43", "Blender 4.3", "Use Blender 4.3 on the farm"),
    ("BLENDER44", "Blender 4.4", "Use Blender 4.4 on the farm"),
    ("BLENDER45", "Blender 4.5", "Use Blender 4.5 on the farm"),
    ("BLENDER50", "Blender 5.0", "Use Blender 5.0 on the farm"),
]

# Build a lookup:  40 → "BLENDER40", 41 → "BLENDER41", …
_enum_by_number: Dict[int, str] = {
    int(code.replace("BLENDER", "")): code for code, *_ in blender_version_items
}
_enum_numbers_sorted = sorted(_enum_by_number)  # e.g. [40, 41, 42, 43, 44, 45]


def enum_from_bpy_version() -> str:
    """
    Return the enum key that best matches the running Blender version.

    • If the build is newer than anything in the list → highest enum we have.
    • If it’s older than anything in the list → lowest.
    • Otherwise pick the exact match or, if the minor isn't represented,
      the nearest lower entry (e.g. 4.2.3 → BLENDER42).
    """
    major, minor, _ = bpy.app.version
    numeric = major * 10 + minor

    # Clamp to list boundaries
    if numeric <= _enum_numbers_sorted[0]:
        return _enum_by_number[_enum_numbers_sorted[0]]
    if numeric >= _enum_numbers_sorted[-1]:
        return _enum_by_number[_enum_numbers_sorted[-1]]

    # Inside the known range – closest lower-or-equal entry
    for n in reversed(_enum_numbers_sorted):
        if n <= numeric:
            return _enum_by_number[n]

    # Fallback (shouldn’t be reached)
    return blender_version_items[0][0]


def get_blender_version_string() -> str:
    """Human-friendly 'major.minor' string of the running Blender."""
    major, minor, _ = bpy.app.version
    return f"{major}.{minor}"


def resolve_selected_blender_enum(auto_determine: bool, selected_enum: str) -> str:
    """
    Decide which enum to use given the toggle and the UI selection.
    This is the single source of truth for the app-wide decision.
    """
    return enum_from_bpy_version() if auto_determine else selected_enum


def to_worker_blender_value(enum_key: str) -> str:
    """
    Convert our enum (e.g. 'BLENDER44') into the value the worker/API expects
    (currently lowercased e.g. 'blender44').
    """
    return enum_key.lower()


def resolved_worker_blender_value(auto_determine: bool, selected_enum: str) -> str:
    """
    Convenience: resolve the right enum and return the worker/API payload string.
    """
    return to_worker_blender_value(
        resolve_selected_blender_enum(auto_determine, selected_enum)
    )
