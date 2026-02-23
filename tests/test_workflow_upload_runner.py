from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_upload_runner = importlib.import_module("transfers.submit.workflow_upload_runner")


class _Session:
    def get(self, *args, **kwargs):
        raise RuntimeError("network down")


class _Logger:
    def stage_header(self, *args, **kwargs):
        return None

    def fatal(self, msg):
        raise RuntimeError(str(msg))


class _Report:
    def start_stage(self, name):
        self.stage = name

    def set_status(self, status):
        self.status = status


class TestWorkflowUploadRunner(unittest.TestCase):
    def test_missing_storage_credentials_returns_fatal_error(self):
        report = _Report()
        context = workflow_upload_runner.SubmitRunContext(
            data={"pocketbase_url": "https://pb", "project": {"id": "p"}},
            project={"id": "p"},
            blend_path="/tmp/scene.blend",
            use_project=False,
            automatic_project_path=True,
            custom_project_path_str="",
            job_id="job1",
            project_name="proj",
            project_sqid="proj-sqid",
            org_id="org1",
            test_mode=False,
            no_submit=False,
            zip_file=Path("/tmp/job.zip"),
            filelist=Path("/tmp/job.txt"),
        )
        artifacts = workflow_upload_runner.StageArtifacts(
            project_root_str="",
            common_path="",
            rel_manifest=[],
            main_blend_s3="",
            required_storage=0,
            dependency_total_size=0,
        )
        result = workflow_upload_runner.run_upload_stage(
            context=context,
            artifacts=artifacts,
            session=_Session(),
            headers={"Authorization": "tok"},
            logger=_Logger(),
            report=report,
            rclone_bin="rclone",
            deps=workflow_upload_runner.UploadDeps(
                build_base_fn=lambda *args, **kwargs: ["rclone"],
                cloudflare_r2_domain="example.com",
                run_rclone=lambda *args, **kwargs: None,
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
                format_size_fn=lambda n: str(n),
                rclone_bytes_fn=lambda x: 0,
                rclone_stats_fn=lambda x: None,
                is_empty_upload_fn=lambda result, expected: False,
                get_rclone_tail_fn=lambda result: [],
                log_upload_result_fn=lambda *args, **kwargs: None,
                check_rclone_errors_fn=lambda *args, **kwargs: None,
                is_filesystem_root_fn=lambda p: False,
                split_manifest_by_first_dir=lambda rel: {},
                record_manifest_touch_mismatch=lambda **kwargs: None,
                upload_touched_lt_manifest="UPLOAD_TOUCHED_LT_MANIFEST",
                clean_key_fn=lambda k: k,
                normalize_nfc_fn=lambda s: s,
            ),
        )

        self.assertIsNotNone(result.fatal_error)
        self.assertEqual("failed", getattr(report, "status", None))


if __name__ == "__main__":
    unittest.main()
