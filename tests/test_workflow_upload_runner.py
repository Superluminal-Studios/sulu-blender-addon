from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_upload_runner = importlib.import_module("transfers.submit.workflow_upload_runner")


class _SessionError:
    def get(self, *args, **kwargs):
        raise RuntimeError("network down")


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"items": [{"bucket_name": "render-test"}]}


class _SessionOk:
    def get(self, *args, **kwargs):
        return _Response()


class _Logger:
    def stage_header(self, *args, **kwargs):
        return None


class _Report:
    def __init__(self):
        self.status = None
        self.stages = []
        self.completed = []

    def start_stage(self, name):
        self.stages.append(name)

    def complete_stage(self, name):
        self.completed.append(name)

    def set_status(self, status):
        self.status = status


def _context(td: str, *, use_project: bool, packed_addons_path: str | None = None):
    data = {
        "pocketbase_url": "https://pb",
        "project": {"id": "p"},
        "packed_addons": [],
    }
    if packed_addons_path is not None:
        data["packed_addons_path"] = packed_addons_path
        data["packed_addons"] = ["a"]
    return workflow_upload_runner.SubmitRunContext(
        data=data,
        project={"id": "p"},
        blend_path=str(Path(td) / "scene.blend"),
        use_project=use_project,
        automatic_project_path=True,
        custom_project_path_str="",
        job_id="job1",
        project_name="proj",
        project_sqid="proj-sqid",
        org_id="org1",
        test_mode=False,
        no_submit=False,
        zip_file=Path(td) / "job.zip",
        filelist=Path(td) / "job.txt",
    )


def _artifacts() -> workflow_upload_runner.StageArtifacts:
    return workflow_upload_runner.StageArtifacts(
        project_root_str="/tmp/proj",
        common_path="/tmp/proj",
        rel_manifest=[],
        main_blend_s3="scene.blend",
        required_storage=0,
        dependency_total_size=0,
    )


def _deps() -> workflow_upload_runner.UploadDeps:
    return workflow_upload_runner.UploadDeps(
        build_base_fn=lambda *args, **kwargs: ["rclone"],
        cloudflare_r2_domain="example.com",
        run_rclone=lambda *args, **kwargs: None,
        debug_enabled_fn=lambda: False,
        log_fn=lambda msg: None,
        format_size_fn=lambda n: str(n),
        upload_touched_lt_manifest="UPLOAD_TOUCHED_LT_MANIFEST",
        clean_key_fn=lambda k: k,
        normalize_nfc_fn=lambda s: s,
    )


class TestWorkflowUploadRunner(unittest.TestCase):
    def test_missing_storage_credentials_returns_fatal_error(self):
        report = _Report()
        result = workflow_upload_runner.run_upload_stage(
            context=_context("/tmp", use_project=False),
            artifacts=_artifacts(),
            session=_SessionError(),
            headers={"Authorization": "tok"},
            logger=_Logger(),
            report=report,
            rclone_bin="rclone",
            deps=_deps(),
        )

        self.assertIsNotNone(result.fatal_error)
        self.assertEqual("failed", report.status)

    def test_dispatches_project_mode(self):
        report = _Report()
        with tempfile.TemporaryDirectory() as td:
            context = _context(td, use_project=True)
            with patch.object(
                workflow_upload_runner,
                "run_upload_project_stage",
                return_value=workflow_upload_runner.UploadResult(),
            ) as project_stage, patch.object(
                workflow_upload_runner,
                "run_upload_zip_stage",
                return_value=workflow_upload_runner.UploadResult(),
            ) as zip_stage:
                result = workflow_upload_runner.run_upload_stage(
                    context=context,
                    artifacts=_artifacts(),
                    session=_SessionOk(),
                    headers={"Authorization": "tok"},
                    logger=_Logger(),
                    report=report,
                    rclone_bin="rclone",
                    deps=_deps(),
                )

        self.assertIsNone(result.fatal_error)
        self.assertEqual(1, project_stage.call_count)
        self.assertEqual(0, zip_stage.call_count)
        self.assertIn("upload", report.completed)

    def test_dispatches_zip_mode(self):
        report = _Report()
        with tempfile.TemporaryDirectory() as td:
            context = _context(td, use_project=False)
            with patch.object(
                workflow_upload_runner,
                "run_upload_project_stage",
                return_value=workflow_upload_runner.UploadResult(),
            ) as project_stage, patch.object(
                workflow_upload_runner,
                "run_upload_zip_stage",
                return_value=workflow_upload_runner.UploadResult(),
            ) as zip_stage:
                result = workflow_upload_runner.run_upload_stage(
                    context=context,
                    artifacts=_artifacts(),
                    session=_SessionOk(),
                    headers={"Authorization": "tok"},
                    logger=_Logger(),
                    report=report,
                    rclone_bin="rclone",
                    deps=_deps(),
                )

        self.assertIsNone(result.fatal_error)
        self.assertEqual(0, project_stage.call_count)
        self.assertEqual(1, zip_stage.call_count)
        self.assertIn("upload", report.completed)

    def test_cleanup_runs_for_packed_addons_path(self):
        report = _Report()
        with tempfile.TemporaryDirectory() as td:
            addons_path = Path(td) / "addons_tmp"
            addons_path.mkdir(parents=True, exist_ok=True)
            (addons_path / "a.txt").write_text("x", encoding="utf-8")
            context = _context(td, use_project=False, packed_addons_path=str(addons_path))
            with patch.object(
                workflow_upload_runner,
                "run_upload_zip_stage",
                return_value=workflow_upload_runner.UploadResult(),
            ):
                result = workflow_upload_runner.run_upload_stage(
                    context=context,
                    artifacts=_artifacts(),
                    session=_SessionOk(),
                    headers={"Authorization": "tok"},
                    logger=_Logger(),
                    report=report,
                    rclone_bin="rclone",
                    deps=_deps(),
                )

            self.assertIsNone(result.fatal_error)
            self.assertFalse(addons_path.exists())


if __name__ == "__main__":
    unittest.main()
