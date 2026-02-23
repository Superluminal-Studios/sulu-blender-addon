"""Payload construction helpers for submit workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict


def build_job_payload(
    *,
    data: Dict[str, Any],
    org_id: str,
    project_name: str,
    blend_path: str,
    project_root_str: str,
    main_blend_s3: str,
    required_storage: int,
    use_project: bool,
    normalize_nfc_fn: Callable[[str], str],
    clean_key_fn: Callable[[str], str],
) -> Dict[str, object]:
    use_scene_image_format = bool(data.get("use_scene_image_format")) or (
        str(data.get("image_format", "")).upper() == "SCENE"
    )
    frame_step_val = int(data.get("frame_stepping_size", 1))

    return {
        "job_data": {
            "id": data["job_id"],
            "project_id": data["project"]["id"],
            "packed_addons": data["packed_addons"],
            "organization_id": org_id,
            "main_file": (
                normalize_nfc_fn(
                    str(Path(blend_path).relative_to(project_root_str)).replace(
                        "\\", "/"
                    )
                )
                if not use_project
                else normalize_nfc_fn(clean_key_fn(main_blend_s3))
            ),
            "project_path": project_name,
            "name": data["job_name"],
            "status": "queued",
            "start": data["start_frame"],
            "end": data["end_frame"],
            "frame_step": frame_step_val,
            "batch_size": 1,
            "image_format": data["image_format"],
            "use_scene_image_format": use_scene_image_format,
            "render_engine": data["render_engine"],
            "version": "20241125",
            "blender_version": data["blender_version"],
            "required_storage": required_storage,
            "zip": not use_project,
            "ignore_errors": data["ignore_errors"],
            "use_bserver": data["use_bserver"],
            "use_async_upload": data["use_async_upload"],
            "defer_status": data["use_async_upload"],
            "farm_url": data["farm_url"],
            "tasks": list(
                range(data["start_frame"], data["end_frame"] + 1, frame_step_val)
            ),
        }
    }
