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


# ─── Worker bootstrap fakes ───────────────────────────────────────────────


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


# ─── Fake requests session helpers ────────────────────────────────────────


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


# ─── Tests ─────────────────────────────────────────────────────────────────


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

    # ── The NEW backend shape: structured placeholder for missing jobs ──

    def test_missing_job_placeholder_returns_unknown_with_zeros(self):
        """The backend fix returns
        `{"status":"success","body":{"status":"unknown","tasks":{zeros},
        "total_tasks":0,"missing":true}}` for jobs not yet in
        Database.jobs. The worker must return that shape unchanged AND
        log nothing — this is the steady state during the sync window
        and on every poll after a job has aged out, so any log noise
        compounds into the spam the user reported."""
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

    # ── The OLD (broken) shape we still need to tolerate ──

    def test_bare_null_body_falls_back_silently(self):
        """If an old backend version still returns `null` for missing
        jobs, `resp.json()` returns the Python value `None`. The worker
        used to crash here with `'NoneType' object has no attribute
        'get'`. After the defensive fix it falls back to the handoff
        snapshot and logs at most one warning."""
        self.worker.session = _make_session(_FakeResponse(body_obj=None))
        result = self.worker._fetch_job_details()
        self.assertEqual(result, ("queued", 0, 5))
        # We don't insist on zero warnings here — older bare-null
        # responses look like a server bug and one warning is fine —
        # but it must not be the crash message AND it must not spam.
        for w in self.fake_logger.warnings:
            self.assertNotIn("NoneType", w)
        self.assertLessEqual(len(self.fake_logger.warnings), 1)

    def test_wrapped_null_body_falls_back_silently(self):
        """The pre-fix backend response `{"status":"success","body":null}`.
        Old worker called `.get` on None and crashed. Must now fall back
        cleanly."""
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

    # ── Real running-job response shape ──

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

    # ── Network-level failures ──

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

    # ── Configuration edge cases ──

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


if __name__ == "__main__":
    unittest.main()
