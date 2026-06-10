from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent


def _load_module_directly(name: str, filepath: Path):
    """Load a single .py file as a module, bypassing package __init__.py."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_submit_worker = _load_module_directly(
    "submit_worker_schema_sync",
    _addon_dir / "transfers" / "submit" / "submit_worker.py",
)


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, get_status=404, post_status=200, get_exc=None):
        self.get_status = get_status
        self.post_status = post_status
        self.get_exc = get_exc
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if self.get_exc is not None:
            raise self.get_exc
        return _FakeResponse(self.get_status)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return _FakeResponse(self.post_status)


def _handoff(**overrides):
    data = {
        "pocketbase_url": "https://pb.example",
        "settings_schema": {"schema_version": 1, "blender_version": "4.5.9", "groups": []},
        "settings_schema_key": "bl459-0123456789abcdef",
    }
    data.update(overrides)
    return data


_HEADERS = {"Authorization": "redacted-token"}


class TestSyncSettingsSchema(unittest.TestCase):
    def test_posts_schema_when_key_is_unknown(self):
        session = _FakeSession(get_status=404)
        _submit_worker._sync_settings_schema(session, _handoff(), _HEADERS)

        self.assertEqual(
            session.get_calls[0][0],
            "https://pb.example/api/blender_schemas/bl459-0123456789abcdef",
        )
        self.assertEqual(session.get_calls[0][1]["headers"], _HEADERS)
        self.assertEqual(len(session.post_calls), 1)
        url, kwargs = session.post_calls[0]
        self.assertEqual(url, "https://pb.example/api/blender_schemas")
        body = json.loads(kwargs["data"])
        self.assertEqual(body["schema_key"], "bl459-0123456789abcdef")
        self.assertEqual(body["blender_version"], "4.5.9")
        self.assertEqual(body["schema"]["schema_version"], 1)

    def test_skips_post_when_schema_already_registered(self):
        session = _FakeSession(get_status=200)
        _submit_worker._sync_settings_schema(session, _handoff(), _HEADERS)
        self.assertEqual(len(session.get_calls), 1)
        self.assertEqual(session.post_calls, [])

    def test_no_requests_without_schema_or_key(self):
        session = _FakeSession()
        _submit_worker._sync_settings_schema(
            session, _handoff(settings_schema=None), _HEADERS
        )
        _submit_worker._sync_settings_schema(
            session, _handoff(settings_schema_key=""), _HEADERS
        )
        _submit_worker._sync_settings_schema(session, {"pocketbase_url": "x"}, _HEADERS)
        self.assertEqual(session.get_calls, [])
        self.assertEqual(session.post_calls, [])

    def test_get_failure_is_swallowed(self):
        session = _FakeSession(get_exc=ConnectionError("farm down"))
        _submit_worker._sync_settings_schema(session, _handoff(), _HEADERS)
        self.assertEqual(session.post_calls, [])

    def test_unexpected_get_status_is_swallowed_without_post(self):
        session = _FakeSession(get_status=500)
        _submit_worker._sync_settings_schema(session, _handoff(), _HEADERS)
        self.assertEqual(session.post_calls, [])

    def test_post_failure_is_swallowed(self):
        session = _FakeSession(get_status=404, post_status=500)
        _submit_worker._sync_settings_schema(session, _handoff(), _HEADERS)
        self.assertEqual(len(session.post_calls), 1)


if __name__ == "__main__":
    unittest.main()
