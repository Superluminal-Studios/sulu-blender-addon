"""Storage resolution stage for download workflow."""

from __future__ import annotations

from typing import Dict

import requests

from .workflow_types import DownloadRunContext, StorageResolutionResult


def resolve_storage(
    *,
    context: DownloadRunContext,
    session,
    headers: Dict[str, str],
    rclone_bin: str,
    build_base_fn,
    cloudflare_r2_domain: str,
) -> StorageResolutionResult:
    data = context.data
    try:
        s3_resp = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={"filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')"},
            timeout=30,
        )
        s3_resp.raise_for_status()
        payload = s3_resp.json()
        items = payload.get("items", [])
        if not items:
            raise IndexError("No storage records returned for this project.")
        s3info = items[0]
        bucket = s3info["bucket_name"]
    except (IndexError, requests.RequestException, KeyError) as exc:
        return StorageResolutionResult(
            fatal_error=f"Couldn't connect to storage: {exc}",
        )

    base_cmd = build_base_fn(
        rclone_bin,
        f"https://{cloudflare_r2_domain}",
        s3info,
    )
    return StorageResolutionResult(
        s3info=s3info,
        bucket=bucket,
        base_cmd=base_cmd,
    )
