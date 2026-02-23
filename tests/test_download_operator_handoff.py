from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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


class TestDownloadOperatorHandoff(unittest.TestCase):
    def _load_download_operator_module(self, *, blend_filepath: str):
        pkg_name = "sulu_download_operator_pkg"

        for key in [k for k in list(sys.modules) if k == pkg_name or k.startswith(f"{pkg_name}.")]:
            del sys.modules[key]

        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_addon_dir)]
        sys.modules[pkg_name] = pkg

        transfers_pkg = types.ModuleType(f"{pkg_name}.transfers")
        transfers_pkg.__path__ = [str(_addon_dir / "transfers")]
        sys.modules[f"{pkg_name}.transfers"] = transfers_pkg

        download_pkg = types.ModuleType(f"{pkg_name}.transfers.download")
        download_pkg.__path__ = [str(_addon_dir / "transfers" / "download")]
        sys.modules[f"{pkg_name}.transfers.download"] = download_pkg

        utils_pkg = types.ModuleType(f"{pkg_name}.utils")
        utils_pkg.__path__ = [str(_addon_dir / "utils")]
        sys.modules[f"{pkg_name}.utils"] = utils_pkg

        worker_utils_mod = types.ModuleType(f"{pkg_name}.utils.worker_utils")
        worker_utils_mod.launch_in_terminal = lambda cmd: None
        sys.modules[f"{pkg_name}.utils.worker_utils"] = worker_utils_mod

        constants_mod = types.ModuleType(f"{pkg_name}.constants")
        constants_mod.POCKETBASE_URL = "https://pb.example"
        sys.modules[f"{pkg_name}.constants"] = constants_mod

        prefs_mod = types.ModuleType(f"{pkg_name}.utils.prefs")
        prefs_mod.get_prefs = lambda: types.SimpleNamespace(project_id="project-1")
        prefs_mod.get_addon_dir = lambda: Path("/addon-root")
        sys.modules[f"{pkg_name}.utils.prefs"] = prefs_mod

        storage_mod = types.ModuleType(f"{pkg_name}.storage")

        class _Storage:
            data = {
                "projects": [{"id": "project-1", "name": "Project 1"}],
                "org_id": "org-1",
                "user_token": "user-token",
                "user_key": "user-key",
            }

        storage_mod.Storage = _Storage
        sys.modules[f"{pkg_name}.storage"] = storage_mod

        bpy_mod = types.ModuleType("bpy")
        bpy_mod.app = types.SimpleNamespace(python_args=())
        bpy_mod.props = types.SimpleNamespace(StringProperty=lambda **kwargs: None)
        bpy_mod.types = types.SimpleNamespace(Operator=object)
        bpy_mod.data = types.SimpleNamespace(filepath=blend_filepath)
        bpy_mod.path = types.SimpleNamespace(abspath=lambda p: str(p))
        sys.modules["bpy"] = bpy_mod

        mod = _load_module_directly(
            f"{pkg_name}.transfers.download.download_operator",
            _addon_dir / "transfers" / "download" / "download_operator.py",
        )
        return mod, bpy_mod

    def test_saved_blend_relative_path_sets_blend_parent_as_base_dir(self):
        mod, _bpy = self._load_download_operator_module(
            blend_filepath="/work/project/main.blend"
        )

        reports = []
        captured = {}

        def _launch(cmd):
            captured["cmd"] = list(cmd)

        mod.launch_in_terminal = _launch

        op = mod.SUPERLUMINAL_OT_DownloadJob()
        op.job_id = "job-1"
        op.job_name = "Job 1"
        op.report = lambda level, msg: reports.append((set(level), str(msg)))

        context = types.SimpleNamespace(
            scene=types.SimpleNamespace(
                superluminal_settings=types.SimpleNamespace(download_path="//downloads")
            )
        )

        with tempfile.TemporaryDirectory() as td:
            with patch.object(mod.tempfile, "gettempdir", return_value=td):
                result = op.execute(context)

            handoff_path = Path(captured["cmd"][-1])
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_path.unlink(missing_ok=True)

        self.assertEqual({"FINISHED"}, result)
        self.assertEqual("//downloads", handoff["download_path"])
        self.assertEqual(
            os.path.abspath("/work/project"),
            handoff["download_base_dir"],
        )
        self.assertFalse(any("WARNING" in levels for levels, _ in reports))

    def test_unsaved_blend_relative_path_falls_back_to_temp_and_warns(self):
        mod, _bpy = self._load_download_operator_module(blend_filepath="")

        reports = []
        captured = {}

        def _launch(cmd):
            captured["cmd"] = list(cmd)

        mod.launch_in_terminal = _launch

        op = mod.SUPERLUMINAL_OT_DownloadJob()
        op.job_id = "job-2"
        op.job_name = "Job 2"
        op.report = lambda level, msg: reports.append((set(level), str(msg)))

        context = types.SimpleNamespace(
            scene=types.SimpleNamespace(
                superluminal_settings=types.SimpleNamespace(download_path="//")
            )
        )

        with tempfile.TemporaryDirectory() as td:
            with patch.object(mod.tempfile, "gettempdir", return_value=td):
                result = op.execute(context)

            handoff_path = Path(captured["cmd"][-1])
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_path.unlink(missing_ok=True)

        self.assertEqual({"FINISHED"}, result)
        self.assertEqual("//", handoff["download_path"])
        self.assertEqual(
            os.path.abspath(td),
            handoff["download_base_dir"],
        )
        warning_messages = [msg for levels, msg in reports if "WARNING" in levels]
        self.assertTrue(warning_messages)
        self.assertTrue(any("unsaved" in msg.lower() for msg in warning_messages))

    def test_unsaved_blend_absolute_path_does_not_warn(self):
        mod, _bpy = self._load_download_operator_module(blend_filepath="")

        reports = []
        captured = {}

        def _launch(cmd):
            captured["cmd"] = list(cmd)

        mod.launch_in_terminal = _launch

        op = mod.SUPERLUMINAL_OT_DownloadJob()
        op.job_id = "job-3"
        op.job_name = "Job 3"
        op.report = lambda level, msg: reports.append((set(level), str(msg)))

        with tempfile.TemporaryDirectory() as out_dir:
            context = types.SimpleNamespace(
                scene=types.SimpleNamespace(
                    superluminal_settings=types.SimpleNamespace(download_path=out_dir)
                )
            )
            with tempfile.TemporaryDirectory() as td:
                with patch.object(mod.tempfile, "gettempdir", return_value=td):
                    result = op.execute(context)

                handoff_path = Path(captured["cmd"][-1])
                handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
                handoff_path.unlink(missing_ok=True)

            self.assertEqual({"FINISHED"}, result)
            self.assertEqual(out_dir, handoff["download_path"])
            warning_messages = [msg for levels, msg in reports if "WARNING" in levels]
            self.assertFalse(warning_messages)


if __name__ == "__main__":
    unittest.main()
