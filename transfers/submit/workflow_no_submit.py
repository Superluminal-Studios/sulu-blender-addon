"""No-submit mode handler for submit workflow."""

from __future__ import annotations

from .workflow_types import FlowControl, StageArtifacts, SubmitRunContext


def handle_no_submit_mode(
    *,
    context: SubmitRunContext,
    artifacts: StageArtifacts,
    logger,
    safe_input_fn,
) -> FlowControl:
    if not context.no_submit:
        return FlowControl.continue_flow()

    zip_size = 0
    if not context.use_project and context.zip_file.exists():
        zip_size = context.zip_file.stat().st_size

    logger.no_submit_report(
        upload_type="PROJECT" if context.use_project else "ZIP",
        common_path=artifacts.common_path if context.use_project else "",
        rel_manifest_count=len(artifacts.rel_manifest) if context.use_project else 0,
        main_blend_s3=artifacts.main_blend_s3 if context.use_project else "",
        zip_file=str(context.zip_file) if not context.use_project else "",
        zip_size=zip_size,
        required_storage=artifacts.required_storage,
    )

    if not context.use_project and context.zip_file.exists():
        try:
            context.zip_file.unlink()
            logger.info(f"Temporary archive removed: {context.zip_file}")
        except Exception:
            pass

    safe_input_fn("\nPress Enter to close.", "")
    return FlowControl.exit_flow(0, "no_submit")
