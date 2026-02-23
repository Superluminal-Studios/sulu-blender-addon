from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_types = importlib.import_module("transfers.download.workflow_types")
workflow_transfer = importlib.import_module("transfers.download.workflow_transfer")


class _Logger:
    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []
        self.successes = []
        self.transfer_titles = []
        self.completes = []
        self.resume = []
        self.auto_info_called = 0

    def info(self, msg):
        self.infos.append(str(msg))

    def warning(self, msg):
        self.warnings.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))

    def success(self, msg):
        self.successes.append(str(msg))

    def transfer_start(self, title):
        self.transfer_titles.append(str(title))

    def transfer_complete(self, msg):
        self.completes.append(str(msg))

    def resume_info(self, count):
        self.resume.append(int(count))

    def auto_mode_info(self):
        self.auto_info_called += 1


def _context(*, download_type: str = "single", with_sarfis: bool = False):
    return workflow_types.DownloadRunContext(
        data={},
        job_id="job1",
        job_name="Job 1",
        download_path="/tmp",
        dest_dir="/tmp/Job 1",
        download_type=download_type,
        sarfis_url="https://sarfis.example" if with_sarfis else None,
        sarfis_token="token" if with_sarfis else None,
    )


class TestDownloadWorkflowTransfer(unittest.TestCase):
    def test_rclone_copy_output_missing_remote_returns_false(self):
        logger = _Logger()

        def _raise(*args, **kwargs):
            raise RuntimeError("404 no such key")

        ok = workflow_transfer.rclone_copy_output(
            base_cmd=["rclone"],
            run_rclone=_raise,
            bucket="render-bucket",
            job_id="job1",
            dest_dir="/tmp/out",
            logger=logger,
        )
        self.assertFalse(ok)
        self.assertIn("No frames available yet", logger.infos)

    def test_rclone_copy_output_non_missing_runtime_error_raises(self):
        logger = _Logger()

        def _raise(*args, **kwargs):
            raise RuntimeError("permission denied")

        with self.assertRaises(RuntimeError):
            workflow_transfer.rclone_copy_output(
                base_cmd=["rclone"],
                run_rclone=_raise,
                bucket="render-bucket",
                job_id="job1",
                dest_dir="/tmp/out",
                logger=logger,
            )
        self.assertTrue(any("Download stopped" in msg for msg in logger.errors))

    def test_run_download_dispatch_single_mode_calls_single_downloader(self):
        logger = _Logger()
        single_calls = []
        auto_calls = []
        with patch.object(
            workflow_transfer,
            "single_downloader",
            side_effect=lambda **kwargs: single_calls.append(kwargs),
        ), patch.object(
            workflow_transfer,
            "auto_downloader",
            side_effect=lambda **kwargs: auto_calls.append(kwargs),
        ), patch.object(
            workflow_transfer,
            "fetch_job_details",
            return_value=("running", 1, 10),
        ):
            result = workflow_transfer.run_download_dispatch(
                context=_context(download_type="single", with_sarfis=True),
                logger=logger,
                session=object(),
                run_rclone=lambda *args, **kwargs: None,
                base_cmd=["rclone"],
                bucket="render-bucket",
            )

        self.assertIsNone(result.fatal_error)
        self.assertEqual(1, len(single_calls))
        self.assertEqual(0, len(auto_calls))

    def test_run_download_dispatch_auto_mode_with_sarfis_calls_auto(self):
        logger = _Logger()
        single_calls = []
        auto_calls = []
        with patch.object(
            workflow_transfer,
            "single_downloader",
            side_effect=lambda **kwargs: single_calls.append(kwargs),
        ), patch.object(
            workflow_transfer,
            "auto_downloader",
            side_effect=lambda **kwargs: auto_calls.append(kwargs),
        ), patch.object(
            workflow_transfer,
            "fetch_job_details",
            return_value=("running", 1, 10),
        ):
            workflow_transfer.run_download_dispatch(
                context=_context(download_type="auto", with_sarfis=True),
                logger=logger,
                session=object(),
                run_rclone=lambda *args, **kwargs: None,
                base_cmd=["rclone"],
                bucket="render-bucket",
            )

        self.assertEqual(0, len(single_calls))
        self.assertEqual(1, len(auto_calls))

    def test_run_download_dispatch_auto_mode_without_sarfis_warns_and_runs_single(self):
        logger = _Logger()
        single_calls = []
        with patch.object(
            workflow_transfer,
            "single_downloader",
            side_effect=lambda **kwargs: single_calls.append(kwargs),
        ), patch.object(
            workflow_transfer,
            "fetch_job_details",
            return_value=("unknown", 0, 0),
        ):
            workflow_transfer.run_download_dispatch(
                context=_context(download_type="auto", with_sarfis=False),
                logger=logger,
                session=object(),
                run_rclone=lambda *args, **kwargs: None,
                base_cmd=["rclone"],
                bucket="render-bucket",
            )

        self.assertEqual(1, len(single_calls))
        self.assertTrue(
            any("Can't track job progress" in message for message in logger.warnings)
        )

    def test_run_download_dispatch_finished_job_forces_single(self):
        logger = _Logger()
        single_calls = []
        auto_calls = []
        with patch.object(
            workflow_transfer,
            "single_downloader",
            side_effect=lambda **kwargs: single_calls.append(kwargs),
        ), patch.object(
            workflow_transfer,
            "auto_downloader",
            side_effect=lambda **kwargs: auto_calls.append(kwargs),
        ), patch.object(
            workflow_transfer,
            "fetch_job_details",
            return_value=("finished", 10, 10),
        ):
            workflow_transfer.run_download_dispatch(
                context=_context(download_type="auto", with_sarfis=True),
                logger=logger,
                session=object(),
                run_rclone=lambda *args, **kwargs: None,
                base_cmd=["rclone"],
                bucket="render-bucket",
            )

        self.assertEqual(1, len(single_calls))
        self.assertEqual(0, len(auto_calls))

    def test_auto_downloader_finishes_and_logs_success(self):
        logger = _Logger()
        with tempfile.TemporaryDirectory() as td:
            context = workflow_types.DownloadRunContext(
                data={},
                job_id="job1",
                job_name="Job 1",
                download_path=td,
                dest_dir=str(Path(td) / "Job 1"),
                download_type="auto",
                sarfis_url="https://sarfis.example",
                sarfis_token="token",
            )

            calls = {"fetch": 0, "copy": 0}

            def _fetch():
                calls["fetch"] += 1
                if calls["fetch"] == 1:
                    return ("running", 3, 10)
                return ("finished", 3, 10)

            def _copy(_dest):
                calls["copy"] += 1
                return True

            workflow_transfer.auto_downloader(
                context=context,
                logger=logger,
                fetch_job_details_fn=_fetch,
                copy_output_fn=_copy,
                poll_seconds=1,
                sleep_fn=lambda _: None,
            )

            self.assertEqual(1, logger.auto_info_called)
            self.assertTrue(any("frames downloaded" in s for s in logger.successes))
            self.assertGreaterEqual(calls["copy"], 2)


if __name__ == "__main__":
    unittest.main()
