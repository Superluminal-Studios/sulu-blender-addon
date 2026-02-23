"""Preflight and runtime readiness checks for submit workflow."""

from __future__ import annotations

import os
import tempfile
import webbrowser

from .workflow_types import FlowControl, PreflightResult, SubmitRunContext


def run_preflight_phase(
    *,
    context: SubmitRunContext,
    session,
    logger,
    worker_utils,
    ensure_rclone,
    debug_enabled_fn,
) -> PreflightResult:
    data = context.data
    project = context.project

    blend_size = 0
    try:
        blend_size = os.path.getsize(data["blend_path"])
    except Exception:
        pass

    use_project = bool(data.get("use_project_upload"))
    temp_needed = blend_size * 2 if not use_project else 10 * 1024 * 1024
    storage_checks = [(tempfile.gettempdir(), temp_needed, "Temp folder")]

    preflight_ok, preflight_issues = worker_utils.run_preflight_checks(
        session=session,
        storage_checks=storage_checks,
    )

    preflight_user_override = None
    if not preflight_ok and preflight_issues:
        issue_text = "\n".join(f"• {issue}" for issue in preflight_issues)
        answer = logger.ask_choice(
            issue_text,
            [
                ("y", "Continue", "Upload anyway"),
                ("n", "Cancel", "Exit and resolve issues"),
            ],
            default="n",
        )
        if answer != "y":
            return PreflightResult(
                preflight_ok=preflight_ok,
                preflight_issues=list(preflight_issues),
                preflight_user_override=preflight_user_override,
                headers={"Authorization": data["user_token"]},
                rclone_bin="",
                flow=FlowControl.exit_flow(1, "preflight_cancelled"),
            )
        preflight_user_override = True

    try:
        github_response = session.get(
            "https://api.github.com/repos/Superluminal-Studios/sulu-blender-addon/releases/latest"
        )
        if github_response.status_code == 200:
            latest_version = github_response.json().get("tag_name")
            if latest_version:
                latest_version_tuple = tuple(int(i) for i in latest_version.split("."))
                if latest_version_tuple > tuple(data["addon_version"]):
                    answer = logger.version_update(
                        "https://superlumin.al/blender-addon",
                        [
                            "Download the add-on .zip file from the link.",
                            "Uninstall the current add-on in Blender preferences.",
                            "Install the downloaded .zip file.",
                            "Restart Blender.",
                        ],
                        prompt="Update now?",
                        options=[
                            ("y", "Update", "Open the download page and close"),
                            ("n", "Not now", "Continue with current version"),
                        ],
                        default="n",
                    )
                    if answer == "y":
                        webbrowser.open("https://superlumin.al/blender-addon")
                        try:
                            logger.info(
                                "Install the new version, then restart Blender."
                            )
                        except Exception:
                            pass
                        return PreflightResult(
                            preflight_ok=preflight_ok,
                            preflight_issues=list(preflight_issues),
                            preflight_user_override=preflight_user_override,
                            headers={"Authorization": data["user_token"]},
                            rclone_bin="",
                            flow=FlowControl.exit_flow(0, "update_requested"),
                        )
    except Exception:
        logger.info("Couldn't check for add-on updates. Continuing with current version.")

    headers = {"Authorization": data["user_token"]}

    try:
        rclone_bin = ensure_rclone(logger=logger)
    except Exception as exc:
        return PreflightResult(
            preflight_ok=preflight_ok,
            preflight_issues=list(preflight_issues),
            preflight_user_override=preflight_user_override,
            headers=headers,
            rclone_bin="",
            fatal_error=(
                "Couldn't set up transfer tool. "
                "Restart Blender. If this keeps happening, reinstall the add-on.\n"
                f"Details: {exc}"
            ),
        )

    try:
        farm_status = session.get(
            f"{data['pocketbase_url']}/api/farm_status/{project['organization_id']}",
            headers=headers,
            timeout=30,
        )
        if farm_status.status_code != 200:
            if debug_enabled_fn():
                try:
                    logger.error(f"Farm status check response: {farm_status.json()}")
                except Exception:
                    logger.error(f"Farm status check response: {farm_status.text}")

            return PreflightResult(
                preflight_ok=preflight_ok,
                preflight_issues=list(preflight_issues),
                preflight_user_override=preflight_user_override,
                headers=headers,
                rclone_bin=str(rclone_bin),
                fatal_error=(
                    "Couldn't confirm farm availability.\n"
                    "Verify you're logged in and a project is selected. "
                    "If this continues, log out and log back in."
                ),
            )
    except Exception as exc:
        if debug_enabled_fn():
            logger.error(f"Farm status check exception: {exc}")
        return PreflightResult(
            preflight_ok=preflight_ok,
            preflight_issues=list(preflight_issues),
            preflight_user_override=preflight_user_override,
            headers=headers,
            rclone_bin=str(rclone_bin),
            fatal_error=(
                "Couldn't confirm farm availability.\n"
                "Verify you're logged in and a project is selected. "
                "If this continues, log out and log back in."
            ),
        )

    return PreflightResult(
        preflight_ok=preflight_ok,
        preflight_issues=list(preflight_issues),
        preflight_user_override=preflight_user_override,
        headers=headers,
        rclone_bin=str(rclone_bin),
    )
