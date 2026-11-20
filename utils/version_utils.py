
from __future__ import annotations
import bpy
import threading
from typing import Dict, List, Tuple

# ----------------------------------------------------------------
# Single source of truth for Blender version selection
# ----------------------------------------------------------------

# Blender keeps references to enum strings. Keep the database records alive.
_version_lock = threading.RLock()
blender_version_items: List[Tuple[str, str, str]] = []
_worker_value_by_enum: Dict[str, str] = {}
_enum_strings: Dict[str, str] = {}
_catalog_status = "Loading farm Blender versions..."


def blender_version_status() -> str:
    with _version_lock:
        return _catalog_status


def clear_deployed_blender_versions(message: str) -> None:
    global _catalog_status
    with _version_lock:
        blender_version_items.clear()
        _worker_value_by_enum.clear()
        _catalog_status = message


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
        return blender_version_items


def update_deployed_blender_versions(records) -> bool:
    """Validate the database catalog before publishing one complete snapshot."""
    global _catalog_status
    if not isinstance(records, list) or not records:
        raise ValueError("No deployed Blender versions were returned.")
    normalized = []
    worker_values = {}
    for record in records:
        identifier = record["identifier"]
        worker_value = record["worker_value"]
        label = record["label"]
        version = record["version"]
        if (
            not isinstance(identifier, str)
            or not identifier.startswith("BLENDER")
            or not identifier.removeprefix("BLENDER").isdigit()
            or identifier in worker_values
            or not isinstance(worker_value, str)
            or not worker_value
            or worker_value in worker_values.values()
            or not isinstance(label, str)
            or not label
            or not isinstance(version, str)
            or not version
            or not record["enabled"]
            or not record["deployed"]
        ):
            raise ValueError("The farm Blender catalog contains an invalid record.")
        order = record["sort_order"]
        if not isinstance(order, (int, float)) or int(order) != order:
            raise ValueError("The farm Blender catalog contains an invalid sort order.")
        normalized.append((order, identifier, label, f"Use Blender {version} on the farm"))
        worker_values[identifier] = worker_value
    normalized.sort(key=lambda item: (item[0], item[1]))
    with _version_lock:
        blender_version_items[:] = [
            tuple(_enum_strings.setdefault(value, value) for value in item[1:])
            for item in normalized
        ]
        _worker_value_by_enum.clear()
        _worker_value_by_enum.update(worker_values)
        _catalog_status = ""
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
        raise ValueError("Farm Blender versions are unavailable. Refresh Projects before submitting.")

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
        if enum_key not in _worker_value_by_enum:
            raise ValueError("Choose a deployed Blender version. Refresh Projects before submitting.")
        return _worker_value_by_enum[enum_key]


def resolved_worker_blender_value(auto_determine: bool, selected_enum: str) -> str:
    """
    Convenience: resolve the right enum and return the worker/API payload string.
    """
    return to_worker_blender_value(
        resolve_selected_blender_enum(auto_determine, selected_enum)
    )
