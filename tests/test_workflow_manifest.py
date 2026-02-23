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


workflow_manifest = importlib.import_module("transfers.submit.workflow_manifest")


class _DummyLogger:
    def __init__(self):
        self.entries = []
        self.warnings = []

    def pack_entry(self, idx, src, size=0, status="ok"):
        self.entries.append((idx, src, size, status))

    def warning(self, msg):
        self.warnings.append(str(msg))


class _DummyReport:
    def __init__(self):
        self.pack = []
        self.meta = {}
        self.codes = []

    def add_pack_entry(self, src_path, dest_key, file_size=0, status="ok"):
        self.pack.append((src_path, dest_key, file_size, status))

    def set_metadata(self, key, value):
        self.meta[key] = value

    def add_issue_code(self, code, action=None):
        self.codes.append((code, action))


class _ManifestValidation:
    def __init__(self, normalized, blocking=False):
        self.normalized_entries = list(normalized)
        self.has_blocking_risk = bool(blocking)
        self.warnings = ["warn"] if blocking else []
        self.issue_codes = ["MANIFEST_SOURCE_MISMATCH"] if blocking else []
        self.actions = {
            "MANIFEST_SOURCE_MISMATCH": "Fix source map",
        }
        self.stats = {
            "source_match_count": len(normalized),
        }


class TestWorkflowManifest(unittest.TestCase):
    def test_build_project_manifest_from_map_filters_and_maps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blend = root / "scene.blend"
            tex = root / "textures" / "albedo.jpg"
            blend.parent.mkdir(parents=True, exist_ok=True)
            tex.parent.mkdir(parents=True, exist_ok=True)
            blend.write_bytes(b"blend")
            tex.write_bytes(b"img")

            fmap = {
                str(blend): "scene.blend",
                str(tex): "textures/albedo.jpg",
            }

            logger = _DummyLogger()
            report = _DummyReport()

            result = workflow_manifest.build_project_manifest_from_map(
                fmap=fmap,
                abs_blend=str(blend),
                common_path=str(root),
                ok_files_cache={str(tex).replace("\\", "/")},
                logger=logger,
                report=report,
                samepath_fn=lambda a, b: os.path.normpath(a) == os.path.normpath(b),
                relpath_safe_fn=lambda c, b: os.path.relpath(c, b).replace("\\", "/"),
                clean_key_fn=lambda k: k.replace("\\", "/"),
            )

            self.assertEqual(["textures/albedo.jpg"], result.rel_manifest)
            self.assertEqual(str(tex).replace("\\", "/"), result.manifest_source_map["textures/albedo.jpg"])
            self.assertEqual(1, result.ok_count)
            self.assertGreaterEqual(result.dependency_total_size, 1)
            self.assertEqual(1, len(logger.entries))
            self.assertEqual(1, len(report.pack))

    def test_apply_manifest_validation_sets_metadata_and_allows_continue(self):
        logger = _DummyLogger()
        report = _DummyReport()

        def _validate(entries, **kwargs):
            return _ManifestValidation(entries, blocking=False)

        normalized, keep_going = workflow_manifest.apply_manifest_validation(
            rel_manifest=["a.jpg"],
            common_path="/tmp/project",
            manifest_source_map={"a.jpg": "/tmp/project/a.jpg"},
            validate_manifest_entries=_validate,
            logger=logger,
            report=report,
            prompt_continue_with_reports=lambda **kwargs: False,
            open_folder_fn=lambda *args, **kwargs: None,
            clean_key_fn=lambda x: x,
            metadata_manifest_entry_count="manifest_entry_count",
            metadata_manifest_source_match_count="manifest_source_match_count",
            metadata_manifest_validation_stats="manifest_validation_stats",
        )

        self.assertEqual(["a.jpg"], normalized)
        self.assertTrue(keep_going)
        self.assertEqual(1, report.meta["manifest_entry_count"])
        self.assertEqual(1, report.meta["manifest_source_match_count"])
        self.assertIn("manifest_validation_stats", report.meta)


if __name__ == "__main__":
    unittest.main()
