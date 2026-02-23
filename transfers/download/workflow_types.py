"""Typed stage contracts for download workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

JsonMap = Dict[str, Any]


@dataclass
class DownloadRunContext:
    data: JsonMap
    job_id: str
    job_name: str
    download_path: str
    dest_dir: str
    download_type: str
    sarfis_url: Optional[str]
    sarfis_token: Optional[str]


@dataclass
class PreflightResult:
    preflight_ok: bool
    preflight_issues: List[str]
    rclone_bin: str
    fatal_error: Optional[str] = None


@dataclass
class StorageResolutionResult:
    s3info: Optional[JsonMap] = None
    bucket: str = ""
    base_cmd: List[str] = field(default_factory=list)
    fatal_error: Optional[str] = None


@dataclass
class DownloadDispatchResult:
    fatal_error: Optional[str] = None


@dataclass
class BootstrapDeps:
    clear_console: Callable[[], None]
    open_folder: Callable[[str], None]
    requests_retry_session: Callable[[], Any]
    run_preflight_checks: Callable[..., Any]
    ensure_rclone: Callable[..., Any]
    run_rclone: Callable[..., Any]
    build_base_fn: Callable[..., List[str]]
    cloudflare_r2_domain: str
    create_logger: Callable[..., Any]
    build_download_context: Callable[[JsonMap], DownloadRunContext]
    ensure_dir: Callable[[str], None]
    run_preflight_phase: Callable[..., PreflightResult]
    resolve_storage: Callable[..., StorageResolutionResult]
    run_download_dispatch: Callable[..., DownloadDispatchResult]
    finalize_download: Callable[..., None]
