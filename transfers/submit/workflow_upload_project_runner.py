"""Project-mode upload stage runner."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, List

from .workflow_types import StageArtifacts, SubmitRunContext, UploadDeps, UploadResult
from .workflow_runtime_helpers import (
    check_rclone_errors,
    get_rclone_tail,
    is_empty_upload,
    is_filesystem_root,
    log_upload_result,
    rclone_bytes,
    rclone_stats,
)
from .workflow_upload import (
    record_manifest_touch_mismatch,
    run_addons_upload_step,
    split_manifest_by_first_dir,
)


def run_upload_project_stage(
    *,
    context: SubmitRunContext,
    artifacts: StageArtifacts,
    logger,
    report,
    bucket: str,
    base_cmd: List[str],
    rclone_settings: List[str],
    deps: UploadDeps,
) -> UploadResult:
    data = context.data
    blend_path = context.blend_path
    filelist = context.filelist
    job_id = context.job_id
    project_name = context.project_name

    common_path = artifacts.common_path
    rel_manifest = artifacts.rel_manifest
    main_blend_s3 = artifacts.main_blend_s3
    dependency_total_size = artifacts.dependency_total_size

    run_rclone = deps.run_rclone
    debug_enabled_fn = deps.debug_enabled_fn
    log_fn = deps.log_fn
    format_size_fn = deps.format_size_fn
    upload_touched_lt_manifest = deps.upload_touched_lt_manifest
    clean_key_fn = deps.clean_key_fn
    normalize_nfc_fn = deps.normalize_nfc_fn

    def _log_upload_result(
        result: Any,
        *,
        expected_bytes: int = 0,
        label: str = "",
    ) -> None:
        log_upload_result(
            result,
            expected_bytes=expected_bytes,
            label=label,
            debug_enabled_fn=debug_enabled_fn,
            format_size_fn=format_size_fn,
            log_fn=log_fn,
        )

    def _check_rclone_errors(result: Any, *, label: str = "") -> None:
        check_rclone_errors(
            result,
            label=label,
            debug_enabled_fn=debug_enabled_fn,
            log_fn=log_fn,
        )

    has_addons = data.get("packed_addons") and len(data["packed_addons"]) > 0
    total_steps = 3 if rel_manifest else 2
    if has_addons:
        total_steps += 1
    step = 1
    logger.upload_start(total_steps)

    blend_size = 0
    try:
        blend_size = os.path.getsize(blend_path)
    except OSError:
        # Keep upload flow tolerant when size metadata cannot be read.
        pass

    logger.upload_step(step, total_steps, "Uploading main blend")
    move_to_path = normalize_nfc_fn(clean_key_fn(f"{project_name}/{main_blend_s3}"))
    remote_main = f":s3:{bucket}/{move_to_path}"
    report.start_upload_step(
        step,
        total_steps,
        "Uploading main blend",
        expected_bytes=blend_size,
        source=blend_path,
        destination=remote_main,
        verb="copyto",
    )
    rclone_result = run_rclone(
        base_cmd,
        "copyto",
        blend_path,
        remote_main,
        extra=rclone_settings,
        logger=logger,
        total_bytes=blend_size,
    )
    if blend_size > 0 and logger._transfer_total == 0:
        logger._transfer_total = blend_size
    logger.upload_complete("Main blend uploaded")
    _log_upload_result(
        rclone_result,
        expected_bytes=blend_size,
        label="Blend: ",
    )
    report.complete_upload_step(
        bytes_transferred=rclone_bytes(rclone_result),
        rclone_stats=rclone_stats(rclone_result),
    )
    step += 1

    if rel_manifest:
        logger.upload_step(step, total_steps, "Uploading dependencies")
        if debug_enabled_fn():
            log_fn(
                f"Manifest: {len(rel_manifest)} files, {format_size_fn(dependency_total_size)} expected"
            )

        if is_filesystem_root(common_path):
            if debug_enabled_fn():
                log_fn(
                    f"Project root is a filesystem root ({common_path}), splitting upload by directory"
                )
            groups = split_manifest_by_first_dir(rel_manifest)
            if debug_enabled_fn():
                log_fn(f"Split into {len(groups)} group(s): {list(groups.keys())}")

            report.start_upload_step(
                step,
                total_steps,
                "Uploading dependencies (split)",
                manifest_entries=len(rel_manifest),
                expected_bytes=dependency_total_size,
                source=common_path,
                destination=f":s3:{bucket}/{project_name}/",
                verb="copy",
            )

            agg_bytes = 0
            agg_checks = 0
            agg_transfers = 0
            agg_errors = 0
            any_empty = False

            for group_name, group_entries in groups.items():
                if not group_entries:
                    continue

                if group_name:
                    group_source = common_path.rstrip("/") + "/" + group_name
                    group_dest = f":s3:{bucket}/{project_name}/{group_name}/"
                else:
                    group_source = common_path
                    group_dest = f":s3:{bucket}/{project_name}/"

                group_filelist = (
                    Path(tempfile.gettempdir())
                    / f"{job_id}_g_{hash(group_name) & 0xFFFF:04x}.txt"
                )
                try:
                    with group_filelist.open("w", encoding="utf-8") as fp:
                        for entry in group_entries:
                            fp.write(f"{entry}\\n")

                    try:
                        gl = group_filelist.read_text("utf-8").splitlines()
                        gc = len([line for line in gl if line.strip()])
                        if gc != len(group_entries) and debug_enabled_fn():
                            log_fn(
                                f"  WARNING: Group '{group_name}' filelist mismatch — "
                                f"expected {len(group_entries)}, got {gc}"
                            )
                    except (OSError, UnicodeError):
                        # Verification is optional and should not block upload.
                        pass

                    group_rclone = ["--files-from", str(group_filelist)]
                    group_rclone.extend(rclone_settings)

                    if debug_enabled_fn():
                        log_fn(
                            f"  Group '{group_name}': {len(group_entries)} files, source={group_source}"
                        )
                    grp_result = run_rclone(
                        base_cmd,
                        "copy",
                        group_source,
                        group_dest,
                        extra=group_rclone,
                        logger=logger,
                        total_bytes=dependency_total_size,
                    )
                    _log_upload_result(
                        grp_result,
                        label=f"  Group '{group_name}': ",
                    )
                    _check_rclone_errors(
                        grp_result,
                        label=f"Group '{group_name}'",
                    )
                    report.add_upload_split_group(
                        group_name=group_name or "(root)",
                        file_count=len(group_entries),
                        source=group_source,
                        destination=group_dest,
                        rclone_stats=rclone_stats(grp_result),
                    )

                    agg_bytes += rclone_bytes(grp_result)
                    if isinstance(grp_result, dict):
                        agg_checks += grp_result.get("checks", 0)
                        agg_transfers += grp_result.get("transfers", 0)
                        agg_errors += grp_result.get("errors", 0)

                    if is_empty_upload(grp_result, len(group_entries)):
                        any_empty = True
                        if debug_enabled_fn():
                            grp_tail = get_rclone_tail(grp_result)
                            log_fn(f"  WARNING: Group '{group_name}' transferred 0 files")
                            if grp_tail:
                                for line in grp_tail[-5:]:
                                    log_fn(f"    {line}")
                finally:
                    try:
                        group_filelist.unlink(missing_ok=True)
                    except OSError:
                        # Best-effort cleanup of temporary per-group manifest.
                        pass

            logger._transfer_total = dependency_total_size
            logger.upload_complete("Dependencies uploaded")
            if debug_enabled_fn():
                log_fn(
                    "  Split upload totals: "
                    f"transferred={format_size_fn(agg_bytes)}, "
                    f"checks={agg_checks}, transfers={agg_transfers}, "
                    f"errors={agg_errors}, groups={len(groups)}"
                )

            agg_stats = {
                "bytes_transferred": agg_bytes,
                "checks": agg_checks,
                "transfers": agg_transfers,
                "errors": agg_errors,
                "stats_received": True,
                "split_groups": len(groups),
            }
            report.complete_upload_step(
                bytes_transferred=agg_bytes,
                rclone_stats=agg_stats,
            )

            if any_empty and dependency_total_size > 0 and debug_enabled_fn():
                log_fn(
                    "WARNING: Some dependency groups transferred 0 files. "
                    "See diagnostic report."
                )

            total_touched = agg_transfers + agg_checks
            record_manifest_touch_mismatch(
                logger=logger,
                report=report,
                total_touched=total_touched,
                manifest_count=len(rel_manifest),
                issue_code=upload_touched_lt_manifest,
                issue_action="Retry upload and inspect manifest/source root alignment.",
                debug_enabled_fn=debug_enabled_fn,
                log_fn=log_fn,
            )
        else:
            report.start_upload_step(
                step,
                total_steps,
                "Uploading dependencies",
                manifest_entries=len(rel_manifest),
                expected_bytes=dependency_total_size,
                source=str(common_path),
                destination=f":s3:{bucket}/{project_name}/",
                verb="copy",
            )
            dependency_rclone_settings = ["--files-from", str(filelist)]
            dependency_rclone_settings.extend(rclone_settings)
            rclone_result = run_rclone(
                base_cmd,
                "copy",
                str(common_path),
                f":s3:{bucket}/{project_name}/",
                extra=dependency_rclone_settings,
                logger=logger,
                total_bytes=dependency_total_size,
            )
            logger.upload_complete("Dependencies uploaded")
            _log_upload_result(
                rclone_result,
                expected_bytes=dependency_total_size,
                label="Dependencies: ",
            )
            _check_rclone_errors(rclone_result, label="Dependencies")
            stats = rclone_stats(rclone_result)
            report.complete_upload_step(
                bytes_transferred=rclone_bytes(rclone_result),
                rclone_stats=stats,
            )
            if is_empty_upload(rclone_result, len(rel_manifest)) and debug_enabled_fn():
                tail = get_rclone_tail(rclone_result)
                log_fn(
                    f"WARNING: Expected {format_size_fn(dependency_total_size)} "
                    f"across {len(rel_manifest)} files, but rclone transferred 0. "
                    "See diagnostic report for details."
                )
                if tail:
                    log_fn("rclone tail log:")
                    for line in tail[-10:]:
                        log_fn(f"  {line}")

            if stats:
                total_touched = (stats.get("transfers", 0) or 0) + (
                    stats.get("checks", 0) or 0
                )
                record_manifest_touch_mismatch(
                    logger=logger,
                    report=report,
                    total_touched=total_touched,
                    manifest_count=len(rel_manifest),
                    issue_code=upload_touched_lt_manifest,
                    issue_action="Retry upload and inspect manifest/source root alignment.",
                    debug_enabled_fn=debug_enabled_fn,
                    log_fn=log_fn,
                )
        step += 1

    with filelist.open("a", encoding="utf-8") as fp:
        fp.write(normalize_nfc_fn(clean_key_fn(main_blend_s3)) + "\\n")

    logger.upload_step(step, total_steps, "Uploading manifest")
    report.start_upload_step(
        step,
        total_steps,
        "Uploading manifest",
        source=str(filelist),
        destination=f":s3:{bucket}/{project_name}/",
        verb="move",
    )
    rclone_result = run_rclone(
        base_cmd,
        "move",
        str(filelist),
        f":s3:{bucket}/{project_name}/",
        extra=rclone_settings,
        logger=logger,
    )
    logger.upload_complete("Manifest uploaded")
    _log_upload_result(rclone_result, label="Manifest: ")
    _check_rclone_errors(rclone_result, label="Manifest")
    report.complete_upload_step(
        bytes_transferred=rclone_bytes(rclone_result),
        rclone_stats=rclone_stats(rclone_result),
    )
    step += 1

    if has_addons:
        run_addons_upload_step(
            data=data,
            job_id=job_id,
            step=step,
            total_steps=total_steps,
            bucket=bucket,
            base_cmd=base_cmd,
            rclone_settings=rclone_settings,
            run_rclone=run_rclone,
            rclone_bytes_fn=rclone_bytes,
            rclone_stats_fn=rclone_stats,
            log_upload_result_fn=_log_upload_result,
            check_rclone_errors_fn=_check_rclone_errors,
            logger=logger,
            report=report,
        )

    return UploadResult()
