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


class _FakeResponse:
    def __init__(self, status_code=200, body_text="", body_obj=None, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._body_text = body_text
        self._body_obj = body_obj

    def json(self):
        if self._body_obj is not None:
            return self._body_obj
        if not self._body_text:
            raise ValueError("Expecting value")
        return json.loads(self._body_text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _make_session(response: _FakeResponse):
    sess = MagicMock()
    sess.get = MagicMock(return_value=response)
    return sess


# Tests


class IntegratedDownloadRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load_worker_module()

    def test_integrated_run_preserves_terminal_and_uses_auto_mode(self):
        global_names = (
            "data",
            "session",
            "job_id",
            "job_name",
            "download_path",
            "download_type",
            "sarfis_url",
            "sarfis_token",
            "logger",
            "run_rclone",
            "ensure_rclone",
            "open_folder",
            "fetch_project_storage",
            "_build_base",
            "requests_retry_session",
            "CLOUDFLARE_R2_DOMAIN",
            "TerminalKeyReader",
            "_download_actions",
        )
        previous_globals = {
            name: getattr(self.worker, name, None) for name in global_names
        }
        self.addCleanup(
            lambda: [
                setattr(self.worker, name, value)
                for name, value in previous_globals.items()
            ]
        )

        fake_logger = MagicMock()
        fake_logger.logo_end.return_value = "c"
        clear_console = MagicMock()
        worker_session = MagicMock()
        storage_record = {
            "bucket_name": "render-test",
            "access_key_id": "key",
            "secret_access_key": "secret",
        }
        mods = {
            "run_rclone": MagicMock(),
            "ensure_rclone": MagicMock(return_value="/tmp/rclone"),
            "NOT_FOUND_MARKERS": (),
            "AUTH_MARKERS": (),
            "open_folder": MagicMock(),
            "fetch_project_storage": MagicMock(
                return_value={"items": [storage_record]}
            ),
            "_build_base": MagicMock(return_value=["rclone"]),
            "requests_retry_session": MagicMock(return_value=worker_session),
            "CLOUDFLARE_R2_DOMAIN": "example.r2.cloudflarestorage.com",
            "DownloadLogger": MagicMock(return_value=fake_logger),
            "TerminalKeyReader": MagicMock(
                return_value=MagicMock(
                    start=MagicMock(return_value=False),
                    stop=MagicMock(),
                )
            ),
            "clear_console": clear_console,
            "run_preflight_checks": MagicMock(return_value=(True, [])),
        }
        handoff = {
            "addon_dir": str(REPO_ROOT),
            "job_id": "job-live-download",
            "job_name": "Nebula Passage",
            "download_path": tempfile.mkdtemp(prefix="sulu_integrated_dl_"),
            "download_type": "auto",
            "pocketbase_url": "https://api.invalid",
            "user_token": "redacted",
            "project": {"id": "project-1"},
            "sarfis_url": "https://farm.invalid/project-1",
            "sarfis_token": "redacted",
        }

        with (
            patch.object(self.worker, "_bootstrap_addon_modules", return_value=mods),
            patch.object(self.worker, "_run_selected_downloader") as downloader,
        ):
            destination = self.worker.run_download(
                handoff,
                clear_console=False,
                integrated=True,
            )

        clear_console.assert_not_called()
        fake_logger.logo_start.assert_called_once_with(
            job_name="Nebula Passage",
            dest_dir=destination,
            show_logo=False,
        )
        downloader.assert_called_once_with(
            destination,
            "auto",
            "https://farm.invalid/project-1",
            "redacted",
        )


class DownloadActionControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load_worker_module()

    class _Reader:
        def __init__(self, keys):
            self.keys = list(keys)
            self.stopped = False

        def start(self):
            return True

        def drain(self):
            keys, self.keys = self.keys, []
            return keys

        def stop(self):
            self.stopped = True

    def setUp(self):
        self.original_logger = getattr(self.worker, "logger", None)
        self.original_open_folder = getattr(self.worker, "open_folder", None)
        self.worker.logger = MagicMock()
        self.worker.open_folder = MagicMock()
        self.addCleanup(setattr, self.worker, "logger", self.original_logger)
        self.addCleanup(
            setattr,
            self.worker,
            "open_folder",
            self.original_open_folder,
        )

    def test_shortcuts_open_job_reports_folder_and_help(self):
        reader = self._Reader(["j", "r", "o", "?"])
        controller = self.worker._DownloadActionController(
            reader,
            dest_dir="/tmp/renders/Nebula Passage",
            job_url="https://superlumin.al/jobs/123",
            report_path="/tmp/reports",
        )

        with patch.object(self.worker.webbrowser, "open") as open_web:
            self.assertTrue(controller.start())
            controller.poll()

        open_web.assert_called_once_with("https://superlumin.al/jobs/123")
        self.worker.open_folder.assert_any_call(
            "/tmp/reports",
            logger_instance=self.worker.logger,
        )
        self.worker.open_folder.assert_any_call(
            "/tmp/renders/Nebula Passage",
            logger_instance=self.worker.logger,
        )
        self.worker.logger.download_actions.assert_called_once_with(
            have_job=True,
            have_report=True,
        )

    def test_cancel_shortcut_raises_resumable_cancellation(self):
        controller = self.worker._DownloadActionController(
            self._Reader(["c"]),
            dest_dir="/tmp/renders",
        )
        controller.start()

        with self.assertRaises(self.worker._DownloadCancelled):
            controller.poll()

        self.worker.logger.action_feedback.assert_called_once_with(
            "Stopping download safely…"
        )

    def test_manual_download_derives_job_page_from_project(self):
        url = self.worker._job_page_url(
            {
                "job_id": "job-123",
                "project": {"sqid": "project-sqid"},
            }
        )

        self.assertEqual(
            url,
            "https://superlumin.al/p/project-sqid/farm/jobs/job-123",
        )


class FetchJobDetailsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load_worker_module()

    def setUp(self):
        # Reset the dedupe set between tests so warning expectations are isolated.
        self.worker._JOB_DETAILS_WARNED.clear()
        # Fresh fake logger per test
        from unittest.mock import MagicMock
        self.fake_logger = MagicMock()
        self.fake_logger.warnings = []
        self.fake_logger.warning = lambda msg: self.fake_logger.warnings.append(msg)
        self.worker.logger = self.fake_logger
        self.worker.sarfis_url = "http://fake-sarfis"
        self.worker.sarfis_token = "fake-token"
        self.worker.job_id = "test-job-id"
        # The handoff snapshot used by `_handoff_job_details` — `data` is a
        # module global the worker reads in `_handoff_job_details`. Restore
        # it to a known shape every test.
        self.worker.data = {
            "job": {
                "status": "queued",
                "tasks": {
                    "queued": 5,
                    "running": 0,
                    "finished": 0,
                    "error": 0,
                    "paused": 0,
                },
                "total_tasks": 5,
            }
        }

    # Structured placeholder for missing jobs

    def test_missing_job_placeholder_returns_unknown_with_zeros(self):
        """The backend returns
        `{"status":"success","body":{"status":"unknown","tasks":{zeros},
        "total_tasks":0,"missing":true}}` for jobs not yet in
        Database.jobs. The worker must return that shape unchanged AND
        log nothing. This is the steady state during the sync window
        and on every poll after a job has aged out."""
        body = {
            "status": "unknown",
            "tasks": {"queued": 0, "running": 0, "finished": 0, "error": 0, "paused": 0},
            "total_tasks": 0,
            "missing": True,
        }
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "success", "body": body})
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("unknown", 0, 0))
        self.assertEqual(self.fake_logger.warnings, [])

    def test_missing_job_placeholder_repeated_polls_no_log_spam(self):
        """Auto-download polls every 5 s. The placeholder is the normal
        case during the sync-pending window, so 60 polls in a row must
        not produce 60 warning lines."""
        body = {
            "status": "unknown",
            "tasks": {"queued": 0, "running": 0, "finished": 0, "error": 0, "paused": 0},
            "total_tasks": 0,
            "missing": True,
        }
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "success", "body": body})
        )
        for _ in range(60):
            self.worker._fetch_job_details()
        self.assertEqual(self.fake_logger.warnings, [])

    # Bare null response tolerated for compatibility

    def test_bare_null_body_falls_back_silently(self):
        """A `null` missing-job body becomes Python `None`; the worker
        falls back to the handoff snapshot and logs at most one warning."""
        self.worker.session = _make_session(_FakeResponse(body_obj=None))
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))
        # Bare null responses may log one warning but must not repeat it.
        for w in self.fake_logger.warnings:
            self.assertNotIn("NoneType", w)
        self.assertLessEqual(len(self.fake_logger.warnings), 1)

    def test_wrapped_null_body_falls_back_silently(self):
        """A wrapped null body falls back to the handoff snapshot."""
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "success", "body": None})
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))
        for w in self.fake_logger.warnings:
            self.assertNotIn("NoneType", w)

    def test_empty_dict_body_falls_back(self):
        """`{"status":"access_denied","body":{}}` — empty dict is falsy."""
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "access_denied", "body": {}})
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))

    # Running-job response shape

    def test_running_job_returns_live_counts(self):
        body = {
            "status": "running",
            "tasks": {"queued": 3, "running": 1, "finished": 12, "error": 0, "paused": 0},
            "total_tasks": 16,
        }
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "success", "body": body})
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("running", 12, 16))
        self.assertEqual(self.fake_logger.warnings, [])

    def test_finished_job_returns_terminal_status(self):
        body = {
            "status": "finished",
            "tasks": {"queued": 0, "running": 0, "finished": 100, "error": 0, "paused": 0},
            "total_tasks": 100,
        }
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "success", "body": body})
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("finished", 100, 100))

    # Network-level failures

    def test_non_200_falls_back(self):
        self.worker.session = _make_session(
            _FakeResponse(status_code=502, body_text="Bad Gateway", content_type="text/plain")
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))
        self.assertEqual(len(self.fake_logger.warnings), 1)
        self.assertIn("502", self.fake_logger.warnings[0])

    def test_repeated_502_doesnt_spam(self):
        self.worker.session = _make_session(
            _FakeResponse(status_code=502, body_text="Bad Gateway", content_type="text/plain")
        )
        for _ in range(30):
            self.worker._fetch_job_details()
        # Dedupe collapses identical warnings.
        self.assertEqual(len(self.fake_logger.warnings), 1)

    def test_network_exception_falls_back(self):
        sess = MagicMock()
        sess.get = MagicMock(side_effect=ConnectionError("connection refused"))
        self.worker.session = sess
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))

    def test_invalid_json_body_falls_back(self):
        self.worker.session = _make_session(
            _FakeResponse(body_text="not actually json", content_type="application/json")
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))

    def test_non_json_content_type_falls_back(self):
        self.worker.session = _make_session(
            _FakeResponse(body_text="<html>error</html>", content_type="text/html")
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))

    # Configuration edge cases

    def test_no_sarfis_url_falls_back_without_network(self):
        self.worker.sarfis_url = None
        self.worker.session = MagicMock()
        self.worker.session.get = MagicMock(side_effect=AssertionError("should not be called"))
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))

    def test_tasks_field_is_null_in_body(self):
        """Edge case: body has `tasks: null` instead of missing the key
        entirely. The worker handled this via `or {}` but let's lock
        it in."""
        body = {
            "status": "running",
            "tasks": None,
            "total_tasks": 10,
        }
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "success", "body": body})
        )
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("running", 0, 10))

    def test_recovery_clears_dedupe_set(self):
        """A transient 502 followed by a real response shouldn't
        permanently silence future warnings of the same kind."""
        # First, fail with 502 — logs once.
        self.worker.session = _make_session(
            _FakeResponse(status_code=502, body_text="x", content_type="text/plain")
        )
        self.worker._fetch_job_details()
        self.assertEqual(len(self.fake_logger.warnings), 1)
        # Recover with a real response — should clear the dedupe set.
        body = {
            "status": "running",
            "tasks": {"queued": 1, "running": 0, "finished": 0, "error": 0, "paused": 0},
            "total_tasks": 1,
        }
        self.worker.session = _make_session(
            _FakeResponse(body_obj={"status": "success", "body": body})
        )
        self.worker._fetch_job_details()
        # Fail again — should log a fresh warning (dedupe cleared).
        self.worker.session = _make_session(
            _FakeResponse(status_code=502, body_text="x", content_type="text/plain")
        )
        self.worker._fetch_job_details()
        self.assertEqual(len(self.fake_logger.warnings), 2)


class StorageCredentialsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load_worker_module()

    def setUp(self):
        self.worker.data = {
            "user_token": "user-token",
            "pocketbase_url": "https://api.example.test",
            "project": {"id": "project-1"},
        }

    def test_fetch_storage_credentials_can_force_backend_renewal(self):
        response = _FakeResponse(
            body_obj={
                "items": [
                    {
                        "bucket_name": "render-project-1",
                        "access_key_id": "AK",
                        "secret_access_key": "SK",
                        "session_token": "TOKEN",
                    }
                ]
            }
        )
        self.worker.session = _make_session(response)

        rec, bucket = self.worker._fetch_storage_credentials(force_renew=True)

        self.assertEqual(bucket, "render-project-1")
        self.assertEqual(rec["access_key_id"], "AK")
        params = self.worker.session.get.call_args.kwargs["params"]
        self.assertEqual(params["force_renew"], "1")


class HandoffCleanupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = _load_worker_module()

    def test_malformed_handoff_is_still_removed(self):
        with tempfile.NamedTemporaryFile(
            prefix="sulu_bad_download_handoff_",
            suffix=".json",
            delete=False,
        ) as handoff:
            handoff_path = Path(handoff.name)
        handoff_path.write_text("{", encoding="utf-8")

        with self.assertRaises(json.JSONDecodeError):
            self.worker._load_handoff_from_argv(
                ["download_worker.py", str(handoff_path)]
            )

        self.assertFalse(handoff_path.exists())


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

    def test_filter_downloadable_output_files_skips_windows_impossible_paths(self):
        files, skipped = self.worker._filter_downloadable_output_files(
            [
                "composite/0001.png",
                "outputs/pass/Beauty:RGBA/0001.png",
                "outputs/bad-name/",
                "outputs/CON/0001.png",
                "outputs/aux.exr",
                "outputs/" + ("x" * 241) + ".png",
            ]
        )

        self.assertEqual(
            files,
            [
                "composite/0001.png",
                "outputs/pass/Beauty:RGBA/0001.png",
            ],
        )
        self.assertEqual([path for path, _ in skipped], [
            "outputs/bad-name/",
            "outputs/CON/0001.png",
            "outputs/aux.exr",
            "outputs/" + ("x" * 241) + ".png",
        ])

    def test_rclone_list_skips_windows_impossible_paths(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout=(
                "composite/0001.png\n"
                "outputs/pass/0001.png\n"
                "outputs/bad-name/\n"
                "outputs/NUL/0001.png\n"
            ),
        )

        with patch.object(self.worker.subprocess, "run", return_value=completed) as run:
            files, skipped = self.worker._rclone_list_output_files(
                ":s3:render-test/job-1/output/"
            )

        self.assertEqual(files, ["composite/0001.png", "outputs/pass/0001.png"])
        self.assertEqual([path for path, _ in skipped], ["outputs/bad-name/", "outputs/NUL/0001.png"])
        cmd = run.call_args.args[0]
        self.assertIn("lsf", cmd)
        self.assertIn("--recursive", cmd)
        self.assertIn("--files-only", cmd)
        self.assertIn("thumbnails/**", cmd)

    def test_run_output_copy_uses_files_from_list(self):
        self.worker.run_rclone = MagicMock()

        with (
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                return_value=(["composite/0001.png"], [("outputs/bad-name/", "name ends with '/'")]),
            ),
            patch.object(
                self.worker,
                "_write_files_from_list",
                return_value="/tmp/sulu-files.txt",
            ),
            patch.object(self.worker.os, "unlink") as unlink,
        ):
            self.worker._run_output_copy("/tmp/download")

        self.worker.run_rclone.assert_called_once()
        args = self.worker.run_rclone.call_args.args
        self.assertEqual(args[1], "copy")
        self.assertEqual(args[2], ":s3:render-test/job-1/output/")
        self.assertEqual(args[3], "/tmp/download/")
        rclone_args = args[4]
        self.assertIn("--files-from-raw", rclone_args)
        self.assertIn("/tmp/sulu-files.txt", rclone_args)
        self.assertIn("--local-encoding", rclone_args)
        self.assertIn(self.worker._WINDOWS_SAFE_LOCAL_ENCODING, rclone_args)
        self.assertNotIn("thumbnails/**", rclone_args)
        self.worker.logger.warning.assert_called_once()
        unlink.assert_called_once_with("/tmp/sulu-files.txt")

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

    def test_reconciliation_rechecks_known_path_and_allows_replacement(self):
        self.worker.run_rclone = MagicMock(return_value={"transfers": 1})
        state = self.worker._OutputCopyState({"composite/0001.png"})
        batches = []

        with (
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                return_value=(["composite/0001.png"], []),
            ),
            patch.object(
                self.worker,
                "_write_files_from_list",
                side_effect=lambda files: batches.append(list(files))
                or "/tmp/sulu-reconcile-files.txt",
            ),
            patch.object(self.worker.os, "unlink"),
        ):
            changed = self.worker._run_output_copy(
                "/tmp/download",
                state,
                reconcile_existing=True,
            )

        self.assertEqual(changed, 1)
        self.assertEqual(batches, [["composite/0001.png"]])
        rclone_args = self.worker.run_rclone.call_args.args[4]
        self.assertNotIn("--size-only", rclone_args)

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

    def test_single_download_reconciles_existing_outputs(self):
        def visible_listing(_dest_dir, state, **kwargs):
            self.assertTrue(kwargs["reconcile_existing"])
            self.assertEqual(state.downloaded_files, {"composite/0001.png"})
            state.last_visible_count = 1
            return True

        with (
            patch.object(
                self.worker,
                "_existing_relative_files",
                return_value={"composite/0001.png"},
            ),
            patch.object(self.worker, "_rclone_copy_output", side_effect=visible_listing),
        ):
            self.worker.single_downloader("/tmp/download")

        self.worker.logger.resume_info.assert_called_once_with(1)
        self.worker.logger.transfer_complete.assert_called_once_with("Downloaded")


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

    def test_auto_dispatch_does_not_bypass_terminal_settling(self):
        self.worker.data = {
            "job": {
                "status": "finished",
                "tasks": {"finished": 1},
                "total_tasks": 1,
            }
        }
        with (
            patch.object(self.worker, "_fetch_job_details") as fetch_details,
            patch.object(self.worker, "single_downloader") as single,
            patch.object(self.worker, "auto_downloader") as automatic,
        ):
            self.worker._run_selected_downloader(
                "/tmp/download",
                "auto",
                "https://farm.example",
                "token",
            )

        fetch_details.assert_not_called()
        single.assert_not_called()
        automatic.assert_called_once_with(
            "/tmp/download",
            poll_seconds=self.worker._AUTO_POLL_SECONDS,
        )

    def test_polling_uses_deadlines_instead_of_sleeping_after_work(self):
        clock = _FakeClock()
        statuses = iter(
            [
                ("running", 0, 1),
                ("finished", 0, 1),
            ]
        )

        def fetch_with_two_seconds_of_work():
            clock.advance(2.0)
            return next(statuses)

        monotonic_patch, sleep_patch = self._clock_patches(clock)
        with (
            tempfile.TemporaryDirectory() as dest_dir,
            monotonic_patch,
            sleep_patch,
            patch.object(
                self.worker,
                "_fetch_job_details",
                side_effect=fetch_with_two_seconds_of_work,
            ),
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                return_value=([], []),
            ),
        ):
            self.worker.auto_downloader(
                dest_dir,
                poll_seconds=5,
                terminal_stable_passes=1,
            )

        self.assertEqual(clock.sleeps, [3.0, 3.0, 2.0])

    def test_poll_deadline_skips_only_deadlines_that_are_already_past(self):
        self.assertEqual(self.worker._next_poll_deadline(0.0, 5.0, 10.0), 10.0)
        self.assertEqual(self.worker._next_poll_deadline(0.0, 5.0, 10.1), 15.0)

    def test_default_batching_does_not_delay_a_single_finished_frame(self):
        self.assertEqual(self.worker._AUTO_BATCH_FRAMES, 1)
        self.assertLessEqual(self.worker._AUTO_BATCH_SECONDS, 5.0)
        self.assertEqual(self.worker._AUTO_POLL_SECONDS, 1)

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

    def test_multiple_outputs_for_one_frame_do_not_suppress_next_poll(self):
        clock = _FakeClock()
        batches = []
        statuses = iter(
            [
                ("running", 2, 3),
                ("running", 2, 3),
                ("finished", 3, 3),
            ]
        )
        listings = iter(
            [
                (["beauty/0001.png", "normal/0001.png"], []),
                (
                    [
                        "beauty/0001.png",
                        "normal/0001.png",
                        "beauty/0002.png",
                        "normal/0002.png",
                    ],
                    [],
                ),
                (
                    [
                        "beauty/0001.png",
                        "normal/0001.png",
                        "beauty/0002.png",
                        "normal/0002.png",
                        "beauty/0003.png",
                        "normal/0003.png",
                    ],
                    [],
                ),
                (
                    [
                        "beauty/0001.png",
                        "normal/0001.png",
                        "beauty/0002.png",
                        "normal/0002.png",
                        "beauty/0003.png",
                        "normal/0003.png",
                    ],
                    [],
                ),
            ]
        )

        monotonic_patch, sleep_patch = self._clock_patches(clock)
        with (
            tempfile.TemporaryDirectory() as dest_dir,
            monotonic_patch,
            sleep_patch,
            patch.object(
                self.worker,
                "_fetch_job_details",
                side_effect=lambda: next(statuses),
            ),
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                side_effect=lambda _remote: next(listings),
            ) as list_files,
            patch.object(
                self.worker,
                "_write_files_from_list",
                side_effect=lambda files: batches.append(list(files))
                or f"/tmp/sulu-multi-output-{len(batches)}.txt",
            ),
            patch.object(self.worker.os, "unlink"),
        ):
            self.worker.auto_downloader(
                dest_dir,
                poll_seconds=2,
                batch_frames=1,
                terminal_stable_passes=1,
            )

        self.assertEqual(list_files.call_count, 4)
        self.assertEqual(
            batches[1],
            ["beauty/0002.png", "normal/0002.png"],
        )
        self.worker.logger.success.assert_called_once_with("3 frames downloaded")

    def test_resume_reconciles_existing_files_only_at_terminal_boundary(self):
        clock = _FakeClock()
        batches = []

        def record_batch(files):
            batches.append(list(files))
            return "/tmp/sulu-resume-files.txt"

        monotonic_patch, sleep_patch = self._clock_patches(clock)
        with tempfile.TemporaryDirectory() as dest_dir:
            existing = Path(dest_dir) / "composite" / "0001.png"
            existing.parent.mkdir()
            existing.write_bytes(b"complete")

            with (
                monotonic_patch,
                sleep_patch,
                patch.object(
                    self.worker,
                    "_fetch_job_details",
                    return_value=("finished", 2, 2),
                ),
                patch.object(
                    self.worker,
                    "_rclone_list_output_files",
                    side_effect=[
                        (
                            ["composite/0001.png", "composite/0002.png"],
                            [],
                        ),
                        (
                            ["composite/0001.png", "composite/0002.png"],
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
                self.worker.auto_downloader(
                    dest_dir,
                    poll_seconds=5,
                    terminal_stable_passes=1,
                )

        self.assertEqual(
            batches,
            [
                ["composite/0001.png", "composite/0002.png"],
                ["composite/0001.png", "composite/0002.png"],
            ],
        )
        self.worker.logger.resume_info.assert_called_once_with(1)
        self.worker.logger.success.assert_called_once_with("2 frames downloaded")

    def test_terminal_quiet_window_survives_empty_gap_before_late_key(self):
        clock = _FakeClock()
        batches = []
        listings = iter(
            [
                (["composite/0001.png"], []),
                (["composite/0001.png"], []),
                (["composite/0001.png"], []),
                (["composite/0001.png", "composite/0002.png"], []),
                (["composite/0001.png", "composite/0002.png"], []),
            ]
        )

        monotonic_patch, sleep_patch = self._clock_patches(clock)
        with (
            tempfile.TemporaryDirectory() as dest_dir,
            monotonic_patch,
            sleep_patch,
            patch.object(
                self.worker,
                "_fetch_job_details",
                return_value=("finished", 2, 2),
            ),
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                side_effect=lambda _remote: next(listings),
            ) as list_files,
            patch.object(
                self.worker,
                "_write_files_from_list",
                side_effect=lambda files: batches.append(list(files))
                or f"/tmp/sulu-gap-{len(batches)}.txt",
            ),
            patch.object(self.worker.os, "unlink"),
        ):
            self.worker.auto_downloader(
                dest_dir,
                poll_seconds=2,
                terminal_stable_passes=1,
                terminal_settle_seconds=30,
                terminal_quiet_seconds=10,
            )

        self.assertEqual(list_files.call_count, 5)
        self.assertIn("composite/0002.png", batches[-1])
        self.worker.logger.success.assert_called_once_with("2 frames downloaded")

    def test_terminal_visibility_wait_is_bounded(self):
        clock = _FakeClock()
        monotonic_patch, sleep_patch = self._clock_patches(clock)
        with (
            tempfile.TemporaryDirectory() as dest_dir,
            monotonic_patch,
            sleep_patch,
            patch.object(
                self.worker,
                "_fetch_job_details",
                return_value=("finished", 1, 1),
            ),
            patch.object(
                self.worker,
                "_rclone_list_output_files",
                return_value=([], []),
            ) as list_files,
        ):
            self.worker.auto_downloader(
                dest_dir,
                poll_seconds=5,
                terminal_stable_passes=2,
                terminal_settle_seconds=12,
            )

        self.assertEqual(clock.sleeps, [5.0, 5.0, 2.0])
        self.assertEqual(list_files.call_count, 4)
        warning_messages = [call.args[0] for call in self.worker.logger.warning.call_args_list]
        self.assertTrue(
            any("did not stabilize within 12s" in message for message in warning_messages)
        )
        self.worker.logger.success.assert_not_called()

    def test_finished_paused_and_error_terminal_messages(self):
        expected = {
            "finished": ("success", "0 frames downloaded"),
            "paused": ("warning", "Job paused. 0 frames saved."),
            "error": ("warning", "Job stopped with errors. 0 frames saved."),
        }

        for status, (method, message) in expected.items():
            with self.subTest(status=status):
                self.worker.logger = MagicMock()
                clock = _FakeClock()
                monotonic_patch, sleep_patch = self._clock_patches(clock)
                with (
                    tempfile.TemporaryDirectory() as dest_dir,
                    monotonic_patch,
                    sleep_patch,
                    patch.object(
                        self.worker,
                        "_fetch_job_details",
                        return_value=(status, 0, 0),
                    ),
                    patch.object(
                        self.worker,
                        "_rclone_list_output_files",
                        return_value=([], []),
                    ),
                ):
                    self.worker.auto_downloader(
                        dest_dir,
                        poll_seconds=5,
                        terminal_stable_passes=1,
                    )

                getattr(self.worker.logger, method).assert_called_with(message)


if __name__ == "__main__":
    unittest.main()
