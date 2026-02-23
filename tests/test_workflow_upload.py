from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


workflow_upload = importlib.import_module("transfers.submit.workflow_upload")


class _DummyLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(str(msg))


class _DummyReport:
    def __init__(self):
        self.codes = []

    def add_issue_code(self, code, action=None):
        self.codes.append((code, action))


class TestWorkflowUpload(unittest.TestCase):
    def test_split_manifest_by_first_dir(self):
        groups = workflow_upload.split_manifest_by_first_dir(
            ["tex/a.jpg", "tex/b.jpg", "root.exr"]
        )
        self.assertEqual(["a.jpg", "b.jpg"], groups["tex"])
        self.assertEqual(["root.exr"], groups[""])

    def test_split_manifest_by_first_dir_mixed_roots(self):
        groups = workflow_upload.split_manifest_by_first_dir(
            [
                "Users/jonas/Dropbox/3. Resources/3D/Megascans/Downloaded/3d/a/albedo.jpg",
                "Users/jonas/Dropbox/3. Resources/3D/Megascans/Downloaded/3d/a/normal.jpg",
                "Application Support/Blender Studio Tools/styles/maps/oil_paint.exr",
                "scene.blend",
            ]
        )
        self.assertEqual(
            [
                "jonas/Dropbox/3. Resources/3D/Megascans/Downloaded/3d/a/albedo.jpg",
                "jonas/Dropbox/3. Resources/3D/Megascans/Downloaded/3d/a/normal.jpg",
            ],
            groups["Users"],
        )
        self.assertEqual(
            ["Blender Studio Tools/styles/maps/oil_paint.exr"],
            groups["Application Support"],
        )
        self.assertEqual(["scene.blend"], groups[""])

    def test_record_manifest_touch_mismatch_adds_issue(self):
        logger = _DummyLogger()
        report = _DummyReport()

        workflow_upload.record_manifest_touch_mismatch(
            logger=logger,
            report=report,
            total_touched=2,
            manifest_count=5,
            issue_code="UPLOAD_TOUCHED_LT_MANIFEST",
            issue_action="retry",
            debug_enabled_fn=lambda: False,
            log_fn=lambda msg: None,
        )

        self.assertEqual(1, len(logger.warnings))
        self.assertIn("UPLOAD_TOUCHED_LT_MANIFEST", [c for c, _ in report.codes])


if __name__ == "__main__":
    unittest.main()
