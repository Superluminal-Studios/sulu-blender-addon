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

workflow_trace_pack_runner = importlib.import_module(
    "transfers.submit.workflow_trace_pack_runner"
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

    def complete_stage(self, *args, **kwargs):
        return None


def _context(
    td: str,
    *,
    use_project: bool,
    automatic_project_path: bool,
    custom_project_path_str: str,
    test_mode: bool,
) -> workflow_types.SubmitRunContext:
    return workflow_types.SubmitRunContext(
        data={"addon_dir": td},
        project={"id": "proj1"},
        blend_path=str(Path(td) / "scene.blend"),
        use_project=use_project,
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


class TestWorkflowTracePackRunner(unittest.TestCase):
    def test_custom_project_path_empty_returns_fatal_error(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(
                td,
                use_project=True,
                automatic_project_path=False,
                custom_project_path_str="",
                test_mode=False,
            )

            result = workflow_trace_pack_runner.run_trace_and_pack_stage(
                context=context,
                logger=_Logger(),
                report=_Report(),
                shorten_path_fn=lambda p: p,
                format_size_fn=lambda n: str(n),
                is_filesystem_root_fn=lambda p: False,
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
                is_mac=False,
                mac_permission_help_fn=lambda p, err: "",
                trace_dependencies=lambda *args, **kwargs: (
                    [Path(td) / "tex.png"],
                    set(),
                    {},
                    [],
                    set(),
                ),
                compute_project_root=lambda *args, **kwargs: (Path(td), [], []),
                classify_out_of_root_ok_files=lambda *args, **kwargs: [],
                apply_project_validation=lambda **kwargs: None,
                validate_project_upload=lambda **kwargs: None,
                meta_project_validation_version="v1",
                meta_project_validation_stats="stats",
                default_project_validation_version="1.0",
                prompt_continue_with_reports=lambda **kwargs: True,
                open_folder_fn=lambda *args, **kwargs: None,
                pack_blend=lambda *args, **kwargs: ({}, None),
                norm_abs_for_detection_fn=lambda p: p,
                build_project_manifest_from_map=lambda **kwargs: None,
                samepath_fn=lambda a, b: a == b,
                relpath_safe_fn=lambda p, b: p,
                clean_key_fn=lambda k: k,
                normalize_nfc_fn=lambda s: s,
                apply_manifest_validation=lambda **kwargs: ([], True),
                validate_manifest_entries=lambda *args, **kwargs: None,
                write_manifest_file=lambda *args, **kwargs: None,
                validate_manifest_writeback=lambda **kwargs: None,
                meta_manifest_entry_count="c",
                meta_manifest_source_match_count="m",
                meta_manifest_validation_stats="s",
                generate_test_report=lambda **kwargs: ({}, None),
                safe_input_fn=lambda *args, **kwargs: None,
            )

            self.assertIsNotNone(result.fatal_error)
            self.assertIn("Custom project path is empty", result.fatal_error)
            self.assertFalse(result.flow.should_exit)

    def test_zip_test_mode_returns_exit_flow(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(
                td,
                use_project=False,
                automatic_project_path=True,
                custom_project_path_str="",
                test_mode=True,
            )
            Path(context.blend_path).write_bytes(b"blend")

            result = workflow_trace_pack_runner.run_trace_and_pack_stage(
                context=context,
                logger=_Logger(),
                report=_Report(),
                shorten_path_fn=lambda p: p,
                format_size_fn=lambda n: str(n),
                is_filesystem_root_fn=lambda p: False,
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
                is_mac=False,
                mac_permission_help_fn=lambda p, err: "",
                trace_dependencies=lambda *args, **kwargs: (
                    [Path(context.blend_path)],
                    set(),
                    {},
                    [],
                    set(),
                ),
                compute_project_root=lambda *args, **kwargs: (
                    Path(td),
                    [Path(context.blend_path)],
                    [],
                ),
                classify_out_of_root_ok_files=lambda *args, **kwargs: [],
                apply_project_validation=lambda **kwargs: None,
                validate_project_upload=lambda **kwargs: None,
                meta_project_validation_version="v1",
                meta_project_validation_stats="stats",
                default_project_validation_version="1.0",
                prompt_continue_with_reports=lambda **kwargs: True,
                open_folder_fn=lambda *args, **kwargs: None,
                pack_blend=lambda *args, **kwargs: ({}, None),
                norm_abs_for_detection_fn=lambda p: p,
                build_project_manifest_from_map=lambda **kwargs: None,
                samepath_fn=lambda a, b: a == b,
                relpath_safe_fn=lambda p, b: p,
                clean_key_fn=lambda k: k,
                normalize_nfc_fn=lambda s: s,
                apply_manifest_validation=lambda **kwargs: ([], True),
                validate_manifest_entries=lambda *args, **kwargs: None,
                write_manifest_file=lambda *args, **kwargs: None,
                validate_manifest_writeback=lambda **kwargs: None,
                meta_manifest_entry_count="c",
                meta_manifest_source_match_count="m",
                meta_manifest_validation_stats="s",
                generate_test_report=lambda **kwargs: ({}, Path(td) / "report.json"),
                safe_input_fn=lambda *args, **kwargs: None,
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(0, result.flow.exit_code)
            self.assertEqual("zip_test_report", result.flow.reason)
            self.assertIsNone(result.fatal_error)


if __name__ == "__main__":
    unittest.main()
