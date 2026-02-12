#!/usr/bin/env python3
"""
Tests for bulletproof upload logging.

Covers:
- DiagnosticReport.complete_upload_step() warning generation
- rclone_utils._redact_cmd() credential masking
- submit_worker._log_upload_result() terminal output
- submit_worker._is_filesystem_root() detection

Usage:
    python -m pytest tests/test_upload_logging.py -v
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


def _load_module_directly(name: str, filepath: Path):
    """Load a single .py file as a module, bypassing package __init__.py."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the modules we need directly, without triggering __init__.py (which
# imports bpy).  Only the modules themselves are needed for unit testing.
_diagnostic_report = _load_module_directly(
    "diagnostic_report", _addon_dir / "utils" / "diagnostic_report.py"
)
_rclone_utils = _load_module_directly(
    "rclone_utils", _addon_dir / "transfers" / "rclone_utils.py"
)
# submit_worker imports requests at module level, so load it carefully.
# We only need the free-standing helpers, not the full main().
_submit_worker = _load_module_directly(
    "submit_worker", _addon_dir / "transfers" / "submit" / "submit_worker.py"
)


# ═════════════════════════════════════════════════════════════════════════
#  1. DiagnosticReport warning generation
# ═════════════════════════════════════════════════════════════════════════


class TestUploadStepWarnings(unittest.TestCase):
    """Test complete_upload_step() warning generation."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.report = _diagnostic_report.DiagnosticReport(
            reports_dir=Path(self._tmpdir),
            job_id="warn-test",
            blend_name="warn",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_step(self, bytes_transferred, rclone_stats,
                  expected_bytes=None):
        """Start + complete an upload step, return the step dict."""
        self.report.start_stage("upload")
        self.report.start_upload_step(
            1, 1, "test step",
            expected_bytes=expected_bytes,
        )
        self.report.complete_upload_step(
            bytes_transferred=bytes_transferred,
            rclone_stats=rclone_stats,
        )
        steps = self.report._data["stages"]["upload"]["steps"]
        return steps[-1]

    # ── stats_received=False ──

    def test_no_stats_received(self):
        """stats_received=False should produce a warning."""
        step = self._run_step(0, {
            "stats_received": False,
            "checks": 0,
            "transfers": 0,
        })
        self.assertIn("warning", step)
        self.assertIn("no transfer stats", step["warning"])

    def test_no_stats_received_with_expected_bytes(self):
        """stats_received=False + expected bytes should combine warnings."""
        step = self._run_step(0, {
            "stats_received": False,
            "checks": 0,
            "transfers": 0,
        }, expected_bytes=1_000_000)
        self.assertIn("warning", step)
        self.assertIn("no transfer stats", step["warning"])
        self.assertIn("Expected 1000000 bytes", step["warning"])

    # ── checks/transfers counters ──

    def test_zero_checks_zero_transfers(self):
        """checks=0, transfers=0 should warn about empty manifest."""
        step = self._run_step(0, {
            "stats_received": True,
            "checks": 0,
            "transfers": 0,
        })
        self.assertIn("warning", step)
        self.assertIn("manifest may be empty", step["warning"])

    def test_checks_positive_transfers_zero(self):
        """checks>0, transfers=0 should warn about matching files."""
        step = self._run_step(0, {
            "stats_received": True,
            "checks": 42,
            "transfers": 0,
        })
        self.assertIn("warning", step)
        self.assertIn("checked 42 files but transferred 0", step["warning"])

    # ── bytes mismatch ──

    def test_expected_nonzero_transferred_zero(self):
        """Expected >0 bytes but transferred 0 should warn."""
        step = self._run_step(0, {
            "stats_received": True,
            "checks": 10,
            "transfers": 0,
        }, expected_bytes=500_000)
        self.assertIn("warning", step)
        self.assertIn("Expected 500000 bytes but transferred 0", step["warning"])

    def test_transferred_less_than_half_expected(self):
        """Transferred < 50% of expected should warn with percentage."""
        step = self._run_step(100_000, {
            "stats_received": True,
            "checks": 10,
            "transfers": 5,
        }, expected_bytes=500_000)
        self.assertIn("warning", step)
        self.assertIn("20%", step["warning"])

    def test_transferred_above_half_no_extra_warning(self):
        """Transferred >= 50% of expected should NOT add bytes mismatch warning."""
        step = self._run_step(300_000, {
            "stats_received": True,
            "checks": 10,
            "transfers": 10,
        }, expected_bytes=500_000)
        # No checks/transfers anomaly, no bytes mismatch
        self.assertNotIn("warning", step)

    # ── normal success ──

    def test_no_warning_on_success(self):
        """Normal successful transfer should produce no warnings."""
        step = self._run_step(1_000_000, {
            "stats_received": True,
            "checks": 50,
            "transfers": 50,
        }, expected_bytes=1_000_000)
        self.assertNotIn("warning", step)

    def test_no_rclone_stats_no_warning(self):
        """No rclone_stats at all (None) should not crash or warn."""
        step = self._run_step(1024, None)
        self.assertNotIn("warning", step)

    # ── combined warnings (appending) ──

    def test_checks_zero_plus_bytes_mismatch(self):
        """Both checks=0 AND expected-bytes mismatch should combine."""
        step = self._run_step(0, {
            "stats_received": True,
            "checks": 0,
            "transfers": 0,
        }, expected_bytes=1_000_000)
        self.assertIn("warning", step)
        # Should have both parts separated by "; "
        self.assertIn("manifest may be empty", step["warning"])
        self.assertIn("Expected 1000000 bytes but transferred 0", step["warning"])
        self.assertIn("; ", step["warning"])

    def test_no_stats_overrides_checks_warning(self):
        """stats_received=False should override checks/transfers warning."""
        step = self._run_step(0, {
            "stats_received": False,
            "checks": 50,
            "transfers": 0,
        })
        self.assertIn("warning", step)
        self.assertIn("no transfer stats", step["warning"])
        # Should NOT contain the checks-based warning
        self.assertNotIn("checked 50 files", step["warning"])

    # ── edge cases ──

    def test_expected_bytes_zero_no_mismatch_warning(self):
        """expected_bytes=0 should not trigger byte mismatch warnings."""
        step = self._run_step(0, {
            "stats_received": True,
            "checks": 5,
            "transfers": 5,
        }, expected_bytes=0)
        self.assertNotIn("warning", step)

    def test_expected_bytes_none_no_mismatch_warning(self):
        """expected_bytes=None should not trigger byte mismatch warnings."""
        step = self._run_step(0, {
            "stats_received": True,
            "checks": 5,
            "transfers": 5,
        }, expected_bytes=None)
        self.assertNotIn("warning", step)


# ═════════════════════════════════════════════════════════════════════════
#  2. _redact_cmd
# ═════════════════════════════════════════════════════════════════════════


class TestRedactCmd(unittest.TestCase):
    """Test credential redaction in rclone commands."""

    def setUp(self):
        self._redact_cmd = _rclone_utils._redact_cmd

    def test_basic_redaction(self):
        """Sensitive flag values should be replaced with ***."""
        cmd = [
            "/usr/bin/rclone", "copy", "/src", ":s3:bucket/dst",
            "--s3-access-key-id", "AKIAEXAMPLE",
            "--s3-secret-access-key", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "--s3-session-token", "FwoGZXIvYXdzEBYaDHqa0",
            "--transfers", "4",
        ]
        result = self._redact_cmd(cmd)
        self.assertNotIn("AKIAEXAMPLE", result)
        self.assertNotIn("wJalrXUtnFEMI", result)
        self.assertNotIn("FwoGZXIvYXdzEBYaDHqa0", result)
        self.assertIn("--s3-access-key-id ***", result)
        self.assertIn("--s3-secret-access-key ***", result)
        self.assertIn("--s3-session-token ***", result)
        # Non-sensitive flags preserved
        self.assertIn("--transfers 4", result)
        self.assertIn("/usr/bin/rclone", result)
        self.assertIn("copy", result)

    def test_no_sensitive_flags(self):
        """Command without sensitive flags should be returned as-is."""
        cmd = ["/usr/bin/rclone", "ls", ":s3:bucket/"]
        result = self._redact_cmd(cmd)
        self.assertEqual(result, "/usr/bin/rclone ls :s3:bucket/")

    def test_sensitive_flag_at_end(self):
        """Sensitive flag as last element (no value) should not crash."""
        cmd = ["/usr/bin/rclone", "copy", "/src", ":s3:dst",
               "--s3-access-key-id"]
        result = self._redact_cmd(cmd)
        # Flag at end with no value — just include it without masking next
        self.assertIn("--s3-access-key-id", result)
        # Should NOT have *** since there's no next element
        self.assertFalse(result.endswith("***"))

    def test_empty_cmd(self):
        """Empty command should return empty string."""
        self.assertEqual(self._redact_cmd([]), "")

    def test_only_session_token(self):
        """Only session token present."""
        cmd = ["/usr/bin/rclone", "copy", "/a", "/b",
               "--s3-session-token", "SECRET123"]
        result = self._redact_cmd(cmd)
        self.assertNotIn("SECRET123", result)
        self.assertIn("--s3-session-token ***", result)

    def test_preserves_paths_and_flags(self):
        """Non-sensitive parts of command should be fully preserved."""
        cmd = [
            "/usr/bin/rclone", "copy",
            "/home/user/project", ":s3:my-bucket/prefix/",
            "--files-from-raw", "/tmp/filelist.txt",
            "--transfers", "4",
            "--checkers", "4",
            "--s3-access-key-id", "AKIA",
            "--stats", "0.1s",
        ]
        result = self._redact_cmd(cmd)
        self.assertIn("/home/user/project", result)
        self.assertIn(":s3:my-bucket/prefix/", result)
        self.assertIn("--files-from-raw /tmp/filelist.txt", result)
        self.assertIn("--transfers 4", result)
        self.assertIn("--stats 0.1s", result)
        self.assertNotIn("AKIA", result)


# ═════════════════════════════════════════════════════════════════════════
#  3. _log_upload_result (submit_worker)
# ═════════════════════════════════════════════════════════════════════════


class TestLogUploadResult(unittest.TestCase):
    """Test terminal stats logging helper."""

    def setUp(self):
        self._mod = _submit_worker
        self._log_upload_result = self._mod._log_upload_result
        self._captured = []

        # Patch _LOG and _format_size
        self._orig_log = self._mod._LOG
        self._orig_fmt = self._mod._format_size
        self._mod._LOG = lambda msg: self._captured.append(str(msg))
        self._mod._format_size = lambda n: f"{n} B"

    def tearDown(self):
        self._mod._LOG = self._orig_log
        self._mod._format_size = self._orig_fmt

    def test_none_result(self):
        """None result should log 'no stats'."""
        self._log_upload_result(None, label="Test: ")
        self.assertEqual(len(self._captured), 1)
        self.assertIn("no stats", self._captured[0])
        self.assertIn("Test: ", self._captured[0])

    def test_non_dict_result(self):
        """Non-dict result should log the value."""
        self._log_upload_result(42, label="X: ")
        self.assertEqual(len(self._captured), 1)
        self.assertIn("42", self._captured[0])

    def test_normal_stats(self):
        """Normal dict result should log all fields."""
        self._log_upload_result({
            "bytes_transferred": 1024,
            "checks": 10,
            "transfers": 10,
            "errors": 0,
            "stats_received": True,
        }, expected_bytes=2000, label="Deps: ")
        self.assertEqual(len(self._captured), 1)
        line = self._captured[0]
        self.assertIn("Deps: ", line)
        self.assertIn("transferred=1024 B", line)
        self.assertIn("expected=2000 B", line)
        self.assertIn("checks=10", line)
        self.assertIn("transfers=10", line)
        # errors=0 should be omitted
        self.assertNotIn("errors=", line)

    def test_stats_received_false(self):
        """stats_received=False should appear in the output."""
        self._log_upload_result({
            "bytes_transferred": 0,
            "checks": 0,
            "transfers": 0,
            "errors": 0,
            "stats_received": False,
        })
        line = self._captured[0]
        self.assertIn("stats_received=False", line)

    def test_errors_shown(self):
        """Nonzero errors should be logged."""
        self._log_upload_result({
            "bytes_transferred": 500,
            "checks": 5,
            "transfers": 3,
            "errors": 2,
            "stats_received": True,
        })
        line = self._captured[0]
        self.assertIn("errors=2", line)

    def test_command_logged(self):
        """command field in result should be logged as a separate line."""
        self._log_upload_result({
            "bytes_transferred": 100,
            "checks": 1,
            "transfers": 1,
            "errors": 0,
            "stats_received": True,
            "command": "rclone copy /src :s3:dst --s3-access-key-id ***",
        }, label="Arc: ")
        self.assertEqual(len(self._captured), 2)
        self.assertIn("cmd:", self._captured[1])
        self.assertIn("rclone copy /src", self._captured[1])
        # Verify label propagates to cmd line too
        self.assertIn("Arc: ", self._captured[1])

    def test_no_command_no_extra_line(self):
        """Missing command field should not produce an extra log line."""
        self._log_upload_result({
            "bytes_transferred": 100,
            "checks": 1,
            "transfers": 1,
            "errors": 0,
            "stats_received": True,
        })
        self.assertEqual(len(self._captured), 1)

    def test_no_expected_bytes_omits_field(self):
        """expected_bytes=0 should omit the expected= field."""
        self._log_upload_result({
            "bytes_transferred": 100,
            "checks": 1,
            "transfers": 1,
            "errors": 0,
            "stats_received": True,
        }, expected_bytes=0)
        line = self._captured[0]
        self.assertNotIn("expected=", line)

    def test_empty_command_not_logged(self):
        """Empty string command should not produce an extra log line."""
        self._log_upload_result({
            "bytes_transferred": 100,
            "checks": 1,
            "transfers": 1,
            "errors": 0,
            "stats_received": True,
            "command": "",
        })
        self.assertEqual(len(self._captured), 1)


# ═════════════════════════════════════════════════════════════════════════
#  4. _is_filesystem_root
# ═════════════════════════════════════════════════════════════════════════


class TestIsFilesystemRoot(unittest.TestCase):
    """Test filesystem root detection."""

    def setUp(self):
        self._is_root = _submit_worker._is_filesystem_root

    def test_unix_root(self):
        self.assertTrue(self._is_root("/"))

    def test_empty_string(self):
        self.assertTrue(self._is_root(""))

    def test_windows_drive_roots(self):
        self.assertTrue(self._is_root("C:/"))
        self.assertTrue(self._is_root("C:\\"))
        self.assertTrue(self._is_root("G:"))
        self.assertTrue(self._is_root("D:/"))

    def test_macos_volume(self):
        self.assertTrue(self._is_root("/Volumes/MyDrive"))

    def test_linux_mnt(self):
        self.assertTrue(self._is_root("/mnt/data"))

    def test_linux_media(self):
        self.assertTrue(self._is_root("/media/user/usb"))

    def test_normal_project_path(self):
        self.assertFalse(self._is_root("/home/user/projects/myproject"))
        self.assertFalse(self._is_root("C:/Users/me/Documents"))
        self.assertFalse(self._is_root("/Volumes/MyDrive/Projects"))

    def test_deeper_mnt(self):
        """Deeper paths under /mnt should not be roots."""
        self.assertFalse(self._is_root("/mnt/data/projects"))


# ═════════════════════════════════════════════════════════════════════════
#  5. _split_manifest_by_first_dir
# ═════════════════════════════════════════════════════════════════════════


class TestSplitManifest(unittest.TestCase):
    """Test manifest splitting for filesystem-root uploads."""

    def setUp(self):
        self._split = _submit_worker._split_manifest_by_first_dir

    def test_basic_split(self):
        manifest = [
            "Users/artist/textures/a.png",
            "Users/artist/textures/b.png",
            "Projects/assets/c.exr",
        ]
        groups = self._split(manifest)
        self.assertEqual(set(groups.keys()), {"Users", "Projects"})
        self.assertEqual(len(groups["Users"]), 2)
        self.assertEqual(len(groups["Projects"]), 1)
        # Check that the first-dir prefix is stripped from entries
        self.assertIn("artist/textures/a.png", groups["Users"])

    def test_files_at_root(self):
        """Files without a directory component go to the '' group."""
        manifest = ["readme.txt", "dir/file.png"]
        groups = self._split(manifest)
        self.assertIn("", groups)
        self.assertEqual(groups[""], ["readme.txt"])
        self.assertEqual(groups["dir"], ["file.png"])

    def test_empty_manifest(self):
        self.assertEqual(self._split([]), {})


# ═════════════════════════════════════════════════════════════════════════
#  6. _rclone_bytes / _rclone_stats / _is_empty_upload helpers
# ═════════════════════════════════════════════════════════════════════════


class TestRcloneHelpers(unittest.TestCase):
    """Test the small rclone result extraction helpers."""

    def test_rclone_bytes_none(self):
        self.assertEqual(_submit_worker._rclone_bytes(None), 0)

    def test_rclone_bytes_dict(self):
        self.assertEqual(
            _submit_worker._rclone_bytes({"bytes_transferred": 42}), 42
        )

    def test_rclone_bytes_int(self):
        self.assertEqual(_submit_worker._rclone_bytes(99), 99)

    def test_rclone_stats_dict(self):
        d = {"bytes_transferred": 1, "checks": 2}
        self.assertIs(_submit_worker._rclone_stats(d), d)

    def test_rclone_stats_none(self):
        self.assertIsNone(_submit_worker._rclone_stats(None))

    def test_rclone_stats_int(self):
        self.assertIsNone(_submit_worker._rclone_stats(42))

    def test_is_empty_upload_none_result(self):
        self.assertTrue(_submit_worker._is_empty_upload(None, 10))

    def test_is_empty_upload_no_stats(self):
        self.assertTrue(_submit_worker._is_empty_upload(
            {"stats_received": False}, 10
        ))

    def test_is_empty_upload_zero_transfers(self):
        self.assertTrue(_submit_worker._is_empty_upload(
            {"stats_received": True, "transfers": 0}, 10
        ))

    def test_is_empty_upload_has_transfers(self):
        self.assertFalse(_submit_worker._is_empty_upload(
            {"stats_received": True, "transfers": 5}, 10
        ))

    def test_is_empty_upload_zero_expected(self):
        """If no files expected, never considered empty."""
        self.assertFalse(_submit_worker._is_empty_upload(None, 0))

    def test_get_rclone_tail_dict(self):
        self.assertEqual(
            _submit_worker._get_rclone_tail({"tail_lines": ["a", "b"]}),
            ["a", "b"]
        )

    def test_get_rclone_tail_none(self):
        self.assertEqual(_submit_worker._get_rclone_tail(None), [])


# ═════════════════════════════════════════════════════════════════════════
#  7. Diagnostic report JSON round-trip with warnings
# ═════════════════════════════════════════════════════════════════════════


class TestReportJsonRoundTrip(unittest.TestCase):
    """Test that warnings survive JSON serialization in the report file."""

    def test_warning_persisted_to_disk(self):
        """Warnings generated by complete_upload_step() should appear in the JSON file."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d),
                job_id="roundtrip-test",
                blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "deps", expected_bytes=1_000_000)
            report.complete_upload_step(
                bytes_transferred=0,
                rclone_stats={
                    "stats_received": False,
                    "checks": 0,
                    "transfers": 0,
                    "command": "rclone copy /src :s3:bucket/ --s3-access-key-id ***",
                },
            )
            report.complete_stage("upload")
            report.finalize()

            # Read back from disk
            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            step = data["stages"]["upload"]["steps"][0]
            self.assertIn("warning", step)
            self.assertIn("no transfer stats", step["warning"])
            self.assertIn("Expected 1000000 bytes", step["warning"])
            # rclone_stats should be stored too (with the command)
            self.assertIn("rclone_stats", step)
            self.assertEqual(
                step["rclone_stats"]["command"],
                "rclone copy /src :s3:bucket/ --s3-access-key-id ***",
            )

    def test_no_warning_not_in_json(self):
        """Successful upload should not have a 'warning' key in JSON."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d),
                job_id="ok-test",
                blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "blend")
            report.complete_upload_step(
                bytes_transferred=5000,
                rclone_stats={
                    "stats_received": True,
                    "checks": 5,
                    "transfers": 5,
                },
            )
            report.complete_stage("upload")
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            step = data["stages"]["upload"]["steps"][0]
            self.assertNotIn("warning", step)


# ═════════════════════════════════════════════════════════════════════════
#  8. Report v3.0: environment section
# ═════════════════════════════════════════════════════════════════════════


class TestReportEnvironment(unittest.TestCase):
    """Test environment recording in the diagnostic report."""

    def test_default_environment(self):
        """Report should capture OS/Python info by default."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="env-test", blend_name="test",
            )
            env = report._data["environment"]
            self.assertIn("os", env)
            self.assertIn("python_version", env)
            self.assertIn("architecture", env)
            self.assertTrue(len(env["os"]) > 0)

    def test_set_environment(self):
        """set_environment() should update specific keys."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="env-test2", blend_name="test",
            )
            report.set_environment("rclone_version", "v1.65.0")
            report.set_environment("rclone_bin", "/usr/bin/rclone")
            self.assertEqual(report._data["environment"]["rclone_version"], "v1.65.0")
            self.assertEqual(report._data["environment"]["rclone_bin"], "/usr/bin/rclone")

    def test_environment_persisted_to_disk(self):
        """Environment data should survive JSON round-trip."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="env-persist", blend_name="test",
            )
            report.set_environment("rclone_version", "v1.65.0")
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["environment"]["rclone_version"], "v1.65.0")
            self.assertIn("os", data["environment"])


# ═════════════════════════════════════════════════════════════════════════
#  9. Report v3.0: preflight section
# ═════════════════════════════════════════════════════════════════════════


class TestReportPreflight(unittest.TestCase):
    """Test preflight recording."""

    def test_preflight_passed(self):
        """Passed preflight with no issues."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="pf-pass", blend_name="test",
            )
            report.record_preflight(True, [])
            pf = report._data["preflight"]
            self.assertTrue(pf["passed"])
            self.assertEqual(pf["issues"], [])
            self.assertIsNone(pf["user_override"])

    def test_preflight_failed_with_override(self):
        """Failed preflight where user chose to continue."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="pf-fail", blend_name="test",
            )
            report.record_preflight(False, ["Low disk space", "Network slow"], True)
            pf = report._data["preflight"]
            self.assertFalse(pf["passed"])
            self.assertEqual(len(pf["issues"]), 2)
            self.assertTrue(pf["user_override"])

    def test_preflight_persisted(self):
        """Preflight data round-trips through JSON."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="pf-disk", blend_name="test",
            )
            report.record_preflight(False, ["Disk full"], True)
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertFalse(data["preflight"]["passed"])
            self.assertIn("Disk full", data["preflight"]["issues"])
            self.assertTrue(data["preflight"]["user_override"])


# ═════════════════════════════════════════════════════════════════════════
#  10. Report v3.0: user choices
# ═════════════════════════════════════════════════════════════════════════


class TestReportUserChoices(unittest.TestCase):
    """Test user choice recording."""

    def test_record_user_choice(self):
        """record_user_choice() should append to the list."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="uc-test", blend_name="test",
            )
            report.record_user_choice(
                "Dependency issues found", "y",
                options=["Continue", "Cancel", "Open reports"],
            )
            report.record_user_choice("Continue after viewing reports?", "n")

            choices = report._data["user_choices"]
            self.assertEqual(len(choices), 2)
            self.assertEqual(choices[0]["prompt"], "Dependency issues found")
            self.assertEqual(choices[0]["choice"], "y")
            self.assertEqual(choices[0]["options"], ["Continue", "Cancel", "Open reports"])
            self.assertIn("timestamp", choices[0])
            self.assertEqual(choices[1]["choice"], "n")
            self.assertNotIn("options", choices[1])

    def test_user_choices_persisted(self):
        """User choices should round-trip through JSON."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="uc-persist", blend_name="test",
            )
            report.record_user_choice("Continue?", "y")
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(len(data["user_choices"]), 1)
            self.assertEqual(data["user_choices"][0]["choice"], "y")


# ═════════════════════════════════════════════════════════════════════════
#  11. Report v3.0: upload summary (computed in complete_stage)
# ═════════════════════════════════════════════════════════════════════════


class TestReportUploadSummary(unittest.TestCase):
    """Test upload stage summary computation."""

    def test_upload_summary_computed(self):
        """complete_stage('upload') should compute summary from all steps."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="sum-test", blend_name="test",
            )
            report.start_stage("upload")

            # Step 1
            report.start_upload_step(1, 2, "Blend")
            report.complete_upload_step(
                bytes_transferred=5000,
                rclone_stats={"checks": 1, "transfers": 1, "errors": 0, "stats_received": True},
            )

            # Step 2 — with warning
            report.start_upload_step(2, 2, "Dependencies", expected_bytes=10000)
            report.complete_upload_step(
                bytes_transferred=0,
                rclone_stats={"checks": 0, "transfers": 0, "errors": 1, "stats_received": True},
            )

            report.complete_stage("upload")

            summary = report._data["stages"]["upload"]["summary"]
            self.assertEqual(summary["total_bytes_transferred"], 5000)
            self.assertEqual(summary["total_checks"], 1)
            self.assertEqual(summary["total_transfers"], 1)
            self.assertEqual(summary["total_errors"], 1)
            self.assertEqual(summary["step_count"], 2)
            self.assertTrue(summary["has_warnings"])
            self.assertIsInstance(summary["total_elapsed_seconds"], float)

    def test_upload_summary_no_warnings(self):
        """Summary should report has_warnings=False when no warnings exist."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="sum-ok", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "Blend")
            report.complete_upload_step(
                bytes_transferred=1000,
                rclone_stats={"checks": 5, "transfers": 5, "errors": 0, "stats_received": True},
            )
            report.complete_stage("upload")

            summary = report._data["stages"]["upload"]["summary"]
            self.assertFalse(summary["has_warnings"])
            self.assertEqual(summary["step_count"], 1)


# ═════════════════════════════════════════════════════════════════════════
#  12. Report v3.0: elapsed_seconds + tail_lines truncation
# ═════════════════════════════════════════════════════════════════════════


class TestReportStepDetails(unittest.TestCase):
    """Test elapsed_seconds and tail_lines truncation in upload steps."""

    def test_elapsed_seconds_computed(self):
        """complete_upload_step should compute elapsed_seconds."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="elapsed-test", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "test")
            report.complete_upload_step(bytes_transferred=100)

            step = report._data["stages"]["upload"]["steps"][0]
            self.assertIn("elapsed_seconds", step)
            self.assertIsInstance(step["elapsed_seconds"], (int, float))
            self.assertGreaterEqual(step["elapsed_seconds"], 0)

    def test_tail_lines_truncated(self):
        """tail_lines > 20 should be truncated to last 20 entries."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="tail-test", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "test")

            long_tail = [f"line_{i}" for i in range(100)]
            report.complete_upload_step(
                bytes_transferred=1000,
                rclone_stats={
                    "checks": 5, "transfers": 5, "errors": 0,
                    "stats_received": True, "tail_lines": long_tail,
                },
            )

            step = report._data["stages"]["upload"]["steps"][0]
            stored_tail = step["rclone_stats"]["tail_lines"]
            self.assertEqual(len(stored_tail), 20)
            # Should keep the LAST 20 lines
            self.assertEqual(stored_tail[0], "line_80")
            self.assertEqual(stored_tail[-1], "line_99")
            self.assertTrue(step["rclone_stats"]["tail_lines_truncated"])

    def test_short_tail_not_truncated(self):
        """tail_lines <= 20 should not be truncated."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="short-tail", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "test")

            short_tail = [f"line_{i}" for i in range(5)]
            report.complete_upload_step(
                bytes_transferred=1000,
                rclone_stats={
                    "checks": 5, "transfers": 5, "errors": 0,
                    "stats_received": True, "tail_lines": short_tail,
                },
            )

            step = report._data["stages"]["upload"]["steps"][0]
            self.assertEqual(len(step["rclone_stats"]["tail_lines"]), 5)
            self.assertNotIn("tail_lines_truncated", step["rclone_stats"])


# ═════════════════════════════════════════════════════════════════════════
#  13. Report v3.0: source/destination/verb in upload steps
# ═════════════════════════════════════════════════════════════════════════


class TestReportUploadStepMeta(unittest.TestCase):
    """Test source/destination/verb params in start_upload_step."""

    def test_source_dest_verb_stored(self):
        """source, destination, verb should be stored in step dict."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="sdv-test", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(
                1, 1, "Uploading blend",
                source="/home/user/file.blend",
                destination=":s3:bucket/project/file.blend",
                verb="copyto",
            )
            report.complete_upload_step(bytes_transferred=1000)

            step = report._data["stages"]["upload"]["steps"][0]
            self.assertEqual(step["source"], "/home/user/file.blend")
            self.assertEqual(step["destination"], ":s3:bucket/project/file.blend")
            self.assertEqual(step["verb"], "copyto")

    def test_optional_params_omitted(self):
        """Omitted source/dest/verb should not appear in step dict."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="sdv-none", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "test step")
            report.complete_upload_step(bytes_transferred=100)

            step = report._data["stages"]["upload"]["steps"][0]
            self.assertNotIn("source", step)
            self.assertNotIn("destination", step)
            self.assertNotIn("verb", step)

    def test_all_fields_persisted_to_disk(self):
        """All step fields should survive JSON round-trip."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="sdv-disk", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(
                1, 1, "Uploading deps",
                manifest_entries=42,
                expected_bytes=500000,
                source="/mnt/data",
                destination=":s3:bucket/proj/",
                verb="copy",
            )
            report.complete_upload_step(
                bytes_transferred=500000,
                rclone_stats={"checks": 42, "transfers": 42, "errors": 0, "stats_received": True},
            )
            report.complete_stage("upload")
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            step = data["stages"]["upload"]["steps"][0]
            self.assertEqual(step["source"], "/mnt/data")
            self.assertEqual(step["destination"], ":s3:bucket/proj/")
            self.assertEqual(step["verb"], "copy")
            self.assertEqual(step["manifest_entries"], 42)
            self.assertEqual(step["expected_bytes"], 500000)
            self.assertIn("elapsed_seconds", step)
            self.assertIn("started_at", step)
            self.assertIn("completed_at", step)


# ═════════════════════════════════════════════════════════════════════════
#  14. Report v3.0: split upload groups
# ═════════════════════════════════════════════════════════════════════════


class TestReportSplitGroups(unittest.TestCase):
    """Test split upload group recording."""

    def test_split_groups_recorded(self):
        """add_upload_split_group should store group details in current step."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="split-test", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "Uploading deps (split)")

            report.add_upload_split_group(
                group_name="Users",
                file_count=10,
                source="/Users",
                destination=":s3:bucket/proj/Users/",
                rclone_stats={
                    "bytes_transferred": 5000,
                    "checks": 10, "transfers": 10, "errors": 0,
                    "stats_received": True,
                },
            )
            report.add_upload_split_group(
                group_name="Projects",
                file_count=5,
                source="/Projects",
                destination=":s3:bucket/proj/Projects/",
                rclone_stats={
                    "bytes_transferred": 0,
                    "checks": 5, "transfers": 0, "errors": 0,
                    "stats_received": True,
                },
            )

            step = report._data["stages"]["upload"]["steps"][0]
            self.assertIn("split_groups", step)
            groups = step["split_groups"]
            self.assertEqual(len(groups), 2)

            self.assertEqual(groups[0]["group_name"], "Users")
            self.assertEqual(groups[0]["file_count"], 10)
            self.assertEqual(groups[0]["bytes_transferred"], 5000)
            self.assertNotIn("warning", groups[0])

            self.assertEqual(groups[1]["group_name"], "Projects")
            self.assertEqual(groups[1]["transfers"], 0)
            self.assertIn("warning", groups[1])

    def test_split_group_without_step(self):
        """add_upload_split_group with no current step should be a no-op."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="split-noop", blend_name="test",
            )
            # No start_upload_step called
            report.add_upload_split_group(
                group_name="test", file_count=1,
                source="/src", destination="/dst",
            )
            # Should not crash; upload steps list stays empty
            self.assertEqual(len(report._data["stages"]["upload"]["steps"]), 0)

    def test_split_groups_persisted(self):
        """Split groups should survive JSON round-trip."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="split-disk", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "deps")
            report.add_upload_split_group(
                group_name="textures", file_count=3,
                source="/textures", destination=":s3:bucket/proj/textures/",
                rclone_stats={"bytes_transferred": 1234, "checks": 3, "transfers": 3,
                              "errors": 0, "stats_received": True},
            )
            report.complete_upload_step(bytes_transferred=1234)
            report.complete_stage("upload")
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            groups = data["stages"]["upload"]["steps"][0]["split_groups"]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["group_name"], "textures")
            self.assertEqual(groups[0]["bytes_transferred"], 1234)


# ═════════════════════════════════════════════════════════════════════════
#  15. Report v3.0: pack dependency size
# ═════════════════════════════════════════════════════════════════════════


class TestReportPackDependencySize(unittest.TestCase):
    """Test dependency size recording in pack stage."""

    def test_dependency_size_set(self):
        """set_pack_dependency_size should store in pack summary."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="dep-size", blend_name="test",
            )
            report.start_stage("pack")
            report.set_pack_dependency_size(123456789)
            report.complete_stage("pack")

            summary = report._data["stages"]["pack"]["summary"]
            self.assertEqual(summary["dependency_total_size"], 123456789)

    def test_dependency_size_persisted(self):
        """Dependency total size should survive JSON round-trip."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="dep-persist", blend_name="test",
            )
            report.start_stage("pack")
            report.set_pack_dependency_size(999)
            report.complete_stage("pack")
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(
                data["stages"]["pack"]["summary"]["dependency_total_size"], 999
            )


# ═════════════════════════════════════════════════════════════════════════
#  16. Report v3.0: version + metadata
# ═════════════════════════════════════════════════════════════════════════


class TestReportVersionAndMetadata(unittest.TestCase):
    """Test report version and metadata fields."""

    def test_report_version(self):
        """Report should have version 3.0."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="ver-test", blend_name="test",
            )
            self.assertEqual(report._data["report_version"], "3.0")

    def test_project_root_method_metadata(self):
        """project_root_method should be settable via set_metadata."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="prm-test", blend_name="test",
            )
            report.set_metadata("project_root_method", "filesystem_root")
            self.assertEqual(
                report._data["metadata"]["project_root_method"], "filesystem_root"
            )

    def test_initial_metadata_merge(self):
        """Constructor metadata should be merged into defaults."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="meta-test", blend_name="test",
                metadata={
                    "upload_type": "PROJECT",
                    "job_name": "MyJob",
                    "blender_version": "4.0",
                },
            )
            meta = report._data["metadata"]
            self.assertEqual(meta["upload_type"], "PROJECT")
            self.assertEqual(meta["job_name"], "MyJob")
            self.assertEqual(meta["blender_version"], "4.0")
            # Default fields should still exist
            self.assertIn("status", meta)
            self.assertIn("started_at", meta)

    def test_finalize_sets_completion(self):
        """finalize() should set completed_at and status."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="fin-test", blend_name="test",
            )
            self.assertIsNone(report._data["metadata"]["completed_at"])
            self.assertEqual(report._data["metadata"]["status"], "in_progress")

            report.finalize()

            self.assertIsNotNone(report._data["metadata"]["completed_at"])
            self.assertEqual(report._data["metadata"]["status"], "completed")

    def test_full_report_schema(self):
        """A complete report should have all top-level sections."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="schema-test", blend_name="test",
            )
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check all required top-level sections
            self.assertIn("report_version", data)
            self.assertIn("metadata", data)
            self.assertIn("environment", data)
            self.assertIn("preflight", data)
            self.assertIn("stages", data)
            self.assertIn("user_choices", data)
            self.assertIn("issues", data)

            # Check stages subsections
            self.assertIn("trace", data["stages"])
            self.assertIn("pack", data["stages"])
            self.assertIn("upload", data["stages"])

            # Check issues subsections
            self.assertIn("missing_files", data["issues"])
            self.assertIn("unreadable_files", data["issues"])
            self.assertIn("cross_drive_files", data["issues"])
            self.assertIn("absolute_path_files", data["issues"])


# ═════════════════════════════════════════════════════════════════════════
#  17. _check_risky_path_chars
# ═════════════════════════════════════════════════════════════════════════


class TestCheckRiskyPathChars(unittest.TestCase):
    """Test preflight warning for shell-risky path characters."""

    def setUp(self):
        self._check = _submit_worker._check_risky_path_chars

    def test_parens_detected(self):
        """Parentheses in path should produce a warning."""
        result = self._check("G:/Dropbox (Compte personnel)/project/file.blend")
        self.assertIsNotNone(result)
        self.assertIn("'('", result)
        self.assertIn("')'", result)
        self.assertIn("special characters", result)

    def test_apostrophe_detected(self):
        """Apostrophe in path should produce a warning."""
        result = self._check("/home/user/Grog's-Hideout/scene.blend")
        self.assertIsNotNone(result)
        self.assertIn("\"'\"", result)

    def test_space_detected(self):
        """Spaces in path should produce a warning."""
        result = self._check("C:/Users/My User/project/file.blend")
        self.assertIsNotNone(result)
        self.assertIn("' '", result)

    def test_clean_path_no_warning(self):
        """Path without risky characters should return None."""
        result = self._check("/home/user/projects/my_project/scene.blend")
        self.assertIsNone(result)

    def test_multiple_risky_chars(self):
        """Path with multiple risky characters should list all of them."""
        result = self._check("C:/Dropbox (Personal)/Grog's $project/file.blend")
        self.assertIsNotNone(result)
        self.assertIn("'('", result)
        self.assertIn("')'", result)
        self.assertIn("\"'\"", result)
        self.assertIn("'$'", result)

    def test_empty_path(self):
        """Empty path should return None."""
        result = self._check("")
        self.assertIsNone(result)

    def test_windows_backslash_path(self):
        """Backslashes are normal on Windows and should NOT be flagged."""
        result = self._check("C:\\Users\\artist\\project\\file.blend")
        self.assertIsNone(result)

    def test_all_risky_chars(self):
        """Each risky character individually should be detected."""
        for char in "()'\"` &|;$!#":
            result = self._check(f"/path/with{char}char/file.blend")
            self.assertIsNotNone(result, f"Character {char!r} should be detected")


# ═════════════════════════════════════════════════════════════════════════
#  18. _RISKY_CHARS constant
# ═════════════════════════════════════════════════════════════════════════


class TestRiskyCharsConstant(unittest.TestCase):
    """Verify _RISKY_CHARS contains the expected characters."""

    def test_expected_chars(self):
        expected = set("()'\"` &|;$!#")
        self.assertEqual(_submit_worker._RISKY_CHARS, expected)


if __name__ == "__main__":
    unittest.main()
