from __future__ import annotations

import importlib.util
import sys
import time
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


class TestPanelStatusHelpers(unittest.TestCase):
    def _load_panels_module(self):
        pkg_name = "sulu_panels_status_pkg"

        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_addon_dir)]
        sys.modules[pkg_name] = pkg

        bpy_mod = types.ModuleType("bpy")
        bpy_types_mod = types.ModuleType("bpy.types")
        bpy_types_mod.UILayout = object
        bpy_types_mod.PropertyGroup = object
        bpy_types_mod.UIList = object
        bpy_types_mod.Operator = object
        bpy_types_mod.Panel = object
        bpy_types_mod.WindowManager = object
        bpy_types_mod.Scene = object
        bpy_types_mod.UI_UL_list = types.SimpleNamespace(
            sort_items_by_name=lambda *_args, **_kwargs: []
        )
        bpy_mod.types = bpy_types_mod
        bpy_mod.props = types.SimpleNamespace(
            StringProperty=lambda **kwargs: None,
            CollectionProperty=lambda **kwargs: None,
            IntProperty=lambda **kwargs: None,
            PointerProperty=lambda **kwargs: None,
        )
        bpy_mod.context = types.SimpleNamespace(
            preferences=types.SimpleNamespace(addons=[]),
        )
        sys.modules["bpy"] = bpy_mod
        sys.modules["bpy.types"] = bpy_types_mod

        addon_utils_mod = types.ModuleType("addon_utils")
        addon_utils_mod.modules = lambda: []
        addon_utils_mod.module_bl_info = lambda mod: {}
        sys.modules["addon_utils"] = addon_utils_mod

        constants_mod = types.ModuleType(f"{pkg_name}.constants")
        constants_mod.DEFAULT_ADDONS = set()
        sys.modules[f"{pkg_name}.constants"] = constants_mod

        version_mod = types.ModuleType(f"{pkg_name}.utils.version_utils")
        version_mod.get_blender_version_string = lambda: "4.4.0"
        sys.modules[f"{pkg_name}.utils.version_utils"] = version_mod

        prefs_mod = types.ModuleType(f"{pkg_name}.preferences")
        prefs_mod.refresh_jobs_collection = lambda prefs: None
        prefs_mod.draw_header_row = lambda layout, prefs: None
        prefs_mod.draw_login = lambda layout: None
        sys.modules[f"{pkg_name}.preferences"] = prefs_mod

        icons_mod = types.ModuleType(f"{pkg_name}.icons")
        icons_mod.get_icon_id = lambda key: 0
        icons_mod.get_fallback_icon = lambda key: "INFO"
        sys.modules[f"{pkg_name}.icons"] = icons_mod

        scan_mod = types.ModuleType(f"{pkg_name}.utils.project_scan")
        scan_mod.quick_cross_drive_hint = lambda: (False, types.SimpleNamespace(
            blend_saved=True,
            examples_other_roots=lambda n: [],
            cross_drive_count=lambda: 0,
        ))
        scan_mod.human_shorten = lambda path: path
        sys.modules[f"{pkg_name}.utils.project_scan"] = scan_mod

        class _Storage:
            data = {}
            panel_data = {
                "projects_refresh_error": "",
                "projects_refresh_at": 0.0,
                "refresh_service_state": "running",
            }

        storage_mod = types.ModuleType(f"{pkg_name}.storage")
        storage_mod.Storage = _Storage
        sys.modules[f"{pkg_name}.storage"] = storage_mod

        mod = _load_module_directly(
            f"{pkg_name}.panels",
            _addon_dir / "panels.py",
        )
        return mod, _Storage

    def test_projects_refresh_status_error_has_priority(self):
        mod, storage = self._load_panels_module()
        storage.panel_data["projects_refresh_error"] = "network issue"
        storage.panel_data["projects_refresh_at"] = time.time()

        icon, text = mod._projects_refresh_status()
        self.assertEqual("ERROR", icon)
        self.assertIn("network issue", text)

    def test_projects_refresh_status_info_uses_timestamp(self):
        mod, storage = self._load_panels_module()
        storage.panel_data["projects_refresh_error"] = ""
        storage.panel_data["projects_refresh_at"] = 100.0

        icon, text = mod._projects_refresh_status()
        self.assertEqual("INFO", icon)
        self.assertTrue(text.startswith("Projects refreshed: "))

    def test_refresh_service_status_maps_error_state(self):
        mod, storage = self._load_panels_module()
        storage.panel_data["refresh_service_state"] = "error"

        icon, text = mod._refresh_service_status()
        self.assertEqual("ERROR", icon)
        self.assertEqual("Refresh: error", text)


if __name__ == "__main__":
    unittest.main()
