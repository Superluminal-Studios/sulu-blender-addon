"""Context and path helpers for download workflow."""

from __future__ import annotations

import os
import re
from typing import Dict

from .workflow_types import DownloadRunContext

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def safe_dir_name(name: str, fallback: str) -> str:
    """Make a filesystem-safe folder name (cross-platform)."""
    normalized = re.sub(r"[\\/:*?\"<>|]+", "_", str(name)).strip()
    return normalized or fallback


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def count_existing_files(path: str) -> int:
    """Count files already in destination (for resume detection)."""
    if not os.path.isdir(path):
        return 0

    count = 0
    for _, _, files in os.walk(path):
        count += len(files)
    return count


def _is_absolute_path(path: str) -> bool:
    return (
        os.path.isabs(path)
        or bool(_WINDOWS_ABS_PATH_RE.match(path))
        or path.startswith("\\\\")
    )


def resolve_download_path(raw_path: str, base_dir: str) -> str:
    """Resolve Blender-style and plain relative download paths to absolute."""
    value = str(raw_path or "").strip()
    anchor = os.path.abspath(str(base_dir or "").strip() or os.getcwd())

    if not value:
        value = "//"

    if value.startswith("//"):
        suffix = value[2:].lstrip("/\\")
        if suffix:
            return os.path.abspath(os.path.join(anchor, suffix))
        return anchor

    if _is_absolute_path(value):
        return os.path.abspath(value)

    return os.path.abspath(os.path.join(anchor, value))


def build_download_context(data: Dict[str, object]) -> DownloadRunContext:
    job_id = str(data.get("job_id", "") or "").strip()
    job_name = str(data.get("job_name", "") or f"job_{job_id}").strip() or f"job_{job_id}"
    download_path = resolve_download_path(
        str(data.get("download_path", "") or ""),
        str(data.get("download_base_dir", "") or ""),
    )
    safe_job_dir = safe_dir_name(job_name, f"job_{job_id}")
    dest_dir = os.path.abspath(os.path.join(download_path, safe_job_dir))

    sarfis_url = data.get("sarfis_url")
    sarfis_token = data.get("sarfis_token")

    requested_mode = str(data.get("download_type", "") or "").lower()
    if requested_mode in {"single", "auto"}:
        download_type = requested_mode
    else:
        download_type = "auto" if sarfis_url and sarfis_token else "single"

    return DownloadRunContext(
        data=dict(data),
        job_id=job_id,
        job_name=job_name,
        download_path=download_path,
        dest_dir=dest_dir,
        download_type=download_type,
        sarfis_url=sarfis_url,
        sarfis_token=sarfis_token,
    )
