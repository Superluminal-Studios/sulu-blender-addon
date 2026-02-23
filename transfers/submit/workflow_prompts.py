"""Shared user-prompt flows for submit workflow stages."""

from __future__ import annotations

from typing import Callable


def standard_continue_options() -> list[tuple[str, str, str]]:
    return [
        ("y", "Continue", "Proceed with submission"),
        ("n", "Cancel", "Cancel and close"),
        (
            "r",
            "Open diagnostic reports",
            "Open the diagnostic reports folder",
        ),
    ]


def prompt_continue_with_reports(
    *,
    logger,
    report,
    prompt: str,
    choice_label: str,
    open_folder_fn: Callable,
    default: str = "y",
    followup_prompt: str = "Continue with submission?",
    followup_default: str = "y",
    followup_choice_label: str = "Continue after viewing reports?",
) -> bool:
    answer = logger.ask_choice(
        prompt,
        standard_continue_options(),
        default=default,
    )
    report.record_user_choice(
        choice_label,
        answer,
        options=["Continue", "Cancel", "Open reports"],
    )

    if answer == "r":
        logger.report_info(str(report.get_path()))
        open_folder_fn(str(report.get_reports_dir()), logger_instance=logger)
        answer = logger.ask_choice(
            followup_prompt,
            [
                ("y", "Continue", "Proceed with submission"),
                ("n", "Cancel", "Cancel and close"),
            ],
            default=followup_default,
        )
        report.record_user_choice(
            followup_choice_label,
            answer,
            options=["Continue", "Cancel"],
        )

    if answer != "y":
        report.set_status("cancelled")
        return False
    return True
