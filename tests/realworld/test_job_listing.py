"""Exercise the registered Blender jobs collection with canonical API responses."""
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def test_canonical_job_progress_sort_and_refresh_in_blender(tmp_path):
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
    subprocess.run([os.environ["SULU_BLENDER_BINARY"], "--factory-startup", "--background", "--python-exit-code", "1", "--python", str(Path(__file__).resolve()), "--", "--addon-dir", str(addon_parent / "SuperluminalRender")], env=env, check=True)


def verify_in_blender(addon_dir):
    import addon_utils
    import bpy
    import importlib

    sys.path.insert(0, str(addon_dir.parent))
    addon_utils.enable(addon_dir.name, default_set=True, persistent=False)
    addon = importlib.import_module(addon_dir.name)
    storage = addon.Storage
    storage.enable_job_thread = False
    storage.save = lambda: None
    prefs = bpy.context.preferences.addons[addon_dir.name].preferences
    preferences = importlib.import_module(addon_dir.name + ".preferences")
    request_utils = importlib.import_module(addon_dir.name + ".utils.request_utils")
    project = {"id": "listing-project", "sqid": "listing-sqid", "organization_id": "listing-organization", "name": "Listing"}
    storage.data.update(org_id=project["organization_id"], project_id=project["id"], projects=[project], user_key="")
    storage.suppress_project_callback = True
    prefs.project_id = project["id"]
    storage.suppress_project_callback = False
    prefs.sort_column = "finished_frames"
    prefs.sort_ascending = False
    responses = [
        {"job-low": {"name": "Low", "project_id": project["id"], "total_tasks": 200, "finished_tasks": 20},
         "job-high": {"name": "High", "project_id": project["id"], "total_tasks": 200, "finished_tasks": 100}},
        {"job-low": {"name": "Low", "project_id": project["id"], "total_tasks": 200, "finished_tasks": 120},
         "job-high": {"name": "High", "project_id": project["id"], "total_tasks": 200, "finished_tasks": 100}},
    ]

    class Response:
        def json(self):
            return {"body": responses.pop(0)}

    def read(method, url, **options):
        assert method == "GET" and url.endswith("/api/render/v1/browser/jobs/" + project["organization_id"])
        assert options == {"params": {"project_id": project["id"], "limit": 200}, "stored_job_session": True}
        return Response()

    request_utils.authorized_request = read
    request_utils.fetch_jobs(project["organization_id"], project["id"])
    assert preferences.refresh_jobs_collection(prefs)
    assert [(item.id, item.finished_frames) for item in prefs.jobs] == [("job-high", 100), ("job-low", 20)]
    assert abs(prefs.jobs[0].progress - 0.5) < 0.00001
    assert abs(prefs.jobs[1].progress - 0.1) < 0.00001
    prefs.active_job_index = 0
    request_utils.fetch_jobs(project["organization_id"], project["id"])
    assert preferences.refresh_jobs_collection(prefs)
    assert [(item.id, item.finished_frames) for item in prefs.jobs] == [("job-low", 120), ("job-high", 100)]
    assert abs(prefs.jobs[0].progress - 0.6) < 0.00001
    assert prefs.jobs[prefs.active_job_index].id == "job-high"
    assert not preferences.refresh_jobs_collection(prefs)
    addon.unregister()
    print("SULU_CANONICAL_JOB_LISTING_REGRESSION passed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    verify_in_blender(args.addon_dir)
