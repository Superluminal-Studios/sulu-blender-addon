"""Typed stage contracts for submit workflow refactors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

JsonMap = Dict[str, Any]
LogFn = Callable[[str], None]
DebugEnabledFn = Callable[[], bool]
FormatSizeFn = Callable[[int], str]
StringTransformFn = Callable[[str], str]
BuildBaseFn = Callable[..., List[str]]
RunRcloneFn = Callable[..., Any]


@dataclass(frozen=True)
class FlowControl:
    """Outcome contract for stage control flow."""

    exit_code: Optional[int] = None
    reason: str = ""

    @property
    def should_exit(self) -> bool:
        return self.exit_code is not None

    @classmethod
    def continue_flow(cls) -> "FlowControl":
        return cls(exit_code=None, reason="")

    @classmethod
    def exit_flow(cls, code: int, reason: str = "") -> "FlowControl":
        return cls(exit_code=int(code), reason=str(reason or ""))


@dataclass
class SubmitRunContext:
    data: JsonMap
    project: JsonMap
    blend_path: str
    use_project: bool
    automatic_project_path: bool
    custom_project_path_str: str
    job_id: str
    project_name: str
    project_sqid: str
    org_id: str
    test_mode: bool
    no_submit: bool
    zip_file: Path
    filelist: Path


@dataclass
class ManifestBuildResult:
    rel_manifest: List[str]
    manifest_source_map: Dict[str, str]
    dependency_total_size: int
    ok_count: int


@dataclass
class StageArtifacts:
    project_root_str: str
    common_path: str
    rel_manifest: List[str]
    main_blend_s3: str
    required_storage: int
    dependency_total_size: int


@dataclass
class TraceProjectResult:
    dep_paths: List[Path]
    missing_set: set[Path]
    unreadable_dict: Dict[Path, str]
    raw_usages: List[Any]
    optional_set: set[Path]
    project_root: Path
    project_root_str: str
    same_drive_deps: List[Path]
    cross_drive_deps: List[Path]
    absolute_path_deps: List[Path]
    out_of_root_ok_files: List[Path]
    ok_files_set: set[Path]
    ok_files_cache: set[str]
    flow: FlowControl = field(default_factory=FlowControl.continue_flow)
    fatal_error: Optional[str] = None


@dataclass
class TraceZipResult:
    dep_paths: List[Path]
    missing_set: set[Path]
    unreadable_dict: Dict[Path, str]
    raw_usages: List[Any]
    optional_set: set[Path]
    project_root: Path
    project_root_str: str
    same_drive_deps: List[Path]
    cross_drive_deps: List[Path]
    flow: FlowControl = field(default_factory=FlowControl.continue_flow)
    fatal_error: Optional[str] = None


@dataclass
class PackProjectResult:
    artifacts: Optional[StageArtifacts] = None
    flow: FlowControl = field(default_factory=FlowControl.continue_flow)
    fatal_error: Optional[str] = None


@dataclass
class PackZipResult:
    artifacts: Optional[StageArtifacts] = None
    flow: FlowControl = field(default_factory=FlowControl.continue_flow)
    fatal_error: Optional[str] = None


@dataclass
class PreflightResult:
    preflight_ok: bool
    preflight_issues: List[str]
    preflight_user_override: Optional[bool]
    headers: Dict[str, str]
    rclone_bin: str
    flow: FlowControl = field(default_factory=FlowControl.continue_flow)
    fatal_error: Optional[str] = None


@dataclass
class UploadResult:
    total_bytes_transferred: int = 0
    total_checks: int = 0
    total_transfers: int = 0
    total_errors: int = 0
    flow: FlowControl = field(default_factory=FlowControl.continue_flow)
    fatal_error: Optional[str] = None


@dataclass
class FinalizeResult:
    flow: FlowControl = field(default_factory=FlowControl.continue_flow)
    selection: str = "c"
    job_url: str = ""
    fatal_error: Optional[str] = None


@dataclass(frozen=True)
class TraceProjectDeps:
    shorten_path_fn: Any
    format_size_fn: Any
    is_filesystem_root_fn: Any
    debug_enabled_fn: Any
    log_fn: Any
    mac_permission_help_fn: Any
    trace_dependencies: Any
    compute_project_root: Any
    classify_out_of_root_ok_files: Any
    apply_project_validation: Any
    validate_project_upload: Any
    prompt_continue_with_reports: Any
    open_folder_fn: Any
    generate_test_report: Any
    safe_input_fn: Any
    meta_project_validation_version: str
    meta_project_validation_stats: str
    default_project_validation_version: str


@dataclass(frozen=True)
class TraceZipDeps:
    shorten_path_fn: Any
    format_size_fn: Any
    trace_dependencies: Any
    compute_project_root: Any
    prompt_continue_with_reports: Any
    open_folder_fn: Any
    generate_test_report: Any
    safe_input_fn: Any


@dataclass(frozen=True)
class PackProjectDeps:
    pack_blend: Any
    norm_abs_for_detection_fn: Any
    build_project_manifest_from_map: Any
    samepath_fn: Any
    relpath_safe_fn: Any
    clean_key_fn: Any
    normalize_nfc_fn: Any
    apply_manifest_validation: Any
    validate_manifest_entries: Any
    write_manifest_file: Any
    validate_manifest_writeback: Any
    prompt_continue_with_reports: Any
    open_folder_fn: Any
    meta_manifest_entry_count: str
    meta_manifest_source_match_count: str
    meta_manifest_validation_stats: str
    debug_enabled_fn: Any
    log_fn: Any


@dataclass(frozen=True)
class PackZipDeps:
    pack_blend: Any
    norm_abs_for_detection_fn: Any


@dataclass(frozen=True)
class UploadDeps:
    build_base_fn: BuildBaseFn
    cloudflare_r2_domain: str
    run_rclone: RunRcloneFn
    debug_enabled_fn: DebugEnabledFn
    log_fn: LogFn
    format_size_fn: FormatSizeFn
    upload_touched_lt_manifest: str
    clean_key_fn: StringTransformFn
    normalize_nfc_fn: StringTransformFn


@dataclass
class BootstrapDeps:
    pkg_name: str
    worker_utils: Any
    safe_input: Any
    clear_console: Any
    is_blend_saved: Any
    requests_retry_session: Any
    open_folder: Any
    build_job_payload: Any
    create_logger: Any
    ensure_rclone: Any
    diagnostic_report_class: Any
    trace_project_deps: TraceProjectDeps
    trace_zip_deps: TraceZipDeps
    pack_project_deps: PackProjectDeps
    pack_zip_deps: PackZipDeps
    upload_deps: UploadDeps
    run_preflight_phase: Any
    run_trace_project_stage: Any
    run_trace_zip_stage: Any
    run_pack_project_stage: Any
    run_pack_zip_stage: Any
    run_upload_stage: Any
    handle_no_submit_mode: Any
    finalize_submission: Any
