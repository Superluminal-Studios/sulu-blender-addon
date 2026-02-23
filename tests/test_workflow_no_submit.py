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

workflow_no_submit = importlib.import_module("transfers.submit.workflow_no_submit")
workflow_types = importlib.import_module("transfers.submit.workflow_types")


class _Logger:
    def __init__(self):
        self.report_calls = []
        self.infos = []

    def no_submit_report(self, **kwargs):
        self.report_calls.append(kwargs)

    def info(self, msg):
        self.infos.append(str(msg))


class TestWorkflowNoSubmit(unittest.TestCase):
    @staticmethod
    def _context(td: str, *, no_submit: bool, use_project: bool):
        return workflow_types.SubmitRunContext(
            data={"job_id": "job1"},
            project={"id": "proj1"},
            blend_path="/tmp/scene.blend",
            use_project=use_project,
            automatic_project_path=True,
            custom_project_path_str="",
            job_id="job1",
            project_name="Proj",
            project_sqid="proj-sqid",
            org_id="org1",
            test_mode=False,
            no_submit=no_submit,
            zip_file=Path(td) / "job.zip",
            filelist=Path(td) / "job.txt",
        )

    @staticmethod
    def _artifacts(required_storage: int = 0):
        return workflow_types.StageArtifacts(
            project_root_str="/tmp",
            common_path="/tmp",
            rel_manifest=["a.txt"],
            main_blend_s3="scene.blend",
            required_storage=required_storage,
            dependency_total_size=0,
        )

    def test_no_submit_false_is_noop(self):
        logger = _Logger()
        flow = workflow_no_submit.handle_no_submit_mode(
            context=self._context("/tmp", no_submit=False, use_project=False),
            artifacts=self._artifacts(),
            logger=logger,
            safe_input_fn=lambda *args, **kwargs: None,
        )
        self.assertEqual([], logger.report_calls)
        self.assertFalse(flow.should_exit)

    def test_no_submit_zip_mode_returns_exit_flow_and_removes_zip(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "job.zip"
            z.write_bytes(b"zip")
            logger = _Logger()
            context = self._context(td, no_submit=True, use_project=False)
            context.zip_file = z

            flow = workflow_no_submit.handle_no_submit_mode(
                context=context,
                artifacts=self._artifacts(required_storage=123),
                logger=logger,
                safe_input_fn=lambda *args, **kwargs: None,
            )

            self.assertTrue(flow.should_exit)
            self.assertEqual(0, flow.exit_code)
            self.assertEqual("no_submit", flow.reason)
            self.assertFalse(z.exists())
            self.assertEqual(1, len(logger.report_calls))


if __name__ == "__main__":
    unittest.main()
