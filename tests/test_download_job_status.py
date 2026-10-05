"""
Test that download_worker._fetch_job_details handles every response shape
the queue manager can produce — including the placeholder dict the backend
now returns for jobs not yet in `Database.jobs` (`{"status": "unknown",
"tasks": {...zeros}, "total_tasks": 0, "missing": True}` wrapped as
`{"status": "success", "body": {...}}` by Sanic).

The worker is normally launched as a subprocess by Blender — it reads a
handoff JSON file from argv[1] and dynamically imports the rest of the
add-on. This test fakes both: writes a minimal handoff file, stubs the
imported helper modules, then imports the worker module and patches its
module-level globals so `_fetch_job_details` can run in isolation.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# Make repo root importable so `_load_worker_module` can manipulate
# sys.modules under the addon's package name.
REPO_ROOT = Path(__file__).resolve().parents[1]


# Worker bootstrap fakes


def _stub_addon_modules(pkg_name: str) -> None:
    """The worker's top-level code does
    `importlib.import_module(f"{pkg_name}.transfers.rclone_utils")` etc.
    We stub those out so the import doesn't try to do real work.
    """
    if "requests" not in sys.modules:
        requests_mod = types.ModuleType("requests")
        requests_mod.Session = object
        requests_mod.RequestException = Exception
        sys.modules["requests"] = requests_mod

    if pkg_name in sys.modules:
        return
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(REPO_ROOT)]
    sys.modules[pkg_name] = pkg

    transfers_pkg = types.ModuleType(f"{pkg_name}.transfers")
    transfers_pkg.__path__ = []
    sys.modules[f"{pkg_name}.transfers"] = transfers_pkg

    utils_pkg = types.ModuleType(f"{pkg_name}.utils")
    utils_pkg.__path__ = []
    sys.modules[f"{pkg_name}.utils"] = utils_pkg

    rclone_mod = types.ModuleType(f"{pkg_name}.transfers.rclone_utils")
    rclone_mod.run_rclone = MagicMock()
    rclone_mod.ensure_rclone = MagicMock()
    sys.modules[f"{pkg_name}.transfers.rclone_utils"] = rclone_mod

    worker_utils_mod = types.ModuleType(f"{pkg_name}.utils.worker_utils")
    worker_utils_mod.clear_console = MagicMock()
    worker_utils_mod.open_folder = MagicMock()
    worker_utils_mod._build_base = MagicMock(return_value=["rclone"])
    worker_utils_mod.requests_retry_session = MagicMock()
    worker_utils_mod.CLOUDFLARE_R2_DOMAIN = "example.r2.cloudflarestorage.com"
    sys.modules[f"{pkg_name}.utils.worker_utils"] = worker_utils_mod

    download_logger_mod = types.ModuleType(f"{pkg_name}.utils.download_logger")

    class _FakeLogger:
        def __init__(self, *a, **kw):
            self.warnings = []
            self.infos = []

        def warning(self, msg):
            self.warnings.append(msg)

        def info(self, msg):
            self.infos.append(msg)

        def fatal(self, msg):
            raise RuntimeError(msg)

    download_logger_mod.DownloadLogger = _FakeLogger
    sys.modules[f"{pkg_name}.utils.download_logger"] = download_logger_mod


def _load_worker_module():
    """Boot download_worker.py with a fake handoff file and stubbed addon
    imports. Returns the imported module (cached in sys.modules so
    subsequent calls reuse it)."""
    cached_name = "_test_download_worker"
    if cached_name in sys.modules:
        return sys.modules[cached_name]

    addon_dir = REPO_ROOT
    pkg_name = addon_dir.name.replace("-", "_")
    _stub_addon_modules(pkg_name)

    handoff = {
        "addon_dir": str(addon_dir),
        "job_id": "test-job-id",
        "job_name": "test-job",
        "download_path": tempfile.mkdtemp(prefix="sulu_test_dl_"),
        "rclone_bin": "/bin/true",
        "s3info": {
            "bucket": "render-test",
            "access_key_id": "AKIA",
            "secret_access_key": "SECRET",
            "session_token": "TOKEN",
        },
        "bucket": "render-test",
        "sarfis_url": "http://fake-sarfis",
        "sarfis_token": "fake-token",
        "download_type": "auto",
        "job": {
            "status": "queued",
            "tasks": {"queued": 5, "running": 0, "finished": 0, "error": 0, "paused": 0},
            "total_tasks": 5,
        },
    }
    handoff_path = Path(tempfile.mkstemp(prefix="sulu_handoff_", suffix=".json")[1])
    handoff_path.write_text(json.dumps(handoff))

    orig_argv = sys.argv[:]
    orig_input = __builtins__["input"] if isinstance(__builtins__, dict) else __builtins__.input
    sys.argv = ["download_worker.py", str(handoff_path)]
    # The top-level except block calls input() on failure; never let it block.
    if isinstance(__builtins__, dict):
        __builtins__["input"] = lambda *a, **k: ""
    else:
        __builtins__.input = lambda *a, **k: ""

    try:
        spec = importlib.util.spec_from_file_location(
            cached_name,
            str(addon_dir / "transfers" / "download" / "download_worker.py"),
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[cached_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = orig_argv
        if isinstance(__builtins__, dict):
            __builtins__["input"] = orig_input
        else:
            __builtins__.input = orig_input


# Fake requests session helpers


# Tests


class OutputListingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load_worker_module()

    def setUp(self):
        self.worker.base_cmd = ["rclone", "--s3-access-key-id", "AKIA"]
        self.worker.bucket = "render-test"
        self.worker.job_id = "job-1"
        self.worker._SKIPPED_OUTPUTS_WARNED = False
        self.worker.logger = MagicMock()


    def test_run_output_copy_caches_completed_keys_and_copies_only_each_delta(self):
        self.worker.run_rclone = MagicMock()
        state = self.worker._OutputCopyState({"composite/0001.png"})
        batches = []

        def record_batch(files):
            batches.append(list(files))
            return f"/tmp/sulu-files-{len(batches)}.txt"

        with (
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                side_effect=[
                    (["composite/0001.png", "composite/0002.png"], []),
                    (
                        [
                            "composite/0001.png",
                            "composite/0002.png",
                            "composite/0003.png",
                        ],
                        [],
                    ),
                ],
            ),
            patch.object(
                self.worker,
                "_write_files_from_list",
                side_effect=record_batch,
            ),
            patch.object(self.worker.os, "unlink"),
        ):
            first_count = self.worker._run_output_copy("/tmp/download", state)
            second_count = self.worker._run_output_copy("/tmp/download", state)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)
        self.assertEqual(
            batches,
            [["composite/0002.png"], ["composite/0003.png"]],
        )
        self.assertEqual(self.worker.run_rclone.call_count, 2)
        self.assertEqual(
            state.downloaded_files,
            {
                "composite/0001.png",
                "composite/0002.png",
                "composite/0003.png",
            },
        )


    def test_single_download_does_not_report_empty_listing_as_complete(self):
        def empty_listing(_dest_dir, state, **_kwargs):
            state.last_visible_count = 0
            return True

        with (
            patch.object(self.worker, "_existing_relative_files", return_value=set()),
            patch.object(self.worker, "_rclone_copy_output", side_effect=empty_listing),
        ):
            self.worker.single_downloader("/tmp/download")

        self.worker.logger.transfer_complete.assert_not_called()
        self.worker.logger.warning.assert_called_once_with(
            "No frames ready yet. Run again later to download."
        )


class _FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


class AutoDownloaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load_worker_module()

    def setUp(self):
        self.worker.base_cmd = ["rclone", "--s3-access-key-id", "AKIA"]
        self.worker.bucket = "render-test"
        self.worker.job_id = "job-1"
        self.worker.logger = MagicMock()
        self.worker.run_rclone = MagicMock()
        self.worker._SKIPPED_OUTPUTS_WARNED = False

    def _clock_patches(self, clock):
        return (
            patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic),
            patch.object(self.worker.time, "sleep", side_effect=clock.sleep),
        )


    def test_batches_only_new_keys_and_settles_after_late_terminal_visibility(self):
        clock = _FakeClock()
        batches = []
        statuses = iter(
            [
                ("running", 1, 3),
                ("running", 2, 3),
                ("finished", 3, 3),
            ]
        )
        listings = iter(
            [
                (["composite/0001.png"], []),
                (["composite/0001.png", "composite/0002.png"], []),
                (
                    [
                        "composite/0001.png",
                        "composite/0002.png",
                        "composite/0003.png",
                    ],
                    [],
                ),
                (
                    [
                        "composite/0001.png",
                        "composite/0002.png",
                        "composite/0003.png",
                    ],
                    [],
                ),
            ]
        )

        def record_batch(files):
            batches.append(list(files))
            return f"/tmp/sulu-auto-files-{len(batches)}.txt"

        monotonic_patch, sleep_patch = self._clock_patches(clock)
        with (
            tempfile.TemporaryDirectory() as dest_dir,
            monotonic_patch,
            sleep_patch,
            patch.object(
                self.worker,
                "_fetch_job_details",
                side_effect=lambda: next(statuses),
            ) as fetch,
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                side_effect=lambda remote: next(listings),
            ) as list_files,
            patch.object(
                self.worker,
                "_write_files_from_list",
                side_effect=record_batch,
            ),
            patch.object(self.worker.os, "unlink"),
        ):
            self.worker.auto_downloader(
                dest_dir,
                poll_seconds=5,
                batch_frames=2,
                batch_seconds=60,
                refresh_seconds=60,
                terminal_stable_passes=1,
                terminal_settle_seconds=30,
            )

        self.assertEqual(
            batches,
            [
                ["composite/0001.png"],
                ["composite/0001.png", "composite/0002.png"],
                [
                    "composite/0001.png",
                    "composite/0002.png",
                    "composite/0003.png",
                ],
                [
                    "composite/0001.png",
                    "composite/0002.png",
                    "composite/0003.png",
                ],
            ],
        )
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(list_files.call_count, 4)
        self.assertEqual(self.worker.run_rclone.call_count, 4)
        self.worker.logger.success.assert_called_once_with("3 frames downloaded")


if __name__ == "__main__":
    unittest.main()
