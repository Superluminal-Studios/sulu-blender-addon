"""Database catalog loading controls the versions available for submission."""

import importlib
import sys
import types
from pathlib import Path

import pytest
import requests


@pytest.fixture
def catalog(monkeypatch):
    package = types.ModuleType("sulu_catalog_test")
    package.__path__ = [str(Path(__file__).resolve().parents[1])]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    bpy = types.SimpleNamespace(app=types.SimpleNamespace(version=(6, 0, 0)))
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    api = importlib.import_module("sulu_catalog_test.utils.request_utils")
    versions = importlib.import_module("sulu_catalog_test.utils.version_utils")
    monkeypatch.setattr(api, "_request_properties_redraw", lambda: None)
    monkeypatch.setattr(api.Storage, "data", {"environment": "production", "user_token": "test-token"})
    monkeypatch.setattr(api.Storage, "environment_generation", 0)
    versions.clear_deployed_blender_versions("Loading")
    yield api, versions


def record(identifier, version, label, worker, order):
    return dict(identifier=identifier, version=version, label=label,
                worker_value=worker, sort_order=order, enabled=True, deployed=True)


def test_database_pages_supply_labels_and_submission_mapping_without_release_list(catalog, monkeypatch):
    api, versions = catalog
    first = record("BLENDER53", "5.3.0", "Blender 5.3", "blender53", 530)
    future = record("BLENDER60", "6.0.1", "Blender 6.0", "farm_blender_60", 600)
    calls = []
    def request(method, url, params):
        calls.append((method, url, params))
        page = params["page"]
        return types.SimpleNamespace(json=lambda: {
            "items": [[first], [future]][page - 1], "page": page, "totalPages": 2,
        })
    monkeypatch.setattr(api, "authorized_request", request)
    api.fetch_blender_versions()
    assert [row[1] for row in versions.blender_version_items_callback()] == ["Blender 5.3", "Blender 6.0"]
    assert versions.resolved_worker_blender_value(True, "") == "farm_blender_60"
    assert versions.resolved_worker_blender_value(False, "BLENDER53") == "blender53"
    assert [call[2]["page"] for call in calls] == [1, 2]
    assert all(call[0] == "GET" and call[1].endswith("/api/collections/blender_versions/records") for call in calls)


def test_failed_catalog_refresh_clears_choices_and_blocks_submission(catalog, monkeypatch):
    api, versions = catalog
    row = record("BLENDER60", "6.0.1", "Blender 6.0", "blender60", 600)
    monkeypatch.setattr(api, "authorized_request", lambda *a, **kw: types.SimpleNamespace(
        json=lambda: {"items": [row], "page": 1, "totalPages": 1}))
    api.fetch_blender_versions()
    def unavailable(*a, **kw):
        raise requests.ConnectionError("Catalog unavailable")
    monkeypatch.setattr(api, "authorized_request", unavailable)
    with pytest.raises(requests.ConnectionError):
        api.fetch_blender_versions()
    assert versions.blender_version_items_callback() == []
    assert "Refresh Projects" in versions.blender_version_status()
    with pytest.raises(ValueError, match="Refresh Projects"):
        versions.resolved_worker_blender_value(False, "BLENDER60")
    with pytest.raises(ValueError, match="Refresh Projects"):
        versions.resolved_worker_blender_value(True, "")


def test_response_from_retired_session_cannot_publish_versions(catalog, monkeypatch):
    api, versions = catalog
    def request(*a, **kw):
        api.Storage.environment_generation += 1
        return types.SimpleNamespace(json=lambda: {
            "items": [record("BLENDER60", "6.0.1", "Old session", "old", 600)],
            "page": 1, "totalPages": 1,
        })
    monkeypatch.setattr(api, "authorized_request", request)
    with pytest.raises(api.ProjectContextError, match="session changed"):
        api.fetch_blender_versions()
    assert versions.blender_version_items_callback() == []
