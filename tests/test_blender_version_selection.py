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


def test_sulu_build_auto_selects_distinct_farm_runtime(monkeypatch):
    version_utils = load_version_utils(
        monkeypatch, (5, 2, 0), "5.2.0 SULU"
    )

    assert version_utils.enum_from_bpy_version() == "BLENDER52SULU"
    assert (
        version_utils.resolved_worker_blender_value(True, "BLENDER52")
        == "blender52sulu"
    )


def test_stock_build_keeps_stock_blender_52_runtime(monkeypatch):
    version_utils = load_version_utils(
        monkeypatch, (5, 2, 0), "5.2.0 LTS"
    )

    assert version_utils.enum_from_bpy_version() == "BLENDER52"
    assert version_utils.to_worker_blender_value("BLENDER52SULU") == "blender52sulu"


def test_newer_stock_build_still_clamps_to_standard_blender_52(monkeypatch):
    version_utils = load_version_utils(
        monkeypatch, (5, 3, 0), "5.3.0 Alpha"
    )

    assert version_utils.enum_from_bpy_version() == "BLENDER52"
