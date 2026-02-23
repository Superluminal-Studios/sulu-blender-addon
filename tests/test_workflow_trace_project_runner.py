from __future__ import annotations

import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_trace_project_runner = importlib.import_module(
    "transfers.submit.workflow_trace_project_runner"
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

    def add_trace_entry(self, *args, **kwargs):
        return None

    def set_metadata(self, *args, **kwargs):
        return None

    def add_cross_drive_files(self, *args, **kwargs):
        return None

    def add_absolute_path_files(self, *args, **kwargs):
        return None

    def add_out_of_root_files(self, *args, **kwargs):
        return None

    def complete_stage(self, *args, **kwargs):
        return None


def _context(
    td: str,
    *,
    automatic_project_path: bool,
    custom_project_path_str: str,
    test_mode: bool,
) -> workflow_types.SubmitRunContext:
    blend_path = Path(td) / "scene.blend"
    blend_path.write_bytes(b"blend")
    return workflow_types.SubmitRunContext(
        data={"addon_dir": td},
        project={"id": "proj1"},
        blend_path=str(blend_path),
        use_project=True,
        automatic_project_path=automatic_project_path,
        custom_project_path_str=custom_project_path_str,
        job_id="job1",
        project_name="Proj",
        project_sqid="proj-sqid",
        org_id="org1",
        test_mode=test_mode,
        no_submit=False,
        zip_file=Path(td) / "job1.zip",
        filelist=Path(td) / "job1.txt",
    )


def _validation_result(has_blocking_risk: bool = False):
    return types.SimpleNamespace(
        has_blocking_risk=has_blocking_risk,
        warnings=[],
    )


def _deps(
    *,
    trace_dependencies,
    compute_project_root,
    classify_out_of_root_ok_files,
    apply_project_validation,
    prompt_continue_with_reports,
    generate_test_report=lambda **kwargs: ({}, None),
) -> workflow_types.TraceProjectDeps:
    return workflow_types.TraceProjectDeps(
        shorten_path_fn=lambda p: p,
        format_size_fn=lambda n: str(n),
        is_filesystem_root_fn=lambda p: False,
        debug_enabled_fn=lambda: False,
        log_fn=lambda msg: None,
        mac_permission_help_fn=lambda p, err: "",
        trace_dependencies=trace_dependencies,
        compute_project_root=compute_project_root,
        classify_out_of_root_ok_files=classify_out_of_root_ok_files,
        apply_project_validation=apply_project_validation,
        validate_project_upload=lambda **kwargs: None,
        prompt_continue_with_reports=prompt_continue_with_reports,
        open_folder_fn=lambda *args, **kwargs: None,
        generate_test_report=generate_test_report,
        safe_input_fn=lambda *args, **kwargs: None,
        meta_project_validation_version="v1",
        meta_project_validation_stats="stats",
        default_project_validation_version="1.0",
    )


class TestWorkflowTraceProjectRunner(unittest.TestCase):
    def test_custom_project_path_empty_returns_fatal_error(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(
                td,
                automatic_project_path=False,
                custom_project_path_str="",
                test_mode=False,
            )

            result = workflow_trace_project_runner.run_trace_project_stage(
                context=context,
                logger=_Logger(),
                report=_Report(),
                deps=_deps(
                    trace_dependencies=lambda *args, **kwargs: (
                        [Path(td) / "tex.png"],
                        set(),
                        {},
                        [],
                        set(),
                    ),
                    compute_project_root=lambda *args, **kwargs: (Path(td), [], []),
                    classify_out_of_root_ok_files=lambda *args, **kwargs: [],
                    apply_project_validation=lambda **kwargs: _validation_result(False),
                    prompt_continue_with_reports=lambda **kwargs: True,
                ),
                is_mac=False,
            )

            self.assertIsNotNone(result.fatal_error)
            self.assertIn("Custom project path is empty", result.fatal_error)
            self.assertFalse(result.flow.should_exit)

    def test_project_test_mode_returns_exit_flow(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(
                td,
                automatic_project_path=True,
                custom_project_path_str="",
                test_mode=True,
            )

            dep = Path(context.blend_path)
            result = workflow_trace_project_runner.run_trace_project_stage(
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
                    classify_out_of_root_ok_files=lambda *args, **kwargs: [],
                    apply_project_validation=lambda **kwargs: _validation_result(False),
                    prompt_continue_with_reports=lambda **kwargs: True,
                    generate_test_report=lambda **kwargs: ({}, Path(td) / "report.json"),
                ),
                is_mac=False,
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(0, result.flow.exit_code)
            self.assertEqual("project_test_report", result.flow.reason)

    def test_project_issue_cancel_returns_exit_flow(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(
                td,
                automatic_project_path=True,
                custom_project_path_str="",
                test_mode=False,
            )

            dep = Path(context.blend_path)
            missing = {Path(td) / "missing.png"}
            result = workflow_trace_project_runner.run_trace_project_stage(
                context=context,
                logger=_Logger(),
                report=_Report(),
                deps=_deps(
                    trace_dependencies=lambda *args, **kwargs: (
                        [dep],
                        missing,
                        {},
                        [],
                        set(),
                    ),
                    compute_project_root=lambda *args, **kwargs: (Path(td), [dep], []),
                    classify_out_of_root_ok_files=lambda *args, **kwargs: [],
                    apply_project_validation=lambda **kwargs: _validation_result(False),
                    prompt_continue_with_reports=lambda **kwargs: False,
                ),
                is_mac=False,
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(1, result.flow.exit_code)
            self.assertEqual("project_trace_cancelled", result.flow.reason)


if __name__ == "__main__":
    unittest.main()
