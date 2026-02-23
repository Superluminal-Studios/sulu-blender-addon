from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


diag = importlib.import_module("utils.diagnostic_schema")


class TestDiagnosticSchema(unittest.TestCase):
    def test_issue_codes_are_unique(self):
        self.assertEqual(len(diag.ALL_ISSUE_CODES), len(set(diag.ALL_ISSUE_CODES)))

    def test_metadata_keys_are_unique(self):
        self.assertEqual(len(diag.ALL_METADATA_KEYS), len(set(diag.ALL_METADATA_KEYS)))

    def test_expected_core_codes_present(self):
        expected = {
            "PROJECT_ABSOLUTE_PATH_REFERENCE",
            "PROJECT_OUT_OF_ROOT_EXCLUDED",
            "MANIFEST_SOURCE_MISMATCH",
            "UPLOAD_TOUCHED_LT_MANIFEST",
        }
        self.assertTrue(expected.issubset(set(diag.ALL_ISSUE_CODES)))


if __name__ == "__main__":
    unittest.main()
