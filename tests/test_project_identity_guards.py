from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


def _load_module_directly(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_submit_worker = _load_module_directly(
    "submit_worker_project_guard",
    _addon_dir / "transfers" / "submit" / "submit_worker.py",
)


class TestProjectIdentityGuards(unittest.TestCase):
    def test_missing_fields_when_project_is_none(self):
        missing = _submit_worker._missing_project_identity_fields(None)
        self.assertEqual(missing, ["id", "organization_id", "sqid"])

    def test_missing_fields_detects_blank_values(self):
        missing = _submit_worker._missing_project_identity_fields(
            {"id": "proj_1", "organization_id": "", "sqid": "   "}
        )
        self.assertEqual(missing, ["organization_id", "sqid"])

    def test_missing_fields_returns_empty_when_identity_complete(self):
        missing = _submit_worker._missing_project_identity_fields(
            {"id": "proj_1", "organization_id": "org_1", "sqid": "sqid_1"}
        )
        self.assertEqual(missing, [])

    def test_parse_project_storage_payload_rejects_empty_items(self):
        with self.assertRaises(RuntimeError):
            _submit_worker._parse_project_storage_payload({"items": []})

    def test_parse_project_storage_payload_rejects_missing_bucket(self):
        with self.assertRaises(RuntimeError):
            _submit_worker._parse_project_storage_payload({"items": [{}]})

    def test_parse_project_storage_payload_success(self):
        rec, bucket = _submit_worker._parse_project_storage_payload(
            {"items": [{"bucket_name": "render-abcd"}]}
        )
        self.assertEqual(bucket, "render-abcd")
        self.assertEqual(rec.get("bucket_name"), "render-abcd")


if __name__ == "__main__":
    unittest.main()
