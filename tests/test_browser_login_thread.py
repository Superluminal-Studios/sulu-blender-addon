from __future__ import annotations

import importlib.util
import sys
import types
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


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 428:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _SessionSequence:
    def __init__(self, steps):
        self._steps = list(steps)
        self.calls = 0

    def post(self, url, json=None, timeout=None):
        if self.calls >= len(self._steps):
            step = self._steps[-1]
        else:
            step = self._steps[self.calls]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


class TestBrowserLoginThread(unittest.TestCase):
    def _load_operators_module(self, *, session_steps=None, queue_returns=True):
        pkg_name = "sulu_ops_thread_pkg"

        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_addon_dir)]
        sys.modules[pkg_name] = pkg

        constants_mod = types.ModuleType(f"{pkg_name}.constants")
        constants_mod.POCKETBASE_URL = "https://example.invalid"
        sys.modules[f"{pkg_name}.constants"] = constants_mod

        auth_mod = types.ModuleType(f"{pkg_name}.pocketbase_auth")
        auth_mod.AuthorizationError = RuntimeError
        auth_mod.NotAuthenticated = RuntimeError
        auth_mod.ResourceNotFound = RuntimeError
        auth_mod.UpstreamServiceError = RuntimeError
        auth_mod.TransportError = RuntimeError
        sys.modules[f"{pkg_name}.pocketbase_auth"] = auth_mod

        utils_pkg = types.ModuleType(f"{pkg_name}.utils")
        utils_pkg.__path__ = [str(_addon_dir / "utils")]
        sys.modules[f"{pkg_name}.utils"] = utils_pkg

        queue_calls = []
        req_utils_mod = types.ModuleType(f"{pkg_name}.utils.request_utils")

        def _queue_login_bootstrap(token, *, addon_package=""):
            queue_calls.append((token, addon_package))
            return queue_returns

        req_utils_mod.get_render_queue_key = lambda org_id: "key-1"
        req_utils_mod.queue_login_bootstrap = _queue_login_bootstrap
        req_utils_mod.request_jobs_refresh = lambda **kwargs: True
        req_utils_mod.request_projects_refresh = lambda **kwargs: True
        req_utils_mod.set_refresh_context = lambda org_id, user_key, project_id: None
        req_utils_mod.stop_live_job_updates = lambda: None
        req_utils_mod.stop_refresh_service = lambda: None
        sys.modules[f"{pkg_name}.utils.request_utils"] = req_utils_mod

        log_mod = types.ModuleType(f"{pkg_name}.utils.logging")
        log_mod.report_exception = lambda op, exc, message, cleanup=None: {"CANCELLED"}
        sys.modules[f"{pkg_name}.utils.logging"] = log_mod

        if session_steps is None:
            session_steps = [_DummyResponse(428, {}), _DummyResponse(200, {"token": "tok-123"})]

        class _Storage:
            session = _SessionSequence(session_steps)
            timeout = 5
            panel_data = {"login_error": ""}
            data = {}

            @classmethod
            def clear(cls):
                pass

        storage_mod = types.ModuleType(f"{pkg_name}.storage")
        storage_mod.Storage = _Storage
        sys.modules[f"{pkg_name}.storage"] = storage_mod

        bpy_mod = types.ModuleType("bpy")
        bpy_mod.app = types.SimpleNamespace(version_string="4.4.0")
        bpy_mod.props = types.SimpleNamespace(
            StringProperty=lambda **kwargs: None,
        )
        bpy_mod.types = types.SimpleNamespace(
            Operator=object,
            WindowManager=object,
        )
        bpy_mod.context = types.SimpleNamespace(
            window_manager=types.SimpleNamespace(windows=[]),
        )
        sys.modules["bpy"] = bpy_mod

        mod = _load_module_directly(
            f"{pkg_name}.operators",
            _addon_dir / "operators.py",
        )
        return mod, queue_calls, _Storage

    def test_browser_login_thread_queues_bootstrap_only(self):
        mod, queue_calls, storage = self._load_operators_module()
        mod.first_login = lambda token: (_ for _ in ()).throw(
            AssertionError("first_login must not run in browser thread")
        )

        mod._browser_login_thread_v2("txn-1", "sulu_ops_thread_pkg")
        self.assertEqual([("tok-123", "sulu_ops_thread_pkg")], queue_calls)
        self.assertEqual("", storage.panel_data.get("login_error", ""))

    def test_browser_login_200_without_token_waits_before_retry(self):
        mod, queue_calls, storage = self._load_operators_module(
            session_steps=[
                _DummyResponse(200, {}),
                _DummyResponse(200, {"token": "tok-456"}),
            ]
        )
        sleep_calls = []
        orig_sleep = mod.time.sleep
        try:
            mod.time.sleep = lambda seconds: sleep_calls.append(seconds)
            mod._browser_login_thread_v2("txn-2", "sulu_ops_thread_pkg")
        finally:
            mod.time.sleep = orig_sleep

        self.assertEqual([("tok-456", "sulu_ops_thread_pkg")], queue_calls)
        self.assertIn(mod.BROWSER_LOGIN_NO_TOKEN_INTERVAL, sleep_calls)
        self.assertEqual("", storage.panel_data.get("login_error", ""))

    def test_browser_login_transient_error_uses_backoff_then_recovers(self):
        mod, queue_calls, storage = self._load_operators_module(
            session_steps=[
                RuntimeError("temporary failure"),
                _DummyResponse(200, {"token": "tok-789"}),
            ]
        )
        sleep_calls = []
        orig_sleep = mod.time.sleep
        try:
            mod.time.sleep = lambda seconds: sleep_calls.append(seconds)
            mod._browser_login_thread_v2("txn-3", "sulu_ops_thread_pkg")
        finally:
            mod.time.sleep = orig_sleep

        self.assertEqual([("tok-789", "sulu_ops_thread_pkg")], queue_calls)
        self.assertIn(mod.BROWSER_LOGIN_BACKOFF_INITIAL, sleep_calls)
        self.assertEqual("", storage.panel_data.get("login_error", ""))

    def test_browser_login_timeout_sets_user_facing_error(self):
        mod, queue_calls, storage = self._load_operators_module(
            session_steps=[_DummyResponse(428, {})]
        )
        orig_sleep = mod.time.sleep
        orig_monotonic = mod.time.monotonic
        monotonic_values = iter([0.0, 0.0, mod.BROWSER_LOGIN_POLL_TIMEOUT_SECONDS + 1.0])

        def _fake_monotonic():
            try:
                return next(monotonic_values)
            except StopIteration:
                return mod.BROWSER_LOGIN_POLL_TIMEOUT_SECONDS + 2.0

        try:
            mod.time.sleep = lambda _seconds: None
            mod.time.monotonic = _fake_monotonic
            mod._browser_login_thread_v2("txn-4", "sulu_ops_thread_pkg")
        finally:
            mod.time.sleep = orig_sleep
            mod.time.monotonic = orig_monotonic

        self.assertEqual([], queue_calls)
        self.assertIn("timed out", storage.panel_data.get("login_error", "").lower())


if __name__ == "__main__":
    unittest.main()
