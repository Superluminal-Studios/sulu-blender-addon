"""Bootstrap dependency resolver for download worker."""

from __future__ import annotations

import importlib

from .workflow_types import BootstrapDeps


def resolve_bootstrap_deps(*, pkg_name: str) -> BootstrapDeps:
    worker_utils = importlib.import_module(f"{pkg_name}.utils.worker_utils")
    download_logger_mod = importlib.import_module(f"{pkg_name}.utils.download_logger")
    rclone = importlib.import_module(f"{pkg_name}.transfers.rclone_utils")

    workflow_context = importlib.import_module(f"{pkg_name}.transfers.download.workflow_context")
    workflow_preflight = importlib.import_module(
        f"{pkg_name}.transfers.download.workflow_preflight"
    )
    workflow_storage = importlib.import_module(f"{pkg_name}.transfers.download.workflow_storage")
    workflow_transfer = importlib.import_module(
        f"{pkg_name}.transfers.download.workflow_transfer"
    )
    workflow_finalize = importlib.import_module(f"{pkg_name}.transfers.download.workflow_finalize")

    create_logger = getattr(download_logger_mod, "create_logger", None)
    if not callable(create_logger):
        create_logger = download_logger_mod.DownloadLogger

    return BootstrapDeps(
        clear_console=worker_utils.clear_console,
        open_folder=worker_utils.open_folder,
        requests_retry_session=worker_utils.requests_retry_session,
        run_preflight_checks=worker_utils.run_preflight_checks,
        ensure_rclone=rclone.ensure_rclone,
        run_rclone=rclone.run_rclone,
        build_base_fn=worker_utils._build_base,
        cloudflare_r2_domain=worker_utils.CLOUDFLARE_R2_DOMAIN,
        create_logger=create_logger,
        build_download_context=workflow_context.build_download_context,
        ensure_dir=workflow_context.ensure_dir,
        run_preflight_phase=workflow_preflight.run_preflight_phase,
        resolve_storage=workflow_storage.resolve_storage,
        run_download_dispatch=workflow_transfer.run_download_dispatch,
        finalize_download=workflow_finalize.finalize_download,
    )
