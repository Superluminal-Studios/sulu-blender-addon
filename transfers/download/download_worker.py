"""
download_worker.py – Superluminal: asset downloader.

Modes:
- "single": one-time download of everything currently available
- "auto"  : periodically pulls new/updated frames as they appear
"""

from __future__ import annotations

import importlib
import json
import sys
import time
import traceback
import types
from pathlib import Path
from typing import Dict, List


def _load_handoff_from_argv(argv: List[str]) -> Dict[str, object]:
    if len(argv) < 2:
        raise RuntimeError(
            "download_worker.py launched without a handoff JSON path.\n"
            "This script should be run as a subprocess by the add-on."
        )
    handoff_path = Path(argv[1]).resolve(strict=True)
    return json.loads(handoff_path.read_text("utf-8"))


def _bootstrap_addon_modules(data: Dict[str, object]):
    addon_dir = Path(data["addon_dir"]).resolve()
    pkg_name = addon_dir.name.replace("-", "_")

    if str(addon_dir.parent) not in sys.path:
        sys.path.insert(0, str(addon_dir.parent))

    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(addon_dir)]
    sys.modules[pkg_name] = pkg

    workflow_bootstrap = importlib.import_module(
        f"{pkg_name}.transfers.download.workflow_bootstrap"
    )
    return workflow_bootstrap.resolve_bootstrap_deps(pkg_name=pkg_name)


def main() -> None:
    t_start = time.perf_counter()
    data = _load_handoff_from_argv(sys.argv)
    deps = _bootstrap_addon_modules(data)

    deps.clear_console()
    logger = deps.create_logger()
    session = deps.requests_retry_session()
    context = deps.build_download_context(data)

    logger.logo_start(job_name=context.job_name, dest_dir=context.dest_dir)

    preflight = deps.run_preflight_phase(
        context=context,
        session=session,
        logger=logger,
        run_preflight_checks=deps.run_preflight_checks,
        ensure_rclone=deps.ensure_rclone,
    )
    if preflight.fatal_error:
        logger.fatal(preflight.fatal_error)

    headers = {"Authorization": data["user_token"]}
    storage = deps.resolve_storage(
        context=context,
        session=session,
        headers=headers,
        rclone_bin=preflight.rclone_bin,
        build_base_fn=deps.build_base_fn,
        cloudflare_r2_domain=deps.cloudflare_r2_domain,
    )
    if storage.fatal_error:
        logger.fatal(storage.fatal_error)

    deps.ensure_dir(context.download_path)

    try:
        dispatch_result = deps.run_download_dispatch(
            context=context,
            logger=logger,
            session=session,
            run_rclone=deps.run_rclone,
            base_cmd=storage.base_cmd,
            bucket=storage.bucket,
        )
        if dispatch_result.fatal_error:
            logger.fatal(dispatch_result.fatal_error)

        elapsed = time.perf_counter() - t_start
        deps.finalize_download(
            logger=logger,
            elapsed=elapsed,
            dest_dir=context.dest_dir,
            open_folder_fn=deps.open_folder,
        )
    except KeyboardInterrupt:
        logger.warn_block("Download interrupted. Run again to resume.", severity="warning")
        try:
            input("\nPress Enter to close.")
        except Exception:
            pass
    except Exception as exc:
        logger.fatal(f"Download stopped: {exc}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        print(f"\nCouldn't start download: {exc}")
        try:
            input("\nPress Enter to close.")
        except Exception:
            pass
        sys.exit(1)
