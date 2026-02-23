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


class TestLoginErrorHelper(unittest.TestCase):
    def _load_preferences_module(self):
        pkg_name = "sulu_pref_status_pkg"

        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_addon_dir)]
        sys.modules[pkg_name] = pkg

        bpy_mod = types.ModuleType("bpy")
        bpy_mod.types = types.SimpleNamespace(
            Operator=object,
            Menu=object,
            UIList=object,
            AddonPreferences=object,
            PropertyGroup=object,
        )
        bpy_mod.props = types.SimpleNamespace(
            StringProperty=lambda **kwargs: None,
            EnumProperty=lambda **kwargs: None,
            BoolProperty=lambda **kwargs: None,
            IntProperty=lambda **kwargs: None,
            FloatProperty=lambda **kwargs: None,
            CollectionProperty=lambda **kwargs: None,
        )
        bpy_mod.context = types.SimpleNamespace(
            preferences=types.SimpleNamespace(addons={pkg_name: types.SimpleNamespace(preferences=types.SimpleNamespace())}),
        )
        sys.modules["bpy"] = bpy_mod

        storage_mod = types.ModuleType(f"{pkg_name}.storage")

        class _Storage:
            data = {"projects": [], "jobs": {}, "user_token": ""}
            panel_data = {"login_error": ""}

        storage_mod.Storage = _Storage
        sys.modules[f"{pkg_name}.storage"] = storage_mod

        date_mod = types.ModuleType(f"{pkg_name}.utils.date_utils")
        date_mod.format_submitted = lambda value: str(value or "")
        sys.modules[f"{pkg_name}.utils.date_utils"] = date_mod

        req_mod = types.ModuleType(f"{pkg_name}.utils.request_utils")
        req_mod.get_render_queue_key = lambda org_id: "key"
        req_mod.request_jobs_refresh = lambda **kwargs: True
        req_mod.set_auto_refresh = lambda enabled: None
        req_mod.set_refresh_context = lambda org_id, user_key, project_id: None
        sys.modules[f"{pkg_name}.utils.request_utils"] = req_mod

        icons_mod = types.ModuleType(f"{pkg_name}.icons")
        icons_mod.get_status_icon_id = lambda status: 0
        icons_mod.get_fallback_icon = lambda status: "INFO"
        sys.modules[f"{pkg_name}.icons"] = icons_mod

        mod = _load_module_directly(
            f"{pkg_name}.preferences",
            _addon_dir / "preferences.py",
        )
        return mod, _Storage

    def test_login_error_text_is_trimmed(self):
        mod, storage = self._load_preferences_module()
        storage.panel_data["login_error"] = "  token expired  "
        self.assertEqual("token expired", mod._login_error_text())

    def test_login_error_text_empty_when_missing(self):
        mod, storage = self._load_preferences_module()
        storage.panel_data["login_error"] = ""
        self.assertEqual("", mod._login_error_text())

    def test_format_job_status_normalizes_common_values(self):
        mod, _storage = self._load_preferences_module()
        self.assertEqual("Running", mod.format_job_status("running"))
        self.assertEqual("Finished", mod.format_job_status("FINISHED"))
        self.assertEqual("In Progress", mod.format_job_status("in_progress"))

    def test_format_job_status_empty_becomes_unknown(self):
        mod, _storage = self._load_preferences_module()
        self.assertEqual("Unknown", mod.format_job_status(""))
        self.assertEqual("Unknown", mod.format_job_status("   "))

    def test_jobs_table_column_order_starts_with_status_then_name(self):
        mod, _storage = self._load_preferences_module()
        self.assertGreaterEqual(len(mod.COLUMN_ORDER), 2)
        self.assertEqual("status", mod.COLUMN_ORDER[0])
        self.assertEqual("name", mod.COLUMN_ORDER[1])


if __name__ == "__main__":
    unittest.main()
