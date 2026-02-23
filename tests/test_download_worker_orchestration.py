from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

download_worker = importlib.import_module("transfers.download.download_worker")
workflow_types = importlib.import_module("transfers.download.workflow_types")


class _Logger:
    def __init__(self):
        self.started = []
        self.fatals = []
        self.warn_blocks = []

    def logo_start(self, **kwargs):
        self.started.append(kwargs)

    def logo_end(self, **kwargs):
        return "c"

    def fatal(self, message):
        self.fatals.append(str(message))
        raise SystemExit(1)

    def warn_block(self, message, severity="warning"):
        self.warn_blocks.append((str(message), str(severity)))


class TestDownloadWorkerOrchestration(unittest.TestCase):
    def test_main_runs_stage_sequence(self):
        calls = []
        logger = _Logger()

        context = workflow_types.DownloadRunContext(
            data={"project": {"id": "p"}, "pocketbase_url": "https://pb"},
            job_id="job1",
            job_name="Job 1",
            download_path="/tmp",
            dest_dir="/tmp/Job 1",
            download_type="single",
            sarfis_url=None,
            sarfis_token=None,
        )
        preflight = workflow_types.PreflightResult(
            preflight_ok=True,
            preflight_issues=[],
            rclone_bin="/tmp/rclone",
        )
        storage = workflow_types.StorageResolutionResult(
            s3info={"bucket_name": "render-bucket"},
            bucket="render-bucket",
            base_cmd=["rclone"],
        )

        deps = workflow_types.BootstrapDeps(
            clear_console=lambda: calls.append("clear"),
            open_folder=lambda path: calls.append(("open", path)),
            requests_retry_session=lambda: "session",
            run_preflight_checks=lambda **kwargs: (True, []),
            ensure_rclone=lambda **kwargs: "/tmp/rclone",
            run_rclone=lambda *args, **kwargs: None,
            build_base_fn=lambda *args: ["rclone"],
            cloudflare_r2_domain="example.com",
            create_logger=lambda: logger,
            build_download_context=lambda data: calls.append("context") or context,
            ensure_dir=lambda path: calls.append(("ensure_dir", path)),
            run_preflight_phase=lambda **kwargs: calls.append("preflight") or preflight,
            resolve_storage=lambda **kwargs: calls.append("storage") or storage,
            run_download_dispatch=lambda **kwargs: calls.append("dispatch")
            or workflow_types.DownloadDispatchResult(),
            finalize_download=lambda **kwargs: calls.append("finalize"),
        )

        handoff = {
            "addon_dir": "/tmp/addon",
            "user_token": "token",
            "project": {"id": "p"},
            "pocketbase_url": "https://pb",
        }

        with patch.object(download_worker, "_load_handoff_from_argv", return_value=handoff), patch.object(
            download_worker, "_bootstrap_addon_modules", return_value=deps
        ):
            download_worker.main()

        self.assertEqual(
            ["clear", "context", "preflight", "storage", ("ensure_dir", "/tmp"), "dispatch", "finalize"],
            calls,
        )

    def test_preflight_fatal_path_exits_via_logger_fatal(self):
        logger = _Logger()
        context = workflow_types.DownloadRunContext(
            data={"project": {"id": "p"}, "pocketbase_url": "https://pb"},
            job_id="job1",
            job_name="Job 1",
            download_path="/tmp",
            dest_dir="/tmp/Job 1",
            download_type="single",
            sarfis_url=None,
            sarfis_token=None,
        )
        deps = workflow_types.BootstrapDeps(
            clear_console=lambda: None,
            open_folder=lambda path: None,
            requests_retry_session=lambda: "session",
            run_preflight_checks=lambda **kwargs: (True, []),
            ensure_rclone=lambda **kwargs: "/tmp/rclone",
            run_rclone=lambda *args, **kwargs: None,
            build_base_fn=lambda *args: ["rclone"],
            cloudflare_r2_domain="example.com",
            create_logger=lambda: logger,
            build_download_context=lambda data: context,
            ensure_dir=lambda path: None,
            run_preflight_phase=lambda **kwargs: workflow_types.PreflightResult(
                preflight_ok=True,
                preflight_issues=[],
                rclone_bin="",
                fatal_error="Couldn't set up transfer tool: boom",
            ),
            resolve_storage=lambda **kwargs: workflow_types.StorageResolutionResult(),
            run_download_dispatch=lambda **kwargs: workflow_types.DownloadDispatchResult(),
            finalize_download=lambda **kwargs: None,
        )

        handoff = {
            "addon_dir": "/tmp/addon",
            "user_token": "token",
            "project": {"id": "p"},
            "pocketbase_url": "https://pb",
        }

        with patch.object(download_worker, "_load_handoff_from_argv", return_value=handoff), patch.object(
            download_worker, "_bootstrap_addon_modules", return_value=deps
        ):
            with self.assertRaises(SystemExit):
                download_worker.main()

        self.assertEqual(1, len(logger.fatals))
        self.assertIn("Couldn't set up transfer tool", logger.fatals[0])


if __name__ == "__main__":
    unittest.main()
