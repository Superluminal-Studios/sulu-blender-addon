"""Project-mode trace stage for submit workflow."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from .workflow_types import (
    FlowControl,
    SubmitRunContext,
    TraceProjectDeps,
    TraceProjectResult,
)


def run_trace_project_stage(
    *,
    context: SubmitRunContext,
    logger,
    report,
    deps: TraceProjectDeps,
    is_mac: bool,
) -> TraceProjectResult:
    shorten_path_fn = deps.shorten_path_fn
    format_size_fn = deps.format_size_fn
    is_filesystem_root_fn = deps.is_filesystem_root_fn
    debug_enabled_fn = deps.debug_enabled_fn
    log_fn = deps.log_fn
    mac_permission_help_fn = deps.mac_permission_help_fn
    trace_dependencies = deps.trace_dependencies
    compute_project_root = deps.compute_project_root
    classify_out_of_root_ok_files = deps.classify_out_of_root_ok_files
    apply_project_validation = deps.apply_project_validation
    validate_project_upload = deps.validate_project_upload
    prompt_continue_with_reports = deps.prompt_continue_with_reports
    open_folder_fn = deps.open_folder_fn
    generate_test_report = deps.generate_test_report
    safe_input_fn = deps.safe_input_fn
    meta_project_validation_version = deps.meta_project_validation_version
    meta_project_validation_stats = deps.meta_project_validation_stats
    default_project_validation_version = deps.default_project_validation_version

    data = context.data
    blend_path = context.blend_path
    automatic_project_path = context.automatic_project_path
    custom_project_path_str = context.custom_project_path_str
    test_mode = context.test_mode

    logger.stage_header(
        1,
        "Tracing dependencies",
        "Scanning for external assets referenced by this blend file",
        details=[
            f"Main file: {Path(blend_path).name}",
            "Resolving dependencies",
        ],
    )
    logger.trace_start(blend_path)
    report.start_stage("trace")

    dep_paths, missing_set, unreadable_dict, raw_usages, optional_set = trace_dependencies(
        Path(blend_path),
        logger=logger,
        hydrate=True,
        diagnostic_report=report,
    )

    absolute_path_deps: List[Path] = []
    for usage in raw_usages:
        try:
            if getattr(usage, "is_optional", False):
                continue
            if not usage.asset_path.is_blendfile_relative():
                abs_path = usage.abspath
                if abs_path not in missing_set and abs_path not in unreadable_dict:
                    if abs_path not in absolute_path_deps:
                        absolute_path_deps.append(abs_path)
        except Exception:
            pass

    for abs_dep in absolute_path_deps:
        try:
            report.add_trace_entry(
                source_blend=blend_path,
                block_type="",
                block_name="",
                resolved_path=str(abs_dep),
                status="absolute_path",
                error_msg="Absolute path — farm cannot resolve. Make relative or use Zip upload.",
            )
        except Exception:
            pass

    ok_files_set = set(p for p in dep_paths if p not in missing_set and p not in unreadable_dict)
    ok_files_cache = set(str(p).replace("\\", "/") for p in ok_files_set)

    custom_root = None
    if not automatic_project_path:
        if not custom_project_path_str or not str(custom_project_path_str).strip():
            return TraceProjectResult(
                dep_paths=dep_paths,
                missing_set=set(missing_set),
                unreadable_dict=dict(unreadable_dict),
                raw_usages=list(raw_usages),
                optional_set=set(optional_set),
                project_root=Path(blend_path).parent,
                project_root_str=str(Path(blend_path).parent).replace("\\", "/"),
                same_drive_deps=[],
                cross_drive_deps=[],
                absolute_path_deps=absolute_path_deps,
                out_of_root_ok_files=[],
                ok_files_set=ok_files_set,
                ok_files_cache=ok_files_cache,
                fatal_error=(
                    "Custom project path is empty.\n"
                    "Turn on Automatic Project Path, or select a valid folder."
                ),
            )
        custom_root = Path(custom_project_path_str)

    project_root, same_drive_deps, cross_drive_deps = compute_project_root(
        Path(blend_path),
        dep_paths,
        custom_root,
        missing_files=missing_set,
        unreadable_files=unreadable_dict,
        optional_files=optional_set,
    )
    same_drive_deps = list(same_drive_deps)
    cross_drive_deps = list(cross_drive_deps)

    out_of_root_ok_files = list(
        classify_out_of_root_ok_files(
            same_drive_deps,
            project_root,
        )
    )
    common_path = str(project_root).replace("\\", "/")
    project_root_str = common_path
    report.set_metadata("project_root", common_path)

    if not automatic_project_path:
        report.set_metadata("project_root_method", "custom")
    elif is_filesystem_root_fn(common_path):
        report.set_metadata("project_root_method", "filesystem_root")
    else:
        report.set_metadata("project_root_method", "automatic")

    if is_filesystem_root_fn(common_path) and debug_enabled_fn():
        log_fn(
            f"NOTE: Project root is a filesystem root ({common_path}). "
            "Dependencies span multiple top-level directories on the same drive."
        )

    if cross_drive_deps:
        report.add_cross_drive_files([str(p) for p in cross_drive_deps])
    if absolute_path_deps:
        report.add_absolute_path_files([str(p) for p in absolute_path_deps])
    if out_of_root_ok_files:
        report.add_out_of_root_files([str(p) for p in out_of_root_ok_files])

    project_validation = apply_project_validation(
        validate_project_upload=validate_project_upload,
        blend_path=blend_path,
        project_root=project_root,
        dep_paths=dep_paths,
        raw_usages=raw_usages,
        missing_set=missing_set,
        unreadable_dict=unreadable_dict,
        optional_set=optional_set,
        cross_drive_deps=list(cross_drive_deps),
        absolute_path_deps=list(absolute_path_deps),
        out_of_root_ok_files=list(out_of_root_ok_files),
        report=report,
        metadata_project_validation_version=meta_project_validation_version,
        metadata_project_validation_stats=meta_project_validation_stats,
        validation_version=default_project_validation_version,
    )

    missing_files_list = [str(p) for p in sorted(missing_set)]
    unreadable_files_list = [
        (str(p), err)
        for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))
    ]
    absolute_path_files_list = [str(p) for p in sorted(absolute_path_deps)]
    out_of_root_files_list = [str(p) for p in sorted(out_of_root_ok_files)]

    has_issues = bool(
        cross_drive_deps
        or missing_files_list
        or unreadable_files_list
        or absolute_path_deps
        or out_of_root_files_list
        or project_validation.has_blocking_risk
    )

    warning_text = None
    if has_issues:
        warning_parts = []

        if absolute_path_deps:
            warning_parts.append(
                "Farm cannot resolve absolute paths. "
                "Make paths relative (File → External Data → Make All Paths Relative), or use Zip upload."
            )

        if cross_drive_deps:
            warning_parts.append(
                "Cross-drive files excluded from Project upload. "
                "Use Zip upload, or move files to the project drive."
            )

        if out_of_root_files_list:
            warning_parts.append(
                "Some dependencies are outside the selected project root and are excluded from Project upload. "
                "Use Zip upload, or broaden Custom Project Path."
            )

        if (
            (missing_files_list or unreadable_files_list)
            and not absolute_path_deps
            and not cross_drive_deps
        ):
            warning_parts.append("Missing or unreadable files excluded.")

        if project_validation.warnings:
            warning_parts.extend(project_validation.warnings)

        mac_extra = ""
        if is_mac and unreadable_files_list:
            for p, err in unreadable_files_list:
                low = err.lower()
                if (
                    "permission" in low
                    or "operation not permitted" in low
                    or "not permitted" in low
                ):
                    mac_extra = "\n" + mac_permission_help_fn(p, err)
                    break

        warning_text = "\n".join(warning_parts) + mac_extra if warning_parts else None

    logger.trace_summary(
        total=len(dep_paths),
        missing=len(missing_set),
        unreadable=len(unreadable_dict),
        project_root=shorten_path_fn(common_path),
        cross_drive=len(cross_drive_deps),
        warning_text=warning_text,
        cross_drive_excluded=True,
        missing_files=missing_files_list,
        unreadable_files=unreadable_files_list,
        cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
        absolute_path_files=absolute_path_files_list,
        out_of_root_files=out_of_root_files_list,
        shorten_fn=shorten_path_fn,
        automatic_project_path=automatic_project_path,
    )
    report.complete_stage("trace")

    if test_mode:
        by_ext: Dict[str, int] = {}
        total_size = 0
        for dep in dep_paths:
            ext = dep.suffix.lower() if dep.suffix else "(no ext)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            if dep.exists() and dep.is_file():
                try:
                    total_size += os.path.getsize(dep)
                except Exception:
                    pass

        _test_report_data, test_report_path = generate_test_report(
            blend_path=blend_path,
            dep_paths=dep_paths,
            missing_set=missing_set,
            unreadable_dict=unreadable_dict,
            project_root=project_root,
            same_drive_deps=same_drive_deps,
            cross_drive_deps=cross_drive_deps,
            upload_type="PROJECT",
            addon_dir=str(data["addon_dir"]),
            mode="test",
            format_size_fn=format_size_fn,
        )
        logger.test_report(
            blend_path=blend_path,
            dep_count=len(dep_paths),
            project_root=str(project_root),
            same_drive=len(same_drive_deps),
            cross_drive=len(cross_drive_deps),
            by_ext=by_ext,
            total_size=total_size,
            missing=[str(p) for p in sorted(missing_set)],
            unreadable=[
                (str(p), err)
                for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))
            ],
            cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
            upload_type="PROJECT",
            report_path=str(test_report_path) if test_report_path else None,
            shorten_fn=shorten_path_fn,
        )
        safe_input_fn("\nPress Enter to close.", "")
        return TraceProjectResult(
            dep_paths=dep_paths,
            missing_set=set(missing_set),
            unreadable_dict=dict(unreadable_dict),
            raw_usages=list(raw_usages),
            optional_set=set(optional_set),
            project_root=project_root,
            project_root_str=project_root_str,
            same_drive_deps=same_drive_deps,
            cross_drive_deps=cross_drive_deps,
            absolute_path_deps=absolute_path_deps,
            out_of_root_ok_files=out_of_root_ok_files,
            ok_files_set=ok_files_set,
            ok_files_cache=ok_files_cache,
            flow=FlowControl.exit_flow(0, "project_test_report"),
        )

    if has_issues:
        issue_prompt = "Some dependencies have problems. Continue anyway?"
        issue_default = "y"
        issue_choice_label = "Dependency issues found"
        if project_validation.has_blocking_risk:
            issue_prompt = (
                "Project upload risk detected (path mapping may fail on farm). Continue anyway?"
            )
            issue_default = "n"
            issue_choice_label = "Project upload blocking risks found"

        keep_going = prompt_continue_with_reports(
            logger=logger,
            report=report,
            prompt=issue_prompt,
            choice_label=issue_choice_label,
            open_folder_fn=open_folder_fn,
            default=issue_default,
            followup_default="y",
        )
        if not keep_going:
            return TraceProjectResult(
                dep_paths=dep_paths,
                missing_set=set(missing_set),
                unreadable_dict=dict(unreadable_dict),
                raw_usages=list(raw_usages),
                optional_set=set(optional_set),
                project_root=project_root,
                project_root_str=project_root_str,
                same_drive_deps=same_drive_deps,
                cross_drive_deps=cross_drive_deps,
                absolute_path_deps=absolute_path_deps,
                out_of_root_ok_files=out_of_root_ok_files,
                ok_files_set=ok_files_set,
                ok_files_cache=ok_files_cache,
                flow=FlowControl.exit_flow(1, "project_trace_cancelled"),
            )

    return TraceProjectResult(
        dep_paths=dep_paths,
        missing_set=set(missing_set),
        unreadable_dict=dict(unreadable_dict),
        raw_usages=list(raw_usages),
        optional_set=set(optional_set),
        project_root=project_root,
        project_root_str=project_root_str,
        same_drive_deps=same_drive_deps,
        cross_drive_deps=cross_drive_deps,
        absolute_path_deps=absolute_path_deps,
        out_of_root_ok_files=out_of_root_ok_files,
        ok_files_set=ok_files_set,
        ok_files_cache=ok_files_cache,
    )
