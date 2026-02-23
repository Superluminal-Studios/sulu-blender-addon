"""Job registration and completion prompt handling for submit workflow."""

from __future__ import annotations

import json
import time
import webbrowser
from pathlib import Path
from typing import Dict, Sequence

import requests

from .workflow_types import FinalizeResult, FlowControl, SubmitRunContext


def finalize_submission(
    *,
    context: SubmitRunContext,
    session,
    headers: Dict[str, str],
    payload: Dict[str, object],
    logger,
    report,
    t_start: float,
    open_folder_fn,
    safe_input_fn,
    argv: Sequence[str],
) -> FinalizeResult:
    data = context.data

    try:
        post_resp = session.post(
            f"{data['pocketbase_url']}/api/farm/{context.org_id}/jobs",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        post_resp.raise_for_status()
    except requests.RequestException as exc:
        report.set_status("failed")
        return FinalizeResult(
            fatal_error=(
                "Couldn't register job. Check your connection and try again.\n"
                f"Details: {exc}"
            ),
        )

    report.finalize()

    elapsed = time.perf_counter() - t_start
    job_url = (
        f"https://superlumin.al/p/{context.project_sqid}/farm/jobs/{data['job_id']}"
    )

    selection = "c"
    try:
        selection = logger.logo_end(
            job_id=data["job_id"],
            elapsed=elapsed,
            job_url=job_url,
            report_path=str(report.get_reports_dir()),
        )
    except Exception:
        selection = "c"

    try:
        handoff_path = Path(argv[1]).resolve()
        handoff_path.unlink(missing_ok=True)
    except Exception:
        pass

    if selection == "j":
        try:
            webbrowser.open(job_url)
            logger.job_complete(job_url)
        except Exception:
            pass
        safe_input_fn("\nPress Enter to close.", "")
        return FinalizeResult(
            flow=FlowControl.exit_flow(0, "open_job"),
            selection=selection,
            job_url=job_url,
        )

    if selection == "r":
        try:
            open_folder_fn(str(report.get_reports_dir()), logger_instance=logger)
            logger.info("Diagnostic reports folder opened.")
        except Exception:
            pass
        safe_input_fn("\nPress Enter to close.", "")
        return FinalizeResult(
            flow=FlowControl.exit_flow(0, "open_reports"),
            selection=selection,
            job_url=job_url,
        )

    return FinalizeResult(
        flow=FlowControl.exit_flow(0, "close"),
        selection=selection,
        job_url=job_url,
    )
