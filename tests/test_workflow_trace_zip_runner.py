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

workflow_trace_zip_runner = importlib.import_module(
    "transfers.submit.workflow_trace_zip_runner"
)
workflow_types = importlib.import_module("transfers.submit.workflow_types")


class _Logger:
    def stage_header(self, *args, **kwargs):
        return None

    def trace_start(self, *args, **kwargs):
        return None

    def trace_summary(self, *args, **kwargs):
        return None

    def test_report(self, *args, **kwargs):
        return None


class _Report:
    def start_stage(self, *args, **kwargs):
        return None

    def set_metadata(self, *args, **kwargs):
        return None

    def add_cross_drive_files(self, *args, **kwargs):
        return None

    def complete_stage(self, *args, **kwargs):
        return None


def _context(td: str, *, test_mode: bool) -> workflow_types.SubmitRunContext:
    blend_path = Path(td) / "scene.blend"
    blend_path.write_bytes(b"blend")
    return workflow_types.SubmitRunContext(
        data={"addon_dir": td},
        project={"id": "proj1"},
        blend_path=str(blend_path),
        use_project=False,
        automatic_project_path=True,
        custom_project_path_str="",
        job_id="job1",
        project_name="Proj",
        project_sqid="proj-sqid",
        org_id="org1",
        test_mode=test_mode,
        no_submit=False,
        zip_file=Path(td) / "job1.zip",
        filelist=Path(td) / "job1.txt",
    )


def _deps(
    *,
    trace_dependencies,
    compute_project_root,
    prompt_continue_with_reports,
    generate_test_report=lambda **kwargs: ({}, None),
) -> workflow_types.TraceZipDeps:
    return workflow_types.TraceZipDeps(
        shorten_path_fn=lambda p: p,
        format_size_fn=lambda n: str(n),
        trace_dependencies=trace_dependencies,
        compute_project_root=compute_project_root,
        prompt_continue_with_reports=prompt_continue_with_reports,
        open_folder_fn=lambda *args, **kwargs: None,
        generate_test_report=generate_test_report,
        safe_input_fn=lambda *args, **kwargs: None,
    )


class TestWorkflowTraceZipRunner(unittest.TestCase):
    def test_zip_test_mode_returns_exit_flow(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td, test_mode=True)
            dep = Path(context.blend_path)

            result = workflow_trace_zip_runner.run_trace_zip_stage(
                context=context,
                logger=_Logger(),
                report=_Report(),
                deps=_deps(
                    trace_dependencies=lambda *args, **kwargs: (
                        [dep],
                        set(),
                        {},
                        [],
                        set(),
                    ),
                    compute_project_root=lambda *args, **kwargs: (Path(td), [dep], []),
                    prompt_continue_with_reports=lambda **kwargs: True,
                    generate_test_report=lambda **kwargs: ({}, Path(td) / "report.json"),
                ),
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(0, result.flow.exit_code)
            self.assertEqual("zip_test_report", result.flow.reason)

    def test_zip_issue_cancel_returns_exit_flow(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td, test_mode=False)
            dep = Path(context.blend_path)

            result = workflow_trace_zip_runner.run_trace_zip_stage(
                context=context,
                logger=_Logger(),
                report=_Report(),
                deps=_deps(
                    trace_dependencies=lambda *args, **kwargs: (
                        [dep],
                        {Path(td) / "missing.exr"},
                        {},
                        [],
                        set(),
                    ),
                    compute_project_root=lambda *args, **kwargs: (Path(td), [dep], []),
                    prompt_continue_with_reports=lambda **kwargs: False,
                ),
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(1, result.flow.exit_code)
            self.assertEqual("zip_trace_cancelled", result.flow.reason)


if __name__ == "__main__":
    unittest.main()
