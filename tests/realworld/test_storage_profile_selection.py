"""Saved Blender choices must retain the selected profile, never a list position."""
from pathlib import Path
import os
import subprocess
import sys
import zipfile

def test_saved_storage_choice_survives_reorder_and_rejects_removed_profile(tmp_path):
    import pytest
    if not os.environ.get("SULU_BLENDER_BINARY"):
        pytest.skip("requires the qualified Blender binary")
    repo = Path(__file__).resolve().parents[2]
    package = tmp_path / "addon.zip"
    package_tmp = tmp_path / "package-tmp"
    package_tmp.mkdir()
    env = dict(os.environ, TEMP=str(package_tmp), TMP=str(package_tmp), TMPDIR=str(package_tmp))
    subprocess.run([sys.executable, str(repo / "deploy.py"), "--environment", "test", "--output", str(package)], env=env, check=True)
    addon_parent = tmp_path / "addon"
    with zipfile.ZipFile(package) as archive:
        archive.extractall(addon_parent)
    subprocess.run([os.environ["SULU_BLENDER_BINARY"], "--factory-startup", "--background", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--addon-dir", str(addon_parent / "SuperluminalRender"), "--output", str(tmp_path / "selection.blend")], env=env, check=True)


def verify_in_blender(addon_dir, output):
    import addon_utils
    import bpy
    import importlib
    from types import SimpleNamespace

    sys.path.insert(0, str(addon_dir.parent))
    addon_utils.enable(addon_dir.name, default_set=True, persistent=False)
    addon = importlib.import_module(addon_dir.name)
    storage = addon.Storage
    storage.enable_job_thread = False
    storage.save = lambda: None
    org = "selection-test-org"
    r2 = {"id": "selection-r2", "name": "R2", "provider": "r2"}
    seaweed = {"id": "selection-seaweed", "name": "SeaweedFS", "provider": "seaweedfs"}
    additional = {"id": "selection-another", "name": "Another", "provider": "r2"}
    storage.data["org_id"] = org
    storage.data["storage_profiles"] = {org: {"profiles": [r2, seaweed], "default_profile": r2["id"]}}
    props = bpy.context.scene.superluminal_settings
    assert props.storage_profile == r2["id"]
    props.storage_profile = seaweed["id"]
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    storage.data["storage_profiles"][org] = {"profiles": [additional, seaweed, r2], "default_profile": additional["id"]}
    bpy.ops.wm.open_mainfile(filepath=str(output))
    props = bpy.context.scene.superluminal_settings
    assert props.storage_profile == seaweed["id"]
    assert props["_storage_profile_id"] == seaweed["id"]
    # Removing the selected profile must not turn an old saved choice into
    # a new provider. The real submit operator must stop before worker launch.
    storage.data["storage_profiles"][org] = {"profiles": [additional, r2], "default_profile": additional["id"]}
    assert props.storage_profile == ""
    assert props["_storage_profile_id"] == seaweed["id"]
    operator = importlib.import_module(addon_dir.name + ".transfers.submit.submit_operator")
    project = {"id": "selection-project", "organization_id": org, "sqid": "selection-project-sqid", "name": "Selection"}
    storage.data["user_token"] = "selection-fixture-token"
    storage.data["projects"] = [project]
    operator.get_prefs = lambda: SimpleNamespace(project_id=project["id"])
    operator.resolve_org_context = lambda *_: (org, "selection-fixture-key")

    def fail_launch(*args, **kwargs):
        raise AssertionError("A removed storage choice must not launch an uploader")

    operator.launch_worker_secure = fail_launch
    try:
        result = bpy.ops.superluminal.submit_job("EXEC_DEFAULT", mode="ANIMATION")
    except RuntimeError as error:
        assert "Choose storage for this job" in str(error)
    else:
        assert result == {"CANCELLED"}
    addon.unregister()
    print("SULU_STORAGE_SELECTION_REGRESSION passed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    verify_in_blender(args.addon_dir, args.output)
