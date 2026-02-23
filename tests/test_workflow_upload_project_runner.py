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

workflow_upload_project_runner = importlib.import_module(
    "transfers.submit.workflow_upload_project_runner"
)


class _Logger:
    def __init__(self):
        self._transfer_total = 0
        self.steps = []
        self.warnings = []

    def upload_start(self, total_steps):
        self.total_steps = total_steps

    def upload_step(self, step, total_steps, label):
        self.steps.append((step, total_steps, label))

    def upload_complete(self, label):
        self.steps.append(("done", label))

    def warning(self, message):
        self.warnings.append(str(message))


class _Report:
    def __init__(self):
        self.upload_steps = []
        self.split_groups = []

    def start_upload_step(self, *args, **kwargs):
        self.upload_steps.append(("start", args, kwargs))

    def complete_upload_step(self, *args, **kwargs):
        self.upload_steps.append(("complete", args, kwargs))

    def add_upload_split_group(self, **kwargs):
        self.split_groups.append(kwargs)


def _context(td: str, *, packed_addons: bool = False):
    data = {"packed_addons": []}
    if packed_addons:
        addons_path = Path(td) / "addons"
        addons_path.mkdir(parents=True, exist_ok=True)
        data["packed_addons"] = ["a"]
        data["packed_addons_path"] = str(addons_path)
    return workflow_upload_project_runner.SubmitRunContext(
        data=data,
        project={"id": "p"},
        blend_path=str(Path(td) / "scene.blend"),
        use_project=True,
        automatic_project_path=True,
        custom_project_path_str="",
        job_id="job1",
        project_name="Proj",
        project_sqid="proj-sqid",
        org_id="org1",
        test_mode=False,
        no_submit=False,
        zip_file=Path(td) / "job.zip",
        filelist=Path(td) / "manifest.txt",
    )


def _artifacts(
    *,
    common_path: str,
    rel_manifest: list[str],
    main_blend_s3: str = "scene.blend",
    dependency_total_size: int = 0,
):
    return workflow_upload_project_runner.StageArtifacts(
        project_root_str=common_path,
        common_path=common_path,
        rel_manifest=rel_manifest,
        main_blend_s3=main_blend_s3,
        required_storage=dependency_total_size,
        dependency_total_size=dependency_total_size,
    )


class TestWorkflowUploadProjectRunner(unittest.TestCase):
    def test_filesystem_root_split_groups_uploads_all_groups(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td)
            blend_path = Path(context.blend_path)
            blend_path.write_bytes(b"blend")
            Path(context.filelist).write_text("", encoding="utf-8")
            artifacts = _artifacts(
                common_path="/Volumes/Drive",
                rel_manifest=[
                    "Users/artist/a.png",
                    "Projects/show/b.exr",
                    "root.txt",
                ],
                dependency_total_size=123,
            )

            calls = []

            def _run_rclone(*args, **kwargs):
                op = args[1]
                src = args[2]
                dst = args[3]
                calls.append((op, src, dst, kwargs.get("extra", [])))
                return {
                    "bytes_transferred": 10,
                    "checks": 1,
                    "transfers": 1,
                    "errors": 0,
                    "stats_received": True,
                }

            deps = workflow_upload_project_runner.UploadDeps(
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

            result = workflow_upload_project_runner.run_upload_project_stage(
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
            copy_ops = [c for c in calls if c[0] == "copy"]
            self.assertEqual(3, len(copy_ops))
            copy_dsts = [c[2] for c in copy_ops]
            self.assertIn(":s3:render-bucket/Proj/Users/", copy_dsts)
            self.assertIn(":s3:render-bucket/Proj/Projects/", copy_dsts)
            self.assertIn(":s3:render-bucket/Proj/", copy_dsts)

    def test_main_blend_key_is_cleaned_and_normalized(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td)
            blend_path = Path(context.blend_path)
            blend_path.write_bytes(b"blend")
            Path(context.filelist).write_text("", encoding="utf-8")
            artifacts = _artifacts(
                common_path=td,
                rel_manifest=[],
                main_blend_s3="/sce\u0065\u0301ne.blend",
            )

            calls = []

            def _run_rclone(*args, **kwargs):
                calls.append((args[1], args[2], args[3], kwargs.get("extra", [])))
                return {"bytes_transferred": 1, "checks": 1, "transfers": 1, "errors": 0}

            deps = workflow_upload_project_runner.UploadDeps(
                build_base_fn=lambda *args, **kwargs: ["rclone"],
                cloudflare_r2_domain="example.com",
                run_rclone=_run_rclone,
                debug_enabled_fn=lambda: False,
                log_fn=lambda msg: None,
                format_size_fn=lambda n: str(n),
                upload_touched_lt_manifest="UPLOAD_TOUCHED_LT_MANIFEST",
                clean_key_fn=lambda k: k.replace("//", "/").lstrip("/"),
                normalize_nfc_fn=lambda s: s.upper(),
            )

            workflow_upload_project_runner.run_upload_project_stage(
                context=context,
                artifacts=artifacts,
                logger=_Logger(),
                report=_Report(),
                bucket="render-bucket",
                base_cmd=["rclone"],
                rclone_settings=["--stats", "0.1s"],
                deps=deps,
            )

            first_call = calls[0]
            self.assertEqual("copyto", first_call[0])
            self.assertEqual(":s3:render-bucket/PROJ/SCEÉNE.BLEND", first_call[2])

    def test_manifest_touch_mismatch_records_issue_when_touched_lt_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            context = _context(td)
            blend_path = Path(context.blend_path)
            blend_path.write_bytes(b"blend")
            Path(context.filelist).write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
            artifacts = _artifacts(
                common_path=td,
                rel_manifest=["a", "b", "c", "d", "e"],
                dependency_total_size=100,
            )

            mismatch_calls = []

            def _run_rclone(*args, **kwargs):
                op = args[1]
                if op == "copy":
                    return {
                        "bytes_transferred": 10,
                        "checks": 1,
                        "transfers": 1,
                        "errors": 0,
                        "stats_received": True,
                    }
                return {"bytes_transferred": 1, "checks": 1, "transfers": 1, "errors": 0}

            deps = workflow_upload_project_runner.UploadDeps(
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

            with patch.object(
                workflow_upload_project_runner,
                "record_manifest_touch_mismatch",
                side_effect=lambda **kwargs: mismatch_calls.append(kwargs),
            ):
                workflow_upload_project_runner.run_upload_project_stage(
                    context=context,
                    artifacts=artifacts,
                    logger=_Logger(),
                    report=_Report(),
                    bucket="render-bucket",
                    base_cmd=["rclone"],
                    rclone_settings=["--stats", "0.1s"],
                    deps=deps,
                )

            self.assertEqual(1, len(mismatch_calls))
            self.assertEqual(2, mismatch_calls[0]["total_touched"])
            self.assertEqual(5, mismatch_calls[0]["manifest_count"])


if __name__ == "__main__":
    unittest.main()
