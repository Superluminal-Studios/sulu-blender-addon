"""
Reliability hardening regression tests.

Covers:
- Auth error taxonomy mapping
- request_utils network-only request path (no bpy prefs mutation)
- download_worker import safety (no argv side effects)
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

import requests

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


class _DummyResponse:
    def __init__(self, status_code: int, text: str = "{}", payload=None, reason: str = ""):
        self.status_code = status_code
        self.text = text
        self.reason = reason
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class TestPocketbaseAuthTaxonomy(unittest.TestCase):
    def _load_auth_module(self):
        pkg_name = "sulu_auth_test_pkg"
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_addon_dir)]
        sys.modules[pkg_name] = pkg

        constants_mod = types.ModuleType(f"{pkg_name}.constants")
        constants_mod.POCKETBASE_URL = "https://example.invalid"
        sys.modules[f"{pkg_name}.constants"] = constants_mod

        class _DummySession:
            def __init__(self):
                self.request_fn = None
                self.post_fn = None

            def request(self, method, url, **kwargs):
                return self.request_fn(method, url, **kwargs)

            def post(self, url, **kwargs):
                return self.post_fn(url, **kwargs)

        class _DummyStorage:
            session = _DummySession()
            timeout = 5
            clear_called = False
            data = {
                "user_token": "tok",
                "user_token_time": 0,
                "org_id": "org-1",
                "user_key": "ukey-1",
            }

            @classmethod
            def clear(cls):
                cls.clear_called = True
                cls.data["user_token"] = ""

            @classmethod
            def save(cls):
                pass

        storage_mod = types.ModuleType(f"{pkg_name}.storage")
        storage_mod.Storage = _DummyStorage
        sys.modules[f"{pkg_name}.storage"] = storage_mod

        mod = _load_module_directly(
            f"{pkg_name}.pocketbase_auth",
            _addon_dir / "pocketbase_auth.py",
        )
        return mod, _DummyStorage

    def test_404_maps_to_resource_not_found(self):
        mod, storage = self._load_auth_module()
        storage.session.request_fn = (
            lambda method, url, **kwargs: _DummyResponse(404, reason="Not Found")
        )
        storage.session.post_fn = (
            lambda url, **kwargs: _DummyResponse(200, payload={"token": "tok"})
        )

        with self.assertRaises(mod.ResourceNotFound):
            mod.authorized_request("GET", "https://example.invalid/missing")

    def test_403_maps_to_authorization_error(self):
        mod, storage = self._load_auth_module()
        storage.session.request_fn = (
            lambda method, url, **kwargs: _DummyResponse(403, reason="Forbidden")
        )
        storage.session.post_fn = (
            lambda url, **kwargs: _DummyResponse(200, payload={"token": "tok"})
        )

        with self.assertRaises(mod.AuthorizationError):
            mod.authorized_request("GET", "https://example.invalid/forbidden")

    def test_500_maps_to_upstream_service_error(self):
        mod, storage = self._load_auth_module()
        storage.session.request_fn = (
            lambda method, url, **kwargs: _DummyResponse(500, reason="Server Error")
        )
        storage.session.post_fn = (
            lambda url, **kwargs: _DummyResponse(200, payload={"token": "tok"})
        )

        with self.assertRaises(mod.UpstreamServiceError):
            mod.authorized_request("GET", "https://example.invalid/fail")

    def test_timeout_maps_to_transport_error(self):
        mod, storage = self._load_auth_module()

        def _raise_timeout(method, url, **kwargs):
            raise requests.Timeout("timed out")

        storage.session.request_fn = _raise_timeout
        storage.session.post_fn = (
            lambda url, **kwargs: _DummyResponse(200, payload={"token": "tok"})
        )

        with self.assertRaises(mod.TransportError):
            mod.authorized_request("GET", "https://example.invalid/timeout")

    def test_401_clears_storage_and_raises_not_authenticated(self):
        mod, storage = self._load_auth_module()
        storage.session.request_fn = (
            lambda method, url, **kwargs: _DummyResponse(401, reason="Unauthorized")
        )
        storage.session.post_fn = (
            lambda url, **kwargs: _DummyResponse(200, payload={"token": "tok"})
        )

        with self.assertRaises(mod.NotAuthenticated):
            mod.authorized_request("GET", "https://example.invalid/private")
        self.assertTrue(storage.clear_called)


class TestRequestUtilsThreadSafety(unittest.TestCase):
    def _load_request_utils(self):
        pkg_name = "sulu_request_utils_pkg"
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_addon_dir)]
        sys.modules[pkg_name] = pkg

        utils_pkg = types.ModuleType(f"{pkg_name}.utils")
        utils_pkg.__path__ = [str(_addon_dir / "utils")]
        sys.modules[f"{pkg_name}.utils"] = utils_pkg

        constants_mod = types.ModuleType(f"{pkg_name}.constants")
        constants_mod.POCKETBASE_URL = "https://example.invalid"
        sys.modules[f"{pkg_name}.constants"] = constants_mod

        class _DummyStorage:
            enable_job_thread = False
            data = {"jobs": {"old": {"id": "old"}}}
            panel_data = {
                "last_jobs_refresh_at": 0.0,
                "jobs_refresh_error": "",
                "jobs_refresh_project_id": "",
            }

        storage_mod = types.ModuleType(f"{pkg_name}.storage")
        storage_mod.Storage = _DummyStorage
        sys.modules[f"{pkg_name}.storage"] = storage_mod

        calls = {"get_prefs_called": 0}

        prefs_mod = types.ModuleType(f"{pkg_name}.utils.prefs")

        def _get_prefs():
            calls["get_prefs_called"] += 1
            raise AssertionError("request_jobs must not touch bpy prefs")

        prefs_mod.get_prefs = _get_prefs
        sys.modules[f"{pkg_name}.utils.prefs"] = prefs_mod

        worker_utils_mod = types.ModuleType(f"{pkg_name}.utils.worker_utils")
        worker_utils_mod.requests_retry_session = lambda: object()
        sys.modules[f"{pkg_name}.utils.worker_utils"] = worker_utils_mod

        auth_mod = types.ModuleType(f"{pkg_name}.pocketbase_auth")

        def _authorized_request(method, url, **kwargs):
            return _DummyResponse(
                200,
                text='{"body":{"job-a":{"id":"job-a"}}}',
                payload={"body": {"job-a": {"id": "job-a"}}},
            )

        auth_mod.authorized_request = _authorized_request
        sys.modules[f"{pkg_name}.pocketbase_auth"] = auth_mod

        # Minimal bpy shim for timer registration/redraw calls.
        bpy_mod = types.ModuleType("bpy")
        bpy_mod.context = types.SimpleNamespace(
            window_manager=types.SimpleNamespace(windows=[])
        )
        bpy_mod.app = types.SimpleNamespace(
            timers=types.SimpleNamespace(register=lambda *a, **k: None)
        )
        sys.modules["bpy"] = bpy_mod

        mod = _load_module_directly(
            f"{pkg_name}.utils.request_utils",
            _addon_dir / "utils" / "request_utils.py",
        )
        return mod, _DummyStorage, calls

    def test_request_jobs_is_network_only(self):
        mod, storage, calls = self._load_request_utils()
        jobs = mod.request_jobs("org", "key", "project")

        self.assertEqual({"job-a": {"id": "job-a"}}, jobs)
        self.assertEqual(0, calls["get_prefs_called"])
        self.assertEqual({"old": {"id": "old"}}, storage.data["jobs"])

    def test_fetch_jobs_sync_updates_storage_and_refresh_state(self):
        mod, storage, calls = self._load_request_utils()
        jobs = mod.fetch_jobs("org", "key", "project", live_update=False)

        self.assertEqual({"job-a": {"id": "job-a"}}, jobs)
        self.assertEqual({"job-a": {"id": "job-a"}}, storage.data["jobs"])
        self.assertEqual("", storage.panel_data["jobs_refresh_error"])
        self.assertEqual("project", storage.panel_data["jobs_refresh_project_id"])


class TestDownloadWorkerImportSafety(unittest.TestCase):
    def test_import_has_no_argv_side_effects(self):
        # No sys.argv handoff provided here; import should still succeed.
        mod = _load_module_directly(
            "download_worker_import_test",
            _addon_dir / "transfers" / "download" / "download_worker.py",
        )
        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(callable(mod.main))
        self.assertFalse(hasattr(mod, "data"))

    def test_load_handoff_requires_path(self):
        mod = _load_module_directly(
            "download_worker_import_test_2",
            _addon_dir / "transfers" / "download" / "download_worker.py",
        )
        with self.assertRaises(RuntimeError):
            mod._load_handoff_from_argv(["download_worker.py"])

    def test_load_handoff_reads_json(self):
        mod = _load_module_directly(
            "download_worker_import_test_3",
            _addon_dir / "transfers" / "download" / "download_worker.py",
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write('{"addon_dir":"/tmp/addon","job_id":"abc"}')
            path = f.name
        try:
            data = mod._load_handoff_from_argv(["download_worker.py", path])
            self.assertEqual("abc", data["job_id"])
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
