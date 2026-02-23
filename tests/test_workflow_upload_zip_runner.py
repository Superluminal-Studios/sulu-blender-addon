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

workflow_upload_zip_runner = importlib.import_module(
    "transfers.submit.workflow_upload_zip_runner"
)


class _Logger:
    def __init__(self):
        self._transfer_total = 0
        self.steps = []

    def upload_start(self, total_steps):
        self.total_steps = total_steps

    def upload_step(self, step, total_steps, label):
        self.steps.append((step, total_steps, label))

    def upload_complete(self, label):
        self.steps.append(("done", label))


class _Report:
    def __init__(self):
        self.upload_steps = []

    def start_upload_step(self, *args, **kwargs):
        self.upload_steps.append(("start", args, kwargs))

    def complete_upload_step(self, *args, **kwargs):
        self.upload_steps.append(("complete", args, kwargs))


def _context(td: str, *, with_addons: bool):
    data = {"packed_addons": []}
    if with_addons:
        addons_path = Path(td) / "addons"
        addons_path.mkdir(parents=True, exist_ok=True)
        data["packed_addons"] = ["a"]
        data["packed_addons_path"] = str(addons_path)
    return workflow_upload_zip_runner.SubmitRunContext(
        data=data,
        project={"id": "p"},
        blend_path=str(Path(td) / "scene.blend"),
        use_project=False,
        automatic_project_path=True,
        custom_project_path_str="",
        job_id="job1",
        project_name="proj",
        project_sqid="proj-sqid",
        org_id="org1",
        test_mode=False,
        no_submit=False,
        zip_file=Path(td) / "job.zip",
        filelist=Path(td) / "manifest.txt",
    )


def _artifacts(required_storage: int = 0):
    return workflow_upload_zip_runner.StageArtifacts(
        project_root_str="",
        common_path="",
        rel_manifest=[],
        main_blend_s3="",
        required_storage=required_storage,
        dependency_total_size=0,
    )


class TestWorkflowUploadZipRunner(unittest.TestCase):
    def test_zip_upload_moves_archive_and_addons(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td, with_addons=True)
            context.zip_file.write_bytes(b"zipdata")
            artifacts = _artifacts(required_storage=context.zip_file.stat().st_size)

            calls = []

            def _run_rclone(*args, **kwargs):
                calls.append((args[1], args[2], args[3], kwargs.get("total_bytes", 0)))
                return {"bytes_transferred": 1, "checks": 1, "transfers": 1, "errors": 0}

            deps = workflow_upload_zip_runner.UploadDeps(
                build_base_fn=lambda *args, **kwargs: ["rclone"],
                cloudflare_r2_domain="example.com",
                run_rclone=_run_rclone,
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
                format_size_fn=lambda n: str(n),
                upload_touched_lt_manifest="UPLOAD_TOUCHED_LT_MANIFEST",
                clean_key_fn=lambda k: k,
                normalize_nfc_fn=lambda s: s,
            )

            logger = _Logger()
            result = workflow_upload_zip_runner.run_upload_zip_stage(
                context=context,
                artifacts=artifacts,
                logger=logger,
                report=_Report(),
                bucket="render-bucket",
                base_cmd=["rclone"],
                rclone_settings=["--stats", "0.1s"],
                deps=deps,
            )

            self.assertIsNone(result.fatal_error)
            self.assertEqual(2, len(calls))
            self.assertEqual("move", calls[0][0])
            self.assertEqual(str(context.zip_file), calls[0][1])
            self.assertEqual(":s3:render-bucket/", calls[0][2])
            self.assertEqual(artifacts.required_storage, calls[0][3])
            self.assertEqual("moveto", calls[1][0])
            self.assertEqual(":s3:render-bucket/job1/addons/", calls[1][2])
            self.assertEqual(artifacts.required_storage, logger._transfer_total)

    def test_zip_upload_without_addons_runs_single_step(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td, with_addons=False)
            context.zip_file.write_bytes(b"zipdata")
            artifacts = _artifacts(required_storage=context.zip_file.stat().st_size)

            calls = []

            def _run_rclone(*args, **kwargs):
                calls.append((args[1], args[2], args[3]))
                return {"bytes_transferred": 1, "checks": 1, "transfers": 1, "errors": 0}

            deps = workflow_upload_zip_runner.UploadDeps(
                build_base_fn=lambda *args, **kwargs: ["rclone"],
                cloudflare_r2_domain="example.com",
                run_rclone=_run_rclone,
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
                format_size_fn=lambda n: str(n),
                upload_touched_lt_manifest="UPLOAD_TOUCHED_LT_MANIFEST",
                clean_key_fn=lambda k: k,
                normalize_nfc_fn=lambda s: s,
            )

            result = workflow_upload_zip_runner.run_upload_zip_stage(
                context=context,
                artifacts=artifacts,
                logger=_Logger(),
                report=_Report(),
                bucket="render-bucket",
                base_cmd=["rclone"],
                rclone_settings=["--stats", "0.1s"],
                deps=deps,
            )

            self.assertIsNone(result.fatal_error)
            self.assertEqual(1, len(calls))
            self.assertEqual("move", calls[0][0])


if __name__ == "__main__":
    unittest.main()
