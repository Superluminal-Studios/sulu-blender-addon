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


def test_newer_build_clamps_to_highest_deployed_standard_version(monkeypatch):
    version_utils = load_version_utils(monkeypatch, (5, 4, 0), "5.4.0 Alpha")

    assert version_utils.enum_from_bpy_version() == "BLENDER53"


