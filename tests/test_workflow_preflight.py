from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_preflight = importlib.import_module("transfers.submit.workflow_preflight")
workflow_types = importlib.import_module("transfers.submit.workflow_types")


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "releases/latest" in url:
            return _Response(status_code=500)
        if "/api/farm_status/" in url:
            return _Response(status_code=200)
        return _Response(status_code=200)


class _WorkerUtils:
    @staticmethod
    def run_preflight_checks(session, storage_checks):
        return True, []


class _FailingWorkerUtils:
    @staticmethod
    def run_preflight_checks(session, storage_checks):
        return False, ["disk low"]


class _Logger:
    def __init__(self, choice="y"):
        self.choice = choice
        self.info_msgs = []

    def ask_choice(self, prompt, options, default="n"):
        return self.choice

    def version_update(self, *args, **kwargs):
        return "n"

    def info_exit(self, msg):
        raise SystemExit(0)

    def info(self, msg):
        self.info_msgs.append(str(msg))

    def error(self, msg):
        self.info_msgs.append(str(msg))

    def fatal(self, msg):
        raise RuntimeError(str(msg))


class TestWorkflowPreflight(unittest.TestCase):
    @staticmethod
    def _context(blend_path: Path, td: str):
        data = {
            "blend_path": str(blend_path),
            "use_project_upload": False,
            "addon_version": [1, 0, 0],
            "user_token": "token",
            "pocketbase_url": "https://pb",
            "job_id": "job1",
        }
        return workflow_types.SubmitRunContext(
            data=data,
            project={"organization_id": "org", "sqid": "proj-sqid", "name": "Proj"},
            blend_path=str(blend_path),
            use_project=False,
            automatic_project_path=True,
            custom_project_path_str="",
            job_id="job1",
            project_name="Proj",
            project_sqid="proj-sqid",
            org_id="org",
            test_mode=False,
            no_submit=False,
            zip_file=Path(td) / "job1.zip",
            filelist=Path(td) / "job1.txt",
        )

    def test_success_returns_headers_and_rclone(self):
        with tempfile.TemporaryDirectory() as td:
            blend = Path(td) / "scene.blend"
            blend.write_bytes(b"ok")
            context = self._context(blend, td)

            result = workflow_preflight.run_preflight_phase(
                context=context,
                session=_Session(),
                logger=_Logger(),
                worker_utils=_WorkerUtils(),
                ensure_rclone=lambda logger: "/tmp/rclone",
                debug_enabled_fn=lambda: False,
            )

            self.assertEqual({"Authorization": "token"}, result.headers)
            self.assertEqual("/tmp/rclone", result.rclone_bin)
            self.assertTrue(result.preflight_ok)
            self.assertFalse(result.flow.should_exit)
            self.assertIsNone(result.fatal_error)

    def test_preflight_cancel_returns_exit_flow(self):
        with tempfile.TemporaryDirectory() as td:
            blend = Path(td) / "scene.blend"
            blend.write_bytes(b"ok")
            context = self._context(blend, td)

            result = workflow_preflight.run_preflight_phase(
                context=context,
                session=_Session(),
                logger=_Logger(choice="n"),
                worker_utils=_FailingWorkerUtils(),
                ensure_rclone=lambda logger: "/tmp/rclone",
                debug_enabled_fn=lambda: False,
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(1, result.flow.exit_code)
            self.assertEqual("preflight_cancelled", result.flow.reason)


if __name__ == "__main__":
    unittest.main()
