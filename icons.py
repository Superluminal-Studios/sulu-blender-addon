from __future__ import annotations

import os
import bpy.utils.previews

# Fallback built-in icons (used if custom icons fail to load)
_FALLBACK_ICONS = {
    "ERROR":    "RESTRICT_RENDER_ON",
    "FINISHED": "CHECKBOX_HLT",
    "PAUSED":   "PAUSE",
    "RUNNING":  "DISCLOSURE_TRI_RIGHT",
    "QUEUED":   "RECOVER_LAST",
    "LOGO":     "RESTRICT_RENDER_OFF",
}

_preview_collections: dict[str, bpy.utils.previews.ImagePreviewCollection] = {}


def get_icon_id(name: str) -> int:
    """Get the icon_id for a custom icon by name. Returns 0 if not loaded."""
    pcoll = _preview_collections.get("main")
    if pcoll and name in pcoll:
        return pcoll[name].icon_id
    return 0


def get_status_icon_id(status: str) -> int:
    """Get icon_id for a job status (case-insensitive)."""
    return get_icon_id(status.upper())


def get_fallback_icon(name: str) -> str:
    """Get the fallback built-in icon name."""
    return _FALLBACK_ICONS.get(name.upper(), "FILE_FOLDER")


def register():
    """Load custom icons from the icons/ directory."""
    if "main" in _preview_collections:
        return  # Already loaded

    pcoll = bpy.utils.previews.new()
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")

    icon_files = {
        "LOGO":     "logo.png",
        "ERROR":    "error.png",
        "FINISHED": "finished.png",
        "PAUSED":   "paused.png",
        "RUNNING":  "running.png",
        "QUEUED":   "queued.png",
    }

    for name, filename in icon_files.items():
        filepath = os.path.join(icons_dir, filename)
        if os.path.exists(filepath):
            pcoll.load(name, filepath, "IMAGE")

    _preview_collections["main"] = pcoll


def unregister():
    """Unload custom icons."""
    for pcoll in _preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    _preview_collections.clear()


# Legacy compatibility - keep icon_values for any code still using it
icon_values = _FALLBACK_ICONS