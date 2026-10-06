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
import types
import unittest
from pathlib import Path
from unittest import mock

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


def _synthesize_addon_package() -> str:
    """Create the package tree workers use without importing add-on __init__.py."""
    pkg_name = "_test_sulu_blender_addon"
    packages = {
        pkg_name: _addon_dir,
        f"{pkg_name}.utils": _addon_dir / "utils",
        f"{pkg_name}.transfers": _addon_dir / "transfers",
        f"{pkg_name}.transfers.submit": _addon_dir / "transfers" / "submit",
    }
    for name, path in packages.items():
        if name in sys.modules:
            continue
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
    return pkg_name


_pkg_name = _synthesize_addon_package()
_diagnostic_report = importlib.import_module(f"{_pkg_name}.utils.diagnostic_report")
_logger_utils = importlib.import_module(f"{_pkg_name}.utils.logger_utils")
_submit_logger = importlib.import_module(f"{_pkg_name}.utils.submit_logger")
_rclone_utils = importlib.import_module(f"{_pkg_name}.transfers.rclone_utils")
_submit_worker = importlib.import_module(
    f"{_pkg_name}.transfers.submit.submit_worker"
)
_environment = importlib.import_module(f"{_pkg_name}.environment")
_farm_upload_harness = _load_module_directly(
    "farm_upload_harness", _addon_dir / "tests" / "realworld" / "test_farm_upload.py"
)


class TestStorageCredentialPrefetch(unittest.TestCase):
    def test_main_rejects_mixed_environment_before_starting_work(self):
        clear_console = mock.Mock()
        session_factory = mock.Mock()
        mods = {
            "validate_handoff_environment": _environment.validate_handoff_environment,
            "clear_console": clear_console,
            "requests_retry_session": session_factory,
        }
        handoff = {
            "environment": "test",
            "pocketbase_url": "https://api.superlumin.al",
            "project": {
                "id": "project-1",
                "organization_id": "org-1",
                "sqid": "Project1",
            },
            "job_id": "job-1",
        }

        with (
            mock.patch.object(
                _submit_worker,
                "_load_handoff_from_argv",
                return_value=handoff,
            ),
            mock.patch.object(
                _submit_worker,
                "_bootstrap_addon_modules",
                return_value=mods,
            ),
            self.assertRaisesRegex(ValueError, "mixes Sulu environments"),
        ):
            _submit_worker.main()

        clear_console.assert_not_called()
        session_factory.assert_not_called()


class TestRcloneFinalizingProgress(unittest.TestCase):
    """100% is emitted only after the rclone process confirms success."""

    class _Logger:
        def __init__(self):
            self.calls = []

        def transfer_progress(self, current, total):
            self.calls.append((current, total, ""))

        def transfer_progress_ext(
            self,
            current,
            total,
            *,
            status="",
            current_file="",
            checks=0,
            transfers=0,
        ):
            self.calls.append((current, total, status))

    class _Process:
        def __init__(self, lines, exit_code=0):
            self.stdout = lines
            self.exit_code = exit_code

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def wait(self, timeout=None):
            return self.exit_code

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True


    def test_failed_process_never_emits_terminal_100_percent(self):
        lines = [
            json.dumps(
                {
                    "stats": {
                        "bytes": 1000,
                        "totalBytes": 1000,
                        "checks": 0,
                        "transfers": 0,
                        "errors": 1,
                        "elapsedTime": 2.0,
                    }
                }
            )
            + "\n",
            json.dumps(
                {
                    "level": "error",
                    "msg": "connection reset by peer",
                }
            )
            + "\n",
        ]
        process = self._Process(lines, exit_code=1)
        logger = self._Logger()

        with mock.patch.object(
            _rclone_utils,
            "_rclone_supports_flag",
            return_value=False,
        ), mock.patch.object(
            _rclone_utils.subprocess,
            "Popen",
            return_value=process,
        ), mock.patch.object(
            _rclone_utils.time,
            "perf_counter",
            side_effect=[10.0, 12.0, 15.0],
        ):
            with self.assertRaises(_rclone_utils.RcloneError):
                _rclone_utils.run_rclone(
                    ["rclone"],
                    "move",
                    "/tmp/archive.zip",
                    ":s3:bucket/",
                    logger=logger,
                    total_bytes=1000,
                )

        self.assertIn((999, 1000, "finalizing"), logger.calls)
        self.assertNotIn((1000, 1000, "complete"), logger.calls)


# DiagnosticReport warning generation


# _redact_cmd


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


# _log_upload_result (submit_worker)


# _is_filesystem_root


# _split_manifest_by_first_dir


# Structured upload success marker


# _is_empty_upload


# Diagnostic report persistence


# Report v3.0: upload summary (computed in complete_stage)


# Report v3.0: elapsed_seconds and tail_lines truncation


# Report v3.0: split upload groups


# ZIP pack summary


# _check_risky_path_chars


# Farm ZIP unpack filename guards


if __name__ == "__main__":
    unittest.main()
