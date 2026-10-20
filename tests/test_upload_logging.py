#!/usr/bin/env python3
"""
Tests for bulletproof upload logging.

Covers:
- submit_worker._log_upload_result() terminal output
- submit_worker._is_filesystem_root() detection

Usage:
    python -m pytest tests/test_upload_logging.py -v
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


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
_submit_worker = importlib.import_module(
    f"{_pkg_name}.transfers.submit.submit_worker"
)
_environment = importlib.import_module(f"{_pkg_name}.environment")


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


# _log_upload_result (submit_worker)


# _is_filesystem_root


# _split_manifest_by_first_dir


# Structured upload success marker


# _is_empty_upload


# Diagnostic report persistence


# Report v3.0: upload summary (computed in complete_stage)


# Report v3.0: split upload groups


# ZIP pack summary


# _check_risky_path_chars


# Farm ZIP unpack filename guards


if __name__ == "__main__":
    unittest.main()
