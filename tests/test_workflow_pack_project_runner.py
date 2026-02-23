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

workflow_pack_project_runner = importlib.import_module(
    "transfers.submit.workflow_pack_project_runner"
)
workflow_types = importlib.import_module("transfers.submit.workflow_types")


class _Logger:
    def stage_header(self, *args, **kwargs):
        return None

    def pack_start(self, *args, **kwargs):
        return None

    def pack_end(self, *args, **kwargs):
        return None


class _Report:
    def start_stage(self, *args, **kwargs):
        return None

    def set_pack_dependency_size(self, *args, **kwargs):
        return None

    def complete_stage(self, *args, **kwargs):
        return None


def _trace_result(root: Path) -> workflow_types.TraceProjectResult:
    return workflow_types.TraceProjectResult(
        dep_paths=[],
        missing_set=set(),
        unreadable_dict={},
        raw_usages=[],
        optional_set=set(),
        project_root=root,
        project_root_str=str(root).replace("\\", "/"),
        same_drive_deps=[],
        cross_drive_deps=[],
        absolute_path_deps=[],
        out_of_root_ok_files=[],
        ok_files_set=set(),
        ok_files_cache=set(),
    )


class TestWorkflowPackProjectRunner(unittest.TestCase):
    def test_manifest_validation_cancelled_returns_exit_flow(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blend = root / "scene.blend"
            blend.write_bytes(b"blend")

            context = workflow_types.SubmitRunContext(
                data={"addon_dir": td},
                project={"id": "proj1"},
                blend_path=str(blend),
                use_project=True,
                automatic_project_path=True,
                custom_project_path_str="",
                job_id="job1",
                project_name="Proj",
                project_sqid="proj",
                org_id="org",
                test_mode=False,
                no_submit=False,
                zip_file=root / "job1.zip",
                filelist=root / "job1.txt",
            )

            result = workflow_pack_project_runner.run_pack_project_stage(
                context=context,
                trace_result=_trace_result(root),
                logger=_Logger(),
                report=_Report(),
                pack_blend=lambda *args, **kwargs: ({}, None),
                norm_abs_for_detection_fn=lambda p: p,
                build_project_manifest_from_map=lambda **kwargs: workflow_types.ManifestBuildResult(
                    rel_manifest=[],
                    manifest_source_map={},
                    dependency_total_size=0,
                    ok_count=0,
                ),
                samepath_fn=lambda a, b: a == b,
                relpath_safe_fn=lambda p, b: p,
                clean_key_fn=lambda k: k,
                normalize_nfc_fn=lambda s: s,
                apply_manifest_validation=lambda **kwargs: ([], False),
                validate_manifest_entries=lambda *args, **kwargs: None,
                write_manifest_file=lambda *args, **kwargs: None,
                validate_manifest_writeback=lambda **kwargs: None,
                prompt_continue_with_reports=lambda **kwargs: True,
                open_folder_fn=lambda *args, **kwargs: None,
                meta_manifest_entry_count="count",
                meta_manifest_source_match_count="match",
                meta_manifest_validation_stats="stats",
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
            )

            self.assertTrue(result.flow.should_exit)
            self.assertEqual(1, result.flow.exit_code)
            self.assertEqual("manifest_validation_cancelled", result.flow.reason)

    def test_pack_project_returns_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blend = root / "scene.blend"
            blend.write_bytes(b"blend")

            context = workflow_types.SubmitRunContext(
                data={"addon_dir": td},
                project={"id": "proj1"},
                blend_path=str(blend),
                use_project=True,
                automatic_project_path=True,
                custom_project_path_str="",
                job_id="job1",
                project_name="Proj",
                project_sqid="proj",
                org_id="org",
                test_mode=False,
                no_submit=False,
                zip_file=root / "job1.zip",
                filelist=root / "job1.txt",
            )

            dep_size = 10
            result = workflow_pack_project_runner.run_pack_project_stage(
                context=context,
                trace_result=_trace_result(root),
                logger=_Logger(),
                report=_Report(),
                pack_blend=lambda *args, **kwargs: ({}, None),
                norm_abs_for_detection_fn=lambda p: p,
                build_project_manifest_from_map=lambda **kwargs: workflow_types.ManifestBuildResult(
                    rel_manifest=["textures/a.jpg"],
                    manifest_source_map={"textures/a.jpg": str(root / "textures/a.jpg")},
                    dependency_total_size=dep_size,
                    ok_count=1,
                ),
                samepath_fn=lambda a, b: a == b,
                relpath_safe_fn=lambda p, b: Path(p).name,
                clean_key_fn=lambda k: k,
                normalize_nfc_fn=lambda s: s,
                apply_manifest_validation=lambda **kwargs: (["textures/a.jpg"], True),
                validate_manifest_entries=lambda *args, **kwargs: None,
                write_manifest_file=lambda p, lines: p.write_text(
                    "".join(f"{line}\n" for line in lines), encoding="utf-8"
                ),
                validate_manifest_writeback=lambda **kwargs: None,
                prompt_continue_with_reports=lambda **kwargs: True,
                open_folder_fn=lambda *args, **kwargs: None,
                meta_manifest_entry_count="count",
                meta_manifest_source_match_count="match",
                meta_manifest_validation_stats="stats",
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
            )

            self.assertFalse(result.flow.should_exit)
            self.assertIsNone(result.fatal_error)
            self.assertIsNotNone(result.artifacts)
            assert result.artifacts is not None
            self.assertEqual("scene.blend", result.artifacts.main_blend_s3)
            self.assertEqual(dep_size + blend.stat().st_size, result.artifacts.required_storage)


if __name__ == "__main__":
    unittest.main()
