"""Zip-mode trace stage for submit workflow."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from .workflow_types import FlowControl, SubmitRunContext, TraceZipDeps, TraceZipResult


def run_trace_zip_stage(
    *,
    context: SubmitRunContext,
    logger,
    report,
    deps: TraceZipDeps,
) -> TraceZipResult:
    shorten_path_fn = deps.shorten_path_fn
    format_size_fn = deps.format_size_fn
    trace_dependencies = deps.trace_dependencies
    compute_project_root = deps.compute_project_root
    prompt_continue_with_reports = deps.prompt_continue_with_reports
    open_folder_fn = deps.open_folder_fn
    generate_test_report = deps.generate_test_report
    safe_input_fn = deps.safe_input_fn

    data = context.data
    blend_path = context.blend_path
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
        Path(blend_path), logger=logger, diagnostic_report=report
    )

    project_root, same_drive_deps, cross_drive_deps = compute_project_root(
        Path(blend_path),
        dep_paths,
        missing_files=missing_set,
        unreadable_files=unreadable_dict,
        optional_files=optional_set,
    )
    same_drive_deps = list(same_drive_deps)
    cross_drive_deps = list(cross_drive_deps)

    project_root_str = str(project_root).replace("\\", "/")
    report.set_metadata("project_root", project_root_str)
    report.set_metadata("project_root_method", "automatic")
    if cross_drive_deps:
        report.add_cross_drive_files([str(p) for p in cross_drive_deps])

    missing_files_list = [str(p) for p in sorted(missing_set)]
    unreadable_files_list = [
        (str(p), err)
        for p, err in sorted(unreadable_dict.items(), key=lambda x: str(x[0]))
    ]
    has_zip_issues = bool(missing_files_list or unreadable_files_list)
    zip_warning_text = "The archive may be incomplete." if has_zip_issues else None

    logger.trace_summary(
        total=len(dep_paths),
        missing=len(missing_set),
        unreadable=len(unreadable_dict),
        project_root=shorten_path_fn(project_root_str),
        cross_drive=len(cross_drive_deps),
        warning_text=zip_warning_text,
        cross_drive_excluded=False,
        missing_files=missing_files_list,
        unreadable_files=unreadable_files_list,
        cross_drive_files=[str(p) for p in sorted(cross_drive_deps)],
        shorten_fn=shorten_path_fn,
        automatic_project_path=True,
    )
    report.complete_stage("trace")

    if has_zip_issues:
        keep_going = prompt_continue_with_reports(
            logger=logger,
            report=report,
            prompt="Some dependencies have problems. Continue anyway?",
            choice_label="Dependency issues found",
            open_folder_fn=open_folder_fn,
            default="y",
            followup_default="y",
        )
        if not keep_going:
            return TraceZipResult(
                dep_paths=dep_paths,
                missing_set=set(missing_set),
                unreadable_dict=dict(unreadable_dict),
                raw_usages=list(raw_usages),
                optional_set=set(optional_set),
                project_root=project_root,
                project_root_str=project_root_str,
                same_drive_deps=same_drive_deps,
                cross_drive_deps=cross_drive_deps,
                flow=FlowControl.exit_flow(1, "zip_trace_cancelled"),
            )

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
            upload_type="ZIP",
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
            upload_type="ZIP",
            report_path=str(test_report_path) if test_report_path else None,
            shorten_fn=shorten_path_fn,
        )
        safe_input_fn("\nPress Enter to close.", "")
        return TraceZipResult(
            dep_paths=dep_paths,
            missing_set=set(missing_set),
            unreadable_dict=dict(unreadable_dict),
            raw_usages=list(raw_usages),
            optional_set=set(optional_set),
            project_root=project_root,
            project_root_str=project_root_str,
            same_drive_deps=same_drive_deps,
            cross_drive_deps=cross_drive_deps,
            flow=FlowControl.exit_flow(0, "zip_test_report"),
        )

    return TraceZipResult(
        dep_paths=dep_paths,
        missing_set=set(missing_set),
        unreadable_dict=dict(unreadable_dict),
        raw_usages=list(raw_usages),
        optional_set=set(optional_set),
        project_root=project_root,
        project_root_str=project_root_str,
        same_drive_deps=same_drive_deps,
        cross_drive_deps=cross_drive_deps,
    )
