
from __future__ import annotations
import bpy
import threading
from typing import Dict, List, Tuple

# ----------------------------------------------------------------
# Single source of truth for Blender version selection
# ----------------------------------------------------------------

# (enum_key, label, description)
_FALLBACK_BLENDER_VERSION_ITEMS: List[Tuple[str, str, str]] = [
    ("BLENDER40", "Blender 4.0", "Use Blender 4.0 on the farm"),
    ("BLENDER41", "Blender 4.1", "Use Blender 4.1 on the farm"),
    ("BLENDER42", "Blender 4.2", "Use Blender 4.2 on the farm"),
    ("BLENDER43", "Blender 4.3", "Use Blender 4.3 on the farm"),
    ("BLENDER44", "Blender 4.4", "Use Blender 4.4 on the farm"),
    ("BLENDER45", "Blender 4.5", "Use Blender 4.5 on the farm"),
    ("BLENDER50", "Blender 5.0", "Use Blender 5.0 on the farm"),
    ("BLENDER51", "Blender 5.1", "Use Blender 5.1 on the farm"),
    ("BLENDER52", "Blender 5.2", "Use Blender 5.2 on the farm"),
    ("BLENDER53", "Blender 5.3", "Use Blender 5.3 on the farm"),
]

_version_lock = threading.RLock()
blender_version_items: List[Tuple[str, str, str]] = list(
    _FALLBACK_BLENDER_VERSION_ITEMS
)
_worker_value_by_enum: Dict[str, str] = {
    code: code.lower() for code, *_ in blender_version_items
}


def _numeric_enum_lookup() -> Tuple[Dict[int, str], List[int]]:
    with _version_lock:
        lookup = {
            int(code.replace("BLENDER", "")): code
            for code, *_ in blender_version_items
            if code.replace("BLENDER", "").isdigit()
        }
    return lookup, sorted(lookup)


def blender_version_items_callback(_self=None, _context=None):
    """Return a stable snapshot for Blender's dynamic EnumProperty callback."""
    with _version_lock:
        return list(blender_version_items)


def update_deployed_blender_versions(records) -> bool:
    """Replace the selector cache with valid deployed records from PocketBase."""
    normalized = []
    worker_values = {}
    seen = set()

    for record in records or []:
        if not isinstance(record, dict):
            continue
        if record.get("enabled") is False or record.get("deployed") is False:
            continue
        identifier = str(record.get("identifier") or "").strip().upper()
        worker_value = str(record.get("worker_value") or "").strip()
        label = str(record.get("label") or "").strip()
        version = str(record.get("version") or "").strip()
        if (
            not identifier.startswith("BLENDER")
            or not identifier.replace("BLENDER", "").isdigit()
            or not worker_value
            or not label
            or identifier in seen
            or any(
                "sulu" in value.lower()
                for value in (identifier, worker_value, label, str(record.get("channel") or ""))
            )
        ):
            continue
        seen.add(identifier)
        description = f"Use Blender {version or label.removeprefix('Blender ')} on the farm"
        try:
            order = int(record.get("sort_order") or 0)
        except (TypeError, ValueError):
            order = 0
        normalized.append((order, identifier, label, description))
        worker_values[identifier] = worker_value

    if not normalized:
        return False

    normalized.sort(key=lambda item: (item[0], item[1]))
    with _version_lock:
        blender_version_items[:] = [item[1:] for item in normalized]
        _worker_value_by_enum.clear()
        _worker_value_by_enum.update(worker_values)
    return True


def enum_from_bpy_version() -> str:
    """
    Return the enum key that best matches the running Blender version.

    - If the build is newer than anything in the list, use the highest enum.
    - If it's older than anything in the list, use the lowest enum.
    - Otherwise pick the exact match or, if the minor isn't represented,
      the nearest lower entry (e.g. 4.2.3 -> BLENDER42).
    """
    major, minor, _ = bpy.app.version
    numeric = major * 10 + minor
    enum_by_number, enum_numbers_sorted = _numeric_enum_lookup()
    if not enum_numbers_sorted:
        return _FALLBACK_BLENDER_VERSION_ITEMS[0][0]

    # Clamp to list boundaries
    if numeric <= enum_numbers_sorted[0]:
        return enum_by_number[enum_numbers_sorted[0]]
    if numeric >= enum_numbers_sorted[-1]:
        return enum_by_number[enum_numbers_sorted[-1]]

    # Inside the known range: closest lower-or-equal entry.
    for n in reversed(enum_numbers_sorted):
        if n <= numeric:
            return enum_by_number[n]

    # Fallback (should not be reached).
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
    Convert our enum into the value the worker/API expects. PocketBase can
    change this mapping without requiring an add-on release.
    """
    with _version_lock:
        return _worker_value_by_enum.get(enum_key, enum_key.lower())


def resolved_worker_blender_value(auto_determine: bool, selected_enum: str) -> str:
    """
    Convenience: resolve the right enum and return the worker/API payload string.
    """
    return to_worker_blender_value(
        resolve_selected_blender_enum(auto_determine, selected_enum)
    )
