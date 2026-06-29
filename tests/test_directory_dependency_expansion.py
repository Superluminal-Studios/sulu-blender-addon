from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
_pkg_name = _addon_dir.name.replace("-", "_")

if str(_addon_dir.parent) not in sys.path:
    sys.path.insert(0, str(_addon_dir.parent))

pkg = sys.modules.get(_pkg_name)
if pkg is None:
    pkg = types.ModuleType(_pkg_name)
    pkg.__path__ = [str(_addon_dir)]
    sys.modules[_pkg_name] = pkg

bat_utils = importlib.import_module(f"{_pkg_name}.utils.bat_utils")
cloud_files = importlib.import_module(f"{_pkg_name}.utils.cloud_files")
diagnostic_report = importlib.import_module(f"{_pkg_name}.utils.diagnostic_report")


class _DirectoryUsage:
    is_optional = False
    asset_path = "//cache"

    def __init__(self, path: Path):
        self.abspath = path

    def files(self):
        return [self.abspath]


class TestDirectoryDependencyExpansion(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self._orig_trace_deps = bat_utils.trace.deps

    def tearDown(self):
        bat_utils.trace.deps = self._orig_trace_deps
        self._tmpdir.cleanup()

    def test_trace_dependencies_expands_directory_usages(self):
        cache_dir = self.tmp_path / "cache"
        nested_dir = cache_dir / "nested"
        nested_dir.mkdir(parents=True)
        file_a = cache_dir / "sim_0001.bphys"
        file_b = nested_dir / "sim_0002.bphys"
        file_a.write_bytes(b"a")
        file_b.write_bytes(b"b")

        bat_utils.trace.deps = lambda _blend_path: [_DirectoryUsage(cache_dir)]

        dep_paths, missing, unreadable, _raw_usages, optional = (
            bat_utils.trace_dependencies(
                self.tmp_path / "scene.blend",
                hydrate=False,
            )
        )

        self.assertEqual(dep_paths, sorted([file_b, file_a], key=lambda p: str(p)))
        self.assertNotIn(cache_dir, dep_paths)
        self.assertEqual(missing, set())
        self.assertEqual(unreadable, {})
        self.assertEqual(optional, set())

    def test_trace_dependencies_marks_empty_directory_unreadable(self):
        cache_dir = self.tmp_path / "empty-cache"
        cache_dir.mkdir()

        bat_utils.trace.deps = lambda _blend_path: [_DirectoryUsage(cache_dir)]

        dep_paths, missing, unreadable, _raw_usages, optional = (
            bat_utils.trace_dependencies(
                self.tmp_path / "scene.blend",
                hydrate=False,
            )
        )

        self.assertEqual(dep_paths, [cache_dir])
        self.assertEqual(missing, set())
        self.assertEqual(unreadable, {cache_dir: "Directory contains no files"})
        self.assertEqual(optional, set())

    def test_empty_directory_is_written_to_diagnostics(self):
        cache_dir = self.tmp_path / "empty-cache"
        cache_dir.mkdir()
        report = diagnostic_report.DiagnosticReport(
            reports_dir=self.tmp_path / "reports",
            job_id="empty-dir-test",
            blend_name="scene",
        )

        bat_utils.trace.deps = lambda _blend_path: [_DirectoryUsage(cache_dir)]

        report.start_stage("trace")
        bat_utils.trace_dependencies(
            self.tmp_path / "scene.blend",
            hydrate=False,
            diagnostic_report=report,
        )
        report.complete_stage("trace")

        empty_dirs = report._data["issues"]["empty_directory_dependencies"]
        self.assertEqual(len(empty_dirs), 1)
        self.assertEqual(empty_dirs[0]["path"], str(cache_dir))
        self.assertEqual(
            empty_dirs[0]["error_message"],
            "Directory contains no files",
        )

    def test_cloud_file_probe_rejects_directories(self):
        cache_dir = self.tmp_path / "cache"
        cache_dir.mkdir()

        ok, err = cloud_files.read_file_with_hydration(
            str(cache_dir),
            hydrate=False,
        )

        self.assertFalse(ok)
        self.assertEqual(err, "is a directory")


if __name__ == "__main__":
    unittest.main()
