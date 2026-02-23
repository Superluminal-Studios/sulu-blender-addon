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


workflow_trace = importlib.import_module("transfers.submit.workflow_trace")


class _DummyReport:
    def __init__(self):
        self.meta = {}
        self.codes = []

    def set_metadata(self, key, value):
        self.meta[key] = value

    def add_issue_code(self, code, action=None):
        self.codes.append((code, action))


class _ValidationResult:
    def __init__(self):
        self.issue_codes = ["PROJECT_OUT_OF_ROOT_EXCLUDED"]
        self.actions = {
            "PROJECT_OUT_OF_ROOT_EXCLUDED": "Broaden project root",
        }
        self.stats = {"out_of_root_count": 1}


class TestWorkflowTrace(unittest.TestCase):
    def test_apply_project_validation_records_metadata_and_codes(self):
        report = _DummyReport()

        def _validate_project_upload(**kwargs):
            return _ValidationResult()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workflow_trace.apply_project_validation(
                validate_project_upload=_validate_project_upload,
                blend_path=str(root / "scene.blend"),
                project_root=root,
                dep_paths=[],
                raw_usages=[],
                missing_set=set(),
                unreadable_dict={},
                optional_set=set(),
                cross_drive_deps=[],
                absolute_path_deps=[],
                out_of_root_ok_files=[],
                report=report,
                metadata_project_validation_version="project_validation_version",
                metadata_project_validation_stats="project_validation_stats",
                validation_version="1.0",
            )

        self.assertEqual("1.0", report.meta["project_validation_version"])
        self.assertEqual({"out_of_root_count": 1}, report.meta["project_validation_stats"])
        self.assertIn("PROJECT_OUT_OF_ROOT_EXCLUDED", [c for c, _ in report.codes])


if __name__ == "__main__":
    unittest.main()
