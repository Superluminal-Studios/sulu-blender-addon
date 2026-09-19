import importlib
import sys
import types


def load_version_utils(monkeypatch, version, version_string):
    fake_bpy = types.SimpleNamespace(
        app=types.SimpleNamespace(version=version, version_string=version_string)
    )
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    sys.modules.pop("utils.version_utils", None)
    return importlib.import_module("utils.version_utils")


def test_sulu_build_name_is_not_exposed_or_selected(monkeypatch):
    version_utils = load_version_utils(monkeypatch, (5, 2, 0), "5.2.0 SULU")

    assert version_utils.enum_from_bpy_version() == "BLENDER52"
    assert all(
        "SULU" not in item[0] + item[1]
        for item in version_utils.blender_version_items
    )


def test_newer_build_clamps_to_highest_deployed_standard_version(monkeypatch):
    version_utils = load_version_utils(monkeypatch, (5, 4, 0), "5.4.0 Alpha")

    assert version_utils.enum_from_bpy_version() == "BLENDER53"


def test_database_records_replace_items_and_worker_mapping(monkeypatch):
    version_utils = load_version_utils(monkeypatch, (5, 2, 0), "5.2.0")

    changed = version_utils.update_deployed_blender_versions(
        [
            {
                "identifier": "BLENDER52",
                "version": "5.2.0",
                "label": "Blender 5.2",
                "worker_value": "blender52-live-v2",
                "enabled": True,
                "deployed": True,
                "sort_order": 520,
            },
            {
                "identifier": "BLENDER53SULU",
                "version": "5.3.0",
                "label": "Blender 5.3 SULU",
                "worker_value": "blender53sulu",
                "enabled": True,
                "deployed": False,
                "sort_order": 530,
            },
            {
                "identifier": "BLENDER53",
                "version": "5.3.0",
                "label": "Blender 5.3 SULU",
                "worker_value": "blender53sulu",
                "channel": "sulu",
                "enabled": True,
                "deployed": True,
                "sort_order": 530,
            },
        ]
    )

    assert changed is True
    assert version_utils.blender_version_items_callback() == [
        ("BLENDER52", "Blender 5.2", "Use Blender 5.2.0 on the farm")
    ]
    assert version_utils.to_worker_blender_value("BLENDER52") == "blender52-live-v2"
    assert version_utils.enum_from_bpy_version() == "BLENDER52"


def test_invalid_or_empty_database_response_keeps_fallback(monkeypatch):
    version_utils = load_version_utils(monkeypatch, (5, 1, 2), "5.1.2")
    before = list(version_utils.blender_version_items)

    assert version_utils.update_deployed_blender_versions([]) is False
    assert version_utils.update_deployed_blender_versions(
        [{"identifier": "SULU"}]
    ) is False
    assert version_utils.blender_version_items == before
