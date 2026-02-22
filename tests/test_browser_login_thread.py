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


class TestBrowserLoginThread(unittest.TestCase):
    def _load_operators_module(self):
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
            return True

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

        class _Session:
            def __init__(self):
                self.calls = 0

            def post(self, url, json=None, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    return _DummyResponse(428, {})
                return _DummyResponse(200, {"token": "tok-123"})

        class _Storage:
            session = _Session()
            timeout = 5
            panel_data = {}
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
        return mod, queue_calls

    def test_browser_login_thread_queues_bootstrap_only(self):
        mod, queue_calls = self._load_operators_module()
        mod.first_login = lambda token: (_ for _ in ()).throw(
            AssertionError("first_login must not run in browser thread")
        )

        mod._browser_login_thread_v2("txn-1", "sulu_ops_thread_pkg")
        self.assertEqual([("tok-123", "sulu_ops_thread_pkg")], queue_calls)


if __name__ == "__main__":
    unittest.main()
