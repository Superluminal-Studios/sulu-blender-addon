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

workflow_finalize = importlib.import_module("transfers.submit.workflow_finalize")
workflow_types = importlib.import_module("transfers.submit.workflow_types")


class _PostResponse:
    def raise_for_status(self):
        return None


class _Session:
    def __init__(self):
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _PostResponse()


class _Logger:
    def __init__(self, selection="c"):
        self.selection = selection
        self.job_complete_calls = []
        self.info_calls = []

    def logo_end(self, **kwargs):
        return self.selection

    def job_complete(self, url):
        self.job_complete_calls.append(url)

    def info(self, msg):
        self.info_calls.append(str(msg))

    def fatal(self, msg):
        raise RuntimeError(str(msg))


class _Report:
    def __init__(self, reports_dir: Path):
        self._reports_dir = reports_dir
        self.finalized = False

    def set_status(self, status):
        self.status = status

    def finalize(self):
        self.finalized = True

    def get_reports_dir(self):
        return self._reports_dir


class TestWorkflowFinalize(unittest.TestCase):
    def test_finalize_close_returns_exit_flow_and_cleans_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            reports_dir = Path(td) / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            handoff = Path(td) / "handoff.json"
            handoff.write_text("{}", encoding="utf-8")

            report = _Report(reports_dir)
            session = _Session()
            logger = _Logger(selection="c")
            context = workflow_types.SubmitRunContext(
                data={
                    "pocketbase_url": "https://pb",
                    "job_id": "job1",
                },
                project={"id": "proj-id"},
                blend_path="/tmp/scene.blend",
                use_project=True,
                automatic_project_path=True,
                custom_project_path_str="",
                job_id="job1",
                project_name="Proj",
                project_sqid="proj1",
                org_id="org1",
                test_mode=False,
                no_submit=False,
                zip_file=Path(td) / "job1.zip",
                filelist=Path(td) / "job1.txt",
            )

            result = workflow_finalize.finalize_submission(
                context=context,
                session=session,
                headers={"Authorization": "tok"},
                payload={"job_data": {}},
                logger=logger,
                report=report,
                t_start=0.0,
                open_folder_fn=lambda *args, **kwargs: None,
                safe_input_fn=lambda *args, **kwargs: None,
                argv=["submit_worker.py", str(handoff)],
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(0, result.flow.exit_code)
            self.assertTrue(report.finalized)
            self.assertFalse(handoff.exists())
            self.assertEqual(1, len(session.posts))


if __name__ == "__main__":
    unittest.main()
