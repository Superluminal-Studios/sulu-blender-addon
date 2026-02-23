from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


class TestProjectUploadValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = importlib.import_module("utils.project_upload_validator")

    def test_detects_blocking_project_path_risks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir(parents=True, exist_ok=True)
            inside = root / "textures" / "albedo.jpg"
            inside.parent.mkdir(parents=True, exist_ok=True)
            inside.write_bytes(b"ok")

            outside_dir = Path(td) / "outside"
            outside_dir.mkdir(parents=True, exist_ok=True)
            outside = outside_dir / "roughness.jpg"
            outside.write_bytes(b"ok")

            res = self.mod.validate_project_upload(
                blend_path=root / "scene.blend",
                project_root=root,
                dep_paths=[inside, outside],
                raw_usages=[],
                missing_set=set(),
                unreadable_dict={},
                optional_set=set(),
                cross_drive_files=[],
                absolute_path_files=[inside],
                out_of_root_files=[outside],
            )

            self.assertTrue(res.has_blocking_risk)
            self.assertIn("PROJECT_ABSOLUTE_PATH_REFERENCE", res.issue_codes)
            self.assertIn("PROJECT_OUT_OF_ROOT_EXCLUDED", res.issue_codes)
            self.assertIn("PROJECT_ROOT_ESCAPE", res.issue_codes)
            self.assertEqual(1, res.stats["absolute_path_count"])
            self.assertEqual(1, res.stats["out_of_root_count"])
            self.assertEqual(1, res.stats["root_escape_count"])

    def test_ignores_optional_and_missing_in_out_of_root_detection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir(parents=True, exist_ok=True)
            optional_outside = Path(td) / "outside" / "cloud_only.exr"

            res = self.mod.validate_project_upload(
                blend_path=root / "scene.blend",
                project_root=root,
                dep_paths=[optional_outside],
                raw_usages=[],
                missing_set=set(),
                unreadable_dict={},
                optional_set={optional_outside},
            )

            self.assertFalse(res.has_blocking_risk)
            self.assertEqual([], res.issue_codes)
            self.assertEqual(0, res.stats["out_of_root_count"])


class TestManifestValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = importlib.import_module("utils.project_upload_validator")

    @staticmethod
    def _clean_key(value: str) -> str:
        key = str(value).replace("\\", "/")
        key = os.path.normpath(key).replace("\\", "/")
        key = key.lstrip("/")
        if key == ".":
            return ""
        return key

    def test_manifest_normalization_and_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tex = root / "textures" / "a.jpg"
            tex.parent.mkdir(parents=True, exist_ok=True)
            tex.write_bytes(b"ok")

            res = self.mod.validate_manifest_entries(
                [
                    "textures/a.jpg",
                    "textures//a.jpg",
                    "./",
                    "../bad.jpg",
                    "textures/../textures/a.jpg",
                ],
                source_root=str(root),
                clean_key=self._clean_key,
            )

            self.assertEqual(["textures/a.jpg"], res.normalized_entries)
            self.assertEqual(2, res.stats["duplicate_entries_removed"])
            self.assertEqual(2, res.stats["invalid_entry_count"])
            self.assertEqual(0, res.stats["source_mismatch_count"])
            self.assertIn("MANIFEST_ENTRY_INVALID", res.issue_codes)

    def test_manifest_source_mismatch_sets_issue_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            res = self.mod.validate_manifest_entries(
                ["textures/missing.jpg"],
                source_root=str(root),
                clean_key=self._clean_key,
            )

            self.assertTrue(res.has_blocking_risk)
            self.assertEqual(["textures/missing.jpg"], res.source_mismatches)
            self.assertIn("MANIFEST_SOURCE_MISMATCH", res.issue_codes)
            self.assertEqual(1, res.stats["source_mismatch_count"])


if __name__ == "__main__":
    unittest.main()
