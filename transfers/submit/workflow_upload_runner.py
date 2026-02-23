"""Stage 3 upload orchestration for submit workflow."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .workflow_types import StageArtifacts, SubmitRunContext, UploadDeps, UploadResult


def run_upload_stage(
    *,
    context: SubmitRunContext,
    artifacts: StageArtifacts,
    session,
    headers: Dict[str, str],
    logger,
    report,
    rclone_bin: str,
    deps: UploadDeps,
) -> UploadResult:
    data: Dict[str, Any] = context.data
    use_project = context.use_project
    blend_path = context.blend_path
    zip_file = context.zip_file
    filelist = context.filelist
    job_id = context.job_id
    project_name = context.project_name

    common_path = artifacts.common_path
    rel_manifest: List[str] = artifacts.rel_manifest
    main_blend_s3 = artifacts.main_blend_s3
    dependency_total_size = artifacts.dependency_total_size
    required_storage = artifacts.required_storage

    build_base_fn = deps.build_base_fn
    cloudflare_r2_domain = deps.cloudflare_r2_domain
    run_rclone = deps.run_rclone
    debug_enabled_fn = deps.debug_enabled_fn
    log_fn = deps.log_fn
    format_size_fn = deps.format_size_fn
    rclone_bytes_fn = deps.rclone_bytes_fn
    rclone_stats_fn = deps.rclone_stats_fn
    is_empty_upload_fn = deps.is_empty_upload_fn
    get_rclone_tail_fn = deps.get_rclone_tail_fn
    log_upload_result_fn = deps.log_upload_result_fn
    check_rclone_errors_fn = deps.check_rclone_errors_fn
    is_filesystem_root_fn = deps.is_filesystem_root_fn
    split_manifest_by_first_dir = deps.split_manifest_by_first_dir
    record_manifest_touch_mismatch = deps.record_manifest_touch_mismatch
    upload_touched_lt_manifest = deps.upload_touched_lt_manifest
    clean_key_fn = deps.clean_key_fn
    normalize_nfc_fn = deps.normalize_nfc_fn

    logger.stage_header(3, "Uploading", "Transferring data to farm storage")
    report.start_stage("upload")

    try:
        s3_response = session.get(
            f"{data['pocketbase_url']}/api/collections/project_storage/records",
            headers=headers,
            params={
                "filter": f"(project_id='{data['project']['id']}' && bucket_name~'render-')"
            },
            timeout=30,
        )
        s3_response.raise_for_status()
        s3info = s3_response.json()["items"][0]
        bucket = s3info["bucket_name"]
    except Exception as exc:
        report.set_status("failed")
        return UploadResult(
            fatal_error=(
                "Couldn't get storage credentials. Check your connection and try again.\n"
                f"Details: {exc}"
            )
        )

    base_cmd = build_base_fn(rclone_bin, f"https://{cloudflare_r2_domain}", s3info)

    rclone_settings = [
        "--transfers",
        "4",
        "--checkers",
        "4",
        "--s3-chunk-size",
        "64M",
        "--s3-upload-cutoff",
        "64M",
        "--s3-upload-concurrency",
        "4",
        "--buffer-size",
        "64M",
        "--retries",
        "20",
        "--low-level-retries",
        "20",
        "--retries-sleep",
        "5s",
        "--timeout",
        "5m",
        "--contimeout",
        "30s",
        "--no-traverse",
        "--stats",
        "0.1s",
    ]

    has_addons = data.get("packed_addons") and len(data["packed_addons"]) > 0

    try:
        if not use_project:
            total_steps = 2 if has_addons else 1
            step = 1
            logger.upload_start(total_steps)

            logger.upload_step(step, total_steps, "Uploading archive")
            report.start_upload_step(
                step,
                total_steps,
                "Uploading archive",
                expected_bytes=required_storage,
                source=str(zip_file),
                destination=f":s3:{bucket}/",
                verb="move",
            )
            rclone_result = run_rclone(
                base_cmd,
                "move",
                str(zip_file),
                f":s3:{bucket}/",
                extra=rclone_settings,
                logger=logger,
                total_bytes=required_storage,
            )
            if required_storage > 0 and logger._transfer_total == 0:
                logger._transfer_total = required_storage
            logger.upload_complete("Archive uploaded")
            log_upload_result_fn(
                rclone_result,
                expected_bytes=required_storage,
                label="Archive: ",
            )
            check_rclone_errors_fn(rclone_result, label="Archive")
            report.complete_upload_step(
                bytes_transferred=rclone_bytes_fn(rclone_result),
                rclone_stats=rclone_stats_fn(rclone_result),
            )
            step += 1

            if has_addons:
                logger.upload_step(step, total_steps, "Uploading add-ons")
                report.start_upload_step(
                    step,
                    total_steps,
                    "Uploading add-ons",
                    source=data["packed_addons_path"],
                    destination=f":s3:{bucket}/{job_id}/addons/",
                    verb="moveto",
                )
                rclone_result = run_rclone(
                    base_cmd,
                    "moveto",
                    data["packed_addons_path"],
                    f":s3:{bucket}/{job_id}/addons/",
                    extra=rclone_settings,
                    logger=logger,
                )
                logger.upload_complete("Add-ons uploaded")
                log_upload_result_fn(rclone_result, label="Add-ons: ")
                check_rclone_errors_fn(rclone_result, label="Add-ons")
                report.complete_upload_step(
                    bytes_transferred=rclone_bytes_fn(rclone_result),
                    rclone_stats=rclone_stats_fn(rclone_result),
                )
        else:
            total_steps = 3 if rel_manifest else 2
            if has_addons:
                total_steps += 1
            step = 1
            logger.upload_start(total_steps)

            blend_size = 0
            try:
                blend_size = os.path.getsize(blend_path)
            except Exception:
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
            log_upload_result_fn(
                rclone_result,
                expected_bytes=blend_size,
                label="Blend: ",
            )
            report.complete_upload_step(
                bytes_transferred=rclone_bytes_fn(rclone_result),
                rclone_stats=rclone_stats_fn(rclone_result),
            )
            step += 1

            if rel_manifest:
                logger.upload_step(step, total_steps, "Uploading dependencies")
                if debug_enabled_fn():
                    log_fn(
                        f"Manifest: {len(rel_manifest)} files, {format_size_fn(dependency_total_size)} expected"
                    )

                if is_filesystem_root_fn(common_path):
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
                        except Exception:
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
                        log_upload_result_fn(
                            grp_result,
                            label=f"  Group '{group_name}': ",
                        )
                        check_rclone_errors_fn(
                            grp_result,
                            label=f"Group '{group_name}'",
                        )
                        report.add_upload_split_group(
                            group_name=group_name or "(root)",
                            file_count=len(group_entries),
                            source=group_source,
                            destination=group_dest,
                            rclone_stats=rclone_stats_fn(grp_result),
                        )

                        try:
                            group_filelist.unlink(missing_ok=True)
                        except Exception:
                            pass

                        agg_bytes += rclone_bytes_fn(grp_result)
                        if isinstance(grp_result, dict):
                            agg_checks += grp_result.get("checks", 0)
                            agg_transfers += grp_result.get("transfers", 0)
                            agg_errors += grp_result.get("errors", 0)

                        if is_empty_upload_fn(grp_result, len(group_entries)):
                            any_empty = True
                            if debug_enabled_fn():
                                grp_tail = get_rclone_tail_fn(grp_result)
                                log_fn(
                                    f"  WARNING: Group '{group_name}' transferred 0 files"
                                )
                                if grp_tail:
                                    for line in grp_tail[-5:]:
                                        log_fn(f"    {line}")

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
                    log_upload_result_fn(
                        rclone_result,
                        expected_bytes=dependency_total_size,
                        label="Dependencies: ",
                    )
                    check_rclone_errors_fn(rclone_result, label="Dependencies")
                    stats = rclone_stats_fn(rclone_result)
                    report.complete_upload_step(
                        bytes_transferred=rclone_bytes_fn(rclone_result),
                        rclone_stats=stats,
                    )
                    if is_empty_upload_fn(rclone_result, len(rel_manifest)) and debug_enabled_fn():
                        tail = get_rclone_tail_fn(rclone_result)
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
            log_upload_result_fn(rclone_result, label="Manifest: ")
            check_rclone_errors_fn(rclone_result, label="Manifest")
            report.complete_upload_step(
                bytes_transferred=rclone_bytes_fn(rclone_result),
                rclone_stats=rclone_stats_fn(rclone_result),
            )
            step += 1

            if has_addons:
                logger.upload_step(step, total_steps, "Uploading add-ons")
                report.start_upload_step(
                    step,
                    total_steps,
                    "Uploading add-ons",
                    source=data["packed_addons_path"],
                    destination=f":s3:{bucket}/{job_id}/addons/",
                    verb="moveto",
                )
                rclone_result = run_rclone(
                    base_cmd,
                    "moveto",
                    data["packed_addons_path"],
                    f":s3:{bucket}/{job_id}/addons/",
                    extra=rclone_settings,
                    logger=logger,
                )
                logger.upload_complete("Add-ons uploaded")
                log_upload_result_fn(rclone_result, label="Add-ons: ")
                check_rclone_errors_fn(rclone_result, label="Add-ons")
                report.complete_upload_step(
                    bytes_transferred=rclone_bytes_fn(rclone_result),
                    rclone_stats=rclone_stats_fn(rclone_result),
                )

        report.complete_stage("upload")
    except RuntimeError as exc:
        report.set_status("failed")
        return UploadResult(
            fatal_error=(
                "Upload stopped. Check your connection and try again.\n"
                f"Details: {exc}"
            )
        )
    finally:
        try:
            if "packed_addons_path" in data and data["packed_addons_path"]:
                shutil.rmtree(data["packed_addons_path"], ignore_errors=True)
        except Exception:
            pass

    return UploadResult()
