from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_types = importlib.import_module("transfers.download.workflow_types")
workflow_preflight = importlib.import_module("transfers.download.workflow_preflight")


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(str(msg))


def _context() -> workflow_types.DownloadRunContext:
    return workflow_types.DownloadRunContext(
        data={"project": {"id": "p"}, "pocketbase_url": "https://pb"},
        job_id="job1",
        job_name="Job 1",
        download_path="/tmp",
        dest_dir="/tmp/Job 1",
        download_type="single",
        sarfis_url=None,
        sarfis_token=None,
    )


class TestDownloadWorkflowPreflight(unittest.TestCase):
    def test_success_returns_rclone_and_issues(self):
        logger = _Logger()
        result = workflow_preflight.run_preflight_phase(
            context=_context(),
            session=object(),
            logger=logger,
            run_preflight_checks=lambda **kwargs: (False, ["disk low"]),
            ensure_rclone=lambda logger: "/tmp/rclone",
        )
        self.assertFalse(result.preflight_ok)
        self.assertEqual(["disk low"], result.preflight_issues)
        self.assertEqual("/tmp/rclone", result.rclone_bin)
        self.assertIsNone(result.fatal_error)
        self.assertEqual(["disk low"], logger.warnings)

    def test_rclone_setup_failure_returns_fatal_error(self):
        logger = _Logger()

        def _raise(*args, **kwargs):
            raise RuntimeError("install failed")

        result = workflow_preflight.run_preflight_phase(
            context=_context(),
            session=object(),
            logger=logger,
            run_preflight_checks=lambda **kwargs: (True, []),
            ensure_rclone=_raise,
        )
        self.assertIn("Couldn't set up transfer tool", result.fatal_error or "")


if __name__ == "__main__":
    unittest.main()
