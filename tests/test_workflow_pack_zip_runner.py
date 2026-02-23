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

workflow_pack_zip_runner = importlib.import_module(
    "transfers.submit.workflow_pack_zip_runner"
)
workflow_types = importlib.import_module("transfers.submit.workflow_types")


class _Logger:
    def stage_header(self, *args, **kwargs):
        return None

    def zip_start(self, *args, **kwargs):
        return None

    def zip_entry(self, *args, **kwargs):
        return None

    def zip_done(self, *args, **kwargs):
        return None


class _Report:
    def start_stage(self, *args, **kwargs):
        return None

    def add_pack_entry(self, *args, **kwargs):
        return None

    def set_pack_dependency_size(self, *args, **kwargs):
        return None

    def complete_stage(self, *args, **kwargs):
        return None

    def set_status(self, status):
        self.status = status


def _context(td: str) -> workflow_types.SubmitRunContext:
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
        project_sqid="proj",
        org_id="org",
        test_mode=False,
        no_submit=False,
        zip_file=Path(td) / "job1.zip",
        filelist=Path(td) / "job1.txt",
    )


def _trace_result(root: Path) -> workflow_types.TraceZipResult:
    return workflow_types.TraceZipResult(
        dep_paths=[],
        missing_set=set(),
        unreadable_dict={},
        raw_usages=[],
        optional_set=set(),
        project_root=root,
        project_root_str=str(root).replace("\\", "/"),
        same_drive_deps=[],
        cross_drive_deps=[],
    )


class TestWorkflowPackZipRunner(unittest.TestCase):
    def test_missing_zip_returns_fatal_error(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td)
            report = _Report()

            result = workflow_pack_zip_runner.run_pack_zip_stage(
                context=context,
                trace_result=_trace_result(Path(td)),
                logger=_Logger(),
                report=report,
                deps=workflow_types.PackZipDeps(
                    pack_blend=lambda *args, **kwargs: ({}, None),
                    norm_abs_for_detection_fn=lambda p: p,
                ),
            )

            self.assertIsNotNone(result.fatal_error)
            self.assertEqual("failed", getattr(report, "status", None))

    def test_pack_zip_returns_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td)
            context.zip_file.write_bytes(b"zipdata")

            def _pack_blend(*args, **kwargs):
                kwargs["zip_entry_cb"](1, 1, "scene.blend", 7, "ZIP")
                kwargs["zip_done_cb"](str(context.zip_file), 1, 7, 0.1)
                return {}

            result = workflow_pack_zip_runner.run_pack_zip_stage(
                context=context,
                trace_result=_trace_result(Path(td)),
                logger=_Logger(),
                report=_Report(),
                deps=workflow_types.PackZipDeps(
                    pack_blend=_pack_blend,
                    norm_abs_for_detection_fn=lambda p: p,
                ),
            )

            self.assertIsNone(result.fatal_error)
            self.assertIsNotNone(result.artifacts)
            assert result.artifacts is not None
            self.assertEqual(context.zip_file.stat().st_size, result.artifacts.required_storage)
            self.assertEqual(7, result.artifacts.dependency_total_size)


if __name__ == "__main__":
    unittest.main()
