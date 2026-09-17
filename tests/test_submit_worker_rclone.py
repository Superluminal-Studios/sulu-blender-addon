from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / relative)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


worker = load("rclone_submit_test_worker", "transfers/submit/submit_worker.py")


def context(tmp_path, monkeypatch, *, project=True):
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"blend")
    dependency = tmp_path / "texture.png"
    dependency.write_bytes(b"image")
    archive = tmp_path / "packed.zip"
    archive.write_bytes(b"archive")
    project_record = {
        "id": "project-a",
        "organization_id": "org-a",
        "name": "Project A",
        "sqid": "ProjA",
    }
    run_rclone = Mock(return_value={
        "bytes_transferred": 5,
        "checks": 1,
        "transfers": 1,
        "errors": 0,
    })
    data = {
        "project": project_record,
        "job_id": "local-intent",
        "job_name": "Render A",
        "start_frame": 1,
        "blender_version": "4.5.2",
        "image_format": "SCENE",
        "render_engine": "CYCLES",
        "use_scene_image_format": True,
        "packed_addons": [],
        "ignore_errors": False,
        "use_bserver": True,
        "farm_url": "https://farm.invalid/farm/org-a/api/",
        "pocketbase_url": "https://api.invalid",
        "user_token": "ordinary-user-token",
    }
    mods = {
        "pkg_name": "sulu_test",
        "run_rclone": run_rclone,
        "CLOUDFLARE_R2_DOMAIN":
            "a" * 32 + ".r2.cloudflarestorage.com",
        "_build_base": Mock(return_value=["rclone-direct-r2"]),
        "fetch_project_storage": Mock(return_value={
            "items": [{
                "bucket_name": "render-test-project",
                "access_key_id": "fixture",
                "secret_access_key": "fixture",
                "session_token": "fixture",
            }]
        }),
    }
    ctx = SimpleNamespace(
        data=data,
        mods=mods,
        proj=project_record,
        org_id="org-a",
        use_project=project,
        blend_path=str(blend),
        zip_file=archive,
        filelist=tmp_path / "manifest.txt",
        common_path=str(tmp_path),
        project_root_str=str(tmp_path),
        main_blend_s3="scene.blend",
        rel_manifest=["texture.png"],
        dependency_total_size=5,
        required_storage=10,
        project_name="Project A",
        project_sqid="ProjA",
        job_id="local-intent",
        effective_end_frame=10,
        frame_step_val=2,
        render_order="TEMPORAL_REFINE",
        render_tasks=[1, 3, 5, 7, 9],
        rclone_bin="rclone",
        storage_future=None,
        storage_thread=None,
        session=Mock(),
        headers={"Authorization": "redacted"},
        phase_timings={},
        logger=Mock(),
        report=Mock(),
    )
    monkeypatch.setattr(worker, "_nfc", lambda value: value)
    monkeypatch.setattr(
        worker, "_s3key_clean", lambda value: value.replace("\\", "/"))
    return ctx


def test_upload_streams_every_payload_through_rclone_not_api(
        tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)

    monkeypatch.setattr(worker, "_debug_enabled", lambda: False)
    worker._upload(ctx)

    calls = ctx.mods["run_rclone"].call_args_list
    assert len(calls) >= 2
    assert all(call.args[0] == ["rclone-direct-r2"] for call in calls)
    assert all(
        isinstance(call.args[3], str)
        and call.args[3].startswith(":s3:render-test-project/")
        for call in calls
    )
    assert any(call.args[1] == "copyto" for call in calls)
    assert any(call.args[1] == "copy" for call in calls)
    ctx.mods["fetch_project_storage"].assert_called_once()
    ctx.session.put.assert_not_called()
    ctx.session.patch.assert_not_called()
    ctx.session.post.assert_not_called()


def test_submission_registers_metadata_only_after_rclone_upload(
        tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch, project=False)
    response = Mock()
    response.raise_for_status.return_value = None
    ctx.session.post.return_value = response

    worker._register_job(ctx)

    ctx.session.post.assert_called_once()
    call = ctx.session.post.call_args
    assert call.args[0] == "https://api.invalid/api/farm/org-a/jobs"
    body = __import__("json").loads(call.kwargs["data"])
    job = body["job_data"]
    assert job["id"] == "local-intent"
    assert job["zip"] is True
    assert job["image_format"] == "SCENE"
    assert job["render_order"] == "TEMPORAL_REFINE"
    assert job["frame_step"] == 2
    assert job["required_storage"] == 10
    ctx.session.put.assert_not_called()
    ctx.session.patch.assert_not_called()
