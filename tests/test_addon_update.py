"""Update boundaries must preserve user data and never install unverified code."""

import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import types
from unittest.mock import Mock
import zipfile

import pytest

import update_install as installer


def package(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("SuperluminalRender/__init__.py", "bl_info = {'version': (1, 4, 0), 'blender': (4, 4, 0)}")
        archive.writestr("SuperluminalRender/build_info.py", 'BUILD_CHANNEL = "release"\nBUILD_ENVIRONMENT = "production"')
        archive.writestr("SuperluminalRender/new_code.py", "value = 1")
        if extra:
            archive.writestr(*extra)
    return output.getvalue()


def response_session(payload):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [payload]
    session = Mock()
    session.get.return_value = response
    return session


def prepare(tmp_path, payload=None):
    payload = package() if payload is None else payload
    attempt = tmp_path / ".sulu-update-test"
    attempt.mkdir()
    release = dict(version=[1, 4, 0], url=installer.RELEASE_PREFIX + "1.4.0/SuperluminalRender.zip",
                   sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))
    stage = installer.prepare_release(response_session(payload), release, attempt, (5, 2, 0), "production")
    return attempt, stage


def plan_for(tmp_path, attempt, stage):
    addon = tmp_path / "SuperluminalRender"
    addon.mkdir()
    (addon / "old_code.py").write_text("old code")
    (addon / "session.json").write_bytes(b'{"user_token":"test-only","project_id":"keep"}')
    (addon / "dev_config.json").write_bytes(b'{"setting":"keep"}')
    (addon / "rclone").mkdir()
    (addon / "rclone" / "rclone.exe").write_bytes(b"preserved-rclone")
    return dict(addon=str(addon), attempt=str(attempt), stage=stage,
                blender=str(tmp_path / "Blender with spaces" / "blender.exe"),
                blend_file=str(tmp_path / "Scene with spaces.blend"),
                status=str(tmp_path / "status.json"), version=[1, 4, 0])


def test_verified_update_replaces_code_preserves_config_and_rclone_and_reopens_same_file(tmp_path):
    attempt, stage = prepare(tmp_path)
    plan = plan_for(tmp_path, attempt, stage)
    addon = Path(plan["addon"])
    before = {name: (addon / name).read_bytes() for name in ("session.json", "dev_config.json", "rclone/rclone.exe")}
    launch = Mock()
    installer.install(plan, launch=launch)
    assert not (addon / "old_code.py").exists()
    assert (addon / "new_code.py").exists()
    assert {name: (addon / name).read_bytes() for name in before} == before
    assert launch.call_count == 1
    assert launch.call_args.args[0] == [plan["blender"], plan["blend_file"]]
    assert launch.call_args.kwargs["cwd"] == str(Path(plan["blender"]).parent)
    assert (attempt / "previous" / "old_code.py").exists()
    assert json.loads(Path(plan["status"]).read_text())["state"] == "installed"


@pytest.mark.parametrize("extra", [("../outside.py", "bad"), ("SuperluminalRender/session.json", "bad")])
def test_unsafe_release_never_reaches_install(tmp_path, extra):
    with pytest.raises(ValueError):
        prepare(tmp_path, package(extra))
    assert not (tmp_path / "outside.py").exists()
    assert not (tmp_path / "SuperluminalRender").exists()


def test_checksum_failure_keeps_installed_code_untouched(tmp_path):
    addon = tmp_path / "SuperluminalRender"
    addon.mkdir()
    (addon / "__init__.py").write_text("original")
    payload = package()
    with pytest.raises(ValueError, match="checksum"):
        installer.prepare_release(response_session(payload), dict(url="unused", size=len(payload), sha256="0" * 64),
                                  tmp_path, (5, 2, 0), "production")
    assert (addon / "__init__.py").read_text() == "original"


def test_restart_failure_rolls_back_code_and_all_preserved_files(tmp_path):
    attempt, stage = prepare(tmp_path)
    plan = plan_for(tmp_path, attempt, stage)
    with pytest.raises(OSError, match="launch failed"):
        installer.install(plan, launch=Mock(side_effect=OSError("launch failed")))
    addon = Path(plan["addon"])
    assert (addon / "old_code.py").read_text() == "old code"
    assert (addon / "rclone" / "rclone.exe").read_bytes() == b"preserved-rclone"
    assert json.loads((addon / "session.json").read_text())["project_id"] == "keep"
    assert not (addon / "new_code.py").exists()


def test_install_failure_mid_preservation_rolls_back_moved_data(tmp_path, monkeypatch):
    attempt, stage = prepare(tmp_path)
    plan = plan_for(tmp_path, attempt, stage)
    original_rename = Path.rename
    def locked(source, destination):
        if source.name == "rclone":
            raise PermissionError("locked rclone")
        return original_rename(source, destination)
    monkeypatch.setattr(Path, "rename", locked)
    launch = Mock()
    with pytest.raises(PermissionError, match="locked rclone"):
        installer.install(plan, launch=launch)
    addon = Path(plan["addon"])
    assert (addon / "old_code.py").exists()
    assert (addon / "session.json").exists()
    assert (addon / "dev_config.json").exists()
    launch.assert_not_called()


def test_release_check_uses_verified_latest_asset_and_never_downgrades():
    session = Mock()
    session.get.return_value.json.return_value = dict(draft=False, prerelease=False, tag_name="1.4.0", assets=[
        dict(name="SuperluminalRender.zip", browser_download_url=installer.RELEASE_PREFIX + "1.4.0/SuperluminalRender.zip",
             digest="sha256:" + "a" * 64, size=100)])
    assert installer.latest_release(session, (1, 3, 22))["version"] == [1, 4, 0]
    assert installer.latest_release(session, (1, 4, 1)) is None


def test_parent_timeout_never_installs_or_relaunches(tmp_path, monkeypatch):
    attempt, stage = prepare(tmp_path)
    plan = plan_for(tmp_path, attempt, stage)
    plan["parent_pid"] = 123
    handoff = attempt / "plan.json"
    handoff.write_text(json.dumps(plan))
    monkeypatch.setattr(installer, "wait_for_exit", Mock(side_effect=TimeoutError("still running")))
    launch = Mock()
    monkeypatch.setattr(installer.subprocess, "Popen", launch)
    with pytest.raises(TimeoutError):
        installer.main(handoff)
    assert Path(plan["addon"], "old_code.py").exists()
    launch.assert_not_called()
    assert json.loads(Path(plan["status"]).read_text())["state"] == "error"


def test_failed_scene_save_does_not_launch_installer_or_close_blender(tmp_path, monkeypatch):
    package_name = "sulu_update_ui_test"
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(Path(__file__).parents[1])]
    monkeypatch.setitem(sys.modules, package_name, package_module)
    bpy = types.SimpleNamespace(
        types=types.SimpleNamespace(Operator=type("Operator", (), {"report": Mock()})),
        props=types.SimpleNamespace(EnumProperty=lambda **kwargs: None, StringProperty=lambda **kwargs: None),
        app=types.SimpleNamespace(is_job_running=lambda job: False),
        data=types.SimpleNamespace(filepath=str(tmp_path / "scene.blend")),
        ops=types.SimpleNamespace(wm=types.SimpleNamespace(
            save_as_mainfile=Mock(return_value={"CANCELLED"}), quit_blender=Mock())),
    )
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    ui = importlib.import_module(package_name + ".updater")
    ui.state.update(phase="ready")
    launch = Mock()
    monkeypatch.setattr(ui.subprocess, "Popen", launch)
    operator = ui.SUPERLUMINAL_OT_RestartUpdate()
    operator.save_choice = "SAVE"
    operator.filepath = ""
    assert operator.execute(None) == {"CANCELLED"}
    launch.assert_not_called()
    bpy.ops.wm.quit_blender.assert_not_called()
