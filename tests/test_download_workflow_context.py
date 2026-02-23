from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_context = importlib.import_module("transfers.download.workflow_context")


class TestDownloadWorkflowContext(unittest.TestCase):
    def test_build_context_defaults_single_mode_without_sarfis(self):
        with tempfile.TemporaryDirectory() as td:
            data = {
                "job_id": "job-1",
                "job_name": "",
                "download_path": td,
            }
            context = workflow_context.build_download_context(data)

            self.assertEqual("job-1", context.job_id)
            self.assertEqual("job_job-1", context.job_name)
            self.assertEqual(td, context.download_path)
            self.assertEqual("single", context.download_type)
            self.assertEqual(os.path.join(td, "job_job-1"), context.dest_dir)

    def test_build_context_honors_requested_mode(self):
        data = {
            "job_id": "abc",
            "job_name": "My Job",
            "download_path": "/tmp/out",
            "download_type": "auto",
        }
        context = workflow_context.build_download_context(data)
        self.assertEqual("auto", context.download_type)

    def test_build_context_auto_mode_inferred_when_sarfis_present(self):
        data = {
            "job_id": "abc",
            "job_name": "My Job",
            "download_path": "/tmp/out",
            "sarfis_url": "https://sarfis.example",
            "sarfis_token": "token",
            "download_type": "other",
        }
        context = workflow_context.build_download_context(data)
        self.assertEqual("auto", context.download_type)

    def test_safe_dir_name_sanitizes_illegal_path_chars(self):
        result = workflow_context.safe_dir_name('A:B/C*D?"E<F>G|', "fallback")
        self.assertEqual("A_B_C_D_E_F_G_", result)

    def test_count_existing_files_counts_recursively(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("a", encoding="utf-8")
            sub = root / "sub"
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "b.txt").write_text("b", encoding="utf-8")
            self.assertEqual(2, workflow_context.count_existing_files(td))

    def test_resolve_download_path_blender_relative_uses_base_dir(self):
        resolved = workflow_context.resolve_download_path("//downloads", "/work/project")
        self.assertEqual(os.path.abspath("/work/project/downloads"), resolved)

    def test_resolve_download_path_plain_relative_uses_base_dir(self):
        resolved = workflow_context.resolve_download_path("downloads/frames", "/work/project")
        self.assertEqual(os.path.abspath("/work/project/downloads/frames"), resolved)

    def test_resolve_download_path_empty_defaults_to_base_dir(self):
        resolved = workflow_context.resolve_download_path("", "/work/project")
        self.assertEqual(os.path.abspath("/work/project"), resolved)

    def test_build_context_uses_download_base_dir_for_relative_path(self):
        data = {
            "job_id": "abc",
            "job_name": "My Job",
            "download_path": "//downloads",
            "download_base_dir": "/work/project",
        }
        context = workflow_context.build_download_context(data)
        self.assertEqual(os.path.abspath("/work/project/downloads"), context.download_path)
        self.assertEqual(
            os.path.abspath("/work/project/downloads/My Job"),
            context.dest_dir,
        )

    def test_build_context_legacy_relative_without_base_dir_uses_cwd(self):
        data = {
            "job_id": "legacy-job",
            "job_name": "Legacy",
            "download_path": "downloads",
        }
        with patch.object(workflow_context.os, "getcwd", return_value="/legacy/cwd"):
            context = workflow_context.build_download_context(data)
        self.assertEqual(os.path.abspath("/legacy/cwd/downloads"), context.download_path)
        self.assertEqual(
            os.path.abspath("/legacy/cwd/downloads/Legacy"),
            context.dest_dir,
        )


if __name__ == "__main__":
    unittest.main()
