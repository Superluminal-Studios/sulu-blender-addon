from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import pytest


def _load_worker():
    path = Path(__file__).parents[1] / "transfers" / "submit" / "submit_worker.py"
    spec = importlib.util.spec_from_file_location("direct_upload_submit_worker", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


worker = _load_worker()
_utils_spec = importlib.util.spec_from_file_location("direct_upload_worker_utils", Path(__file__).parents[1] / "utils" / "worker_utils.py")
worker_utils = importlib.util.module_from_spec(_utils_spec)
_utils_spec.loader.exec_module(worker_utils)


def _rclone_result(byte_count: int = 1) -> dict[str, object]:
    return {
        "bytes_transferred": byte_count,
        "checks": 0,
        "transfers": 1,
        "errors": 0,
        "stats_received": True,
    }


def _upload_context(tmp_path: Path, *, project_upload: bool) -> SimpleNamespace:
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"blend")
    archive = tmp_path / "render-input.zip"
    archive.write_bytes(b"archive")
    dependency = tmp_path / "texture.png"
    dependency.write_bytes(b"texture")
    filelist = tmp_path / "job-1.txt"
    filelist.write_text("texture.png\n", encoding="utf-8")

    run_rclone = mock.Mock(return_value=_rclone_result())
    logger = mock.MagicMock()
    logger._transfer_total = 0
    return SimpleNamespace(
        data={
            "job_id": "job-1", "storage_profile": "seaweed",
            "project": {
                "id": "project-1",
                "organization_id": "org-1",
                "sqid": "TestProject",
            },
            "packed_addons": [],
        },
        mods={
            "_build_base": mock.Mock(return_value=["rclone", "--config", "memory"]),
            "CLOUDFLARE_R2_DOMAIN": "account.r2.cloudflarestorage.com",
            "run_rclone": run_rclone,
        },
        logger=logger,
        session=mock.MagicMock(),
        report=mock.MagicMock(),
        rclone_bin="rclone",
        blend_path=str(blend),
        use_project=project_upload,
        zip_file=archive,
        filelist=filelist,
        project_name="job-1/input" if project_upload else "TestProject",
        job_id="job-1",
        rel_manifest=["texture.png"] if project_upload else [],
        dependency_total_size=dependency.stat().st_size if project_upload else 0,
        required_storage=archive.stat().st_size,
        common_path=str(tmp_path),
        main_blend_s3="scene.blend",
        phase_timings={},
    )


def _run_upload(ctx: SimpleNamespace) -> None:
    storage = {
                "endpoint_url": "https://storage.lab.invalid", "region": "us-east-1", "storage_profile": "seaweed",
                "bucket_name": "project-bucket",
                "access_key_id": "redacted",
                "secret_access_key": "redacted",
    }
    with (
        mock.patch.object(worker, "_job_storage_payload", return_value=storage),
        mock.patch.object(worker, "_nfc", side_effect=lambda value: value),
        mock.patch.object(
            worker,
            "_s3key_clean",
            side_effect=lambda value: str(value).replace("\\", "/"),
        ),
        mock.patch.object(worker, "_debug_enabled", return_value=False),
    ):
        worker._upload(ctx)


def test_zip_payload_moves_directly_to_selected_storage_with_rclone(tmp_path):
    ctx = _upload_context(tmp_path, project_upload=False)

    _run_upload(ctx)

    call = ctx.mods["run_rclone"].call_args_list[0]
    assert call.args[:4] == (
        ["rclone", "--config", "memory"],
        "move",
        str(ctx.zip_file),
        ":s3:project-bucket/",
    )
    assert call.kwargs["total_bytes"] == ctx.required_storage
    assert ctx.mods["_build_base"].call_args.args[1] == "https://storage.lab.invalid"
    assert ctx.data["storage_profile"] == "seaweed"
    ctx.session.put.assert_not_called()
    ctx.session.post.assert_not_called()
    ctx.session.request.assert_not_called()


def test_registration_posts_metadata_to_existing_farm_endpoint(tmp_path):
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"blend")
    response = mock.MagicMock()
    response.raise_for_status.return_value = None
    session = mock.MagicMock()
    session.post.return_value = response
    ctx = SimpleNamespace(
        data={
            "job_id": "job-1",
            "storage_profile": "seaweed",
            "project": {"id": "project-1"},
            "packed_addons": [],
            "job_name": "Direct R2 render",
            "start_frame": 1,
            "image_format": "SCENE",
            "use_scene_image_format": True,
            "render_engine": "CYCLES",
            "scene_metadata": {"resolution_x": 1920, "resolution_y": 1080},
            "blender_version": "blender52",
            "ignore_errors": False,
            "use_bserver": True,
            "farm_url": "https://farm.lab.invalid",
            "pocketbase_url": "https://api.lab.invalid",
        },
        logger=mock.MagicMock(),
        session=session,
        report=mock.MagicMock(),
        headers={"Authorization": "redacted"},
        blend_path=str(blend),
        use_project=False,
        org_id="org-1",
        project_name="TestProject",
        project_root_str=str(tmp_path),
        main_blend_s3="scene.blend",
        effective_end_frame=10,
        frame_step_val=1,
        render_order="LINEAR",
        render_tasks=[{"frame": 1}],
        required_storage=123,
        phase_timings={},
    )

    with (
        mock.patch.object(worker, "_nfc", side_effect=lambda value: value),
        mock.patch.object(
            worker,
            "_s3key_clean",
            side_effect=lambda value: str(value).replace("\\", "/"),
        ),
        mock.patch.object(worker, "_debug_enabled", return_value=False),
    ):
        worker._register_job(ctx)

    session.post.assert_called_once()
    call = session.post.call_args
    assert call.args[0] == "https://api.lab.invalid/api/farm/org-1/jobs"
    payload = json.loads(call.kwargs["data"])
    assert payload["job_data"]["id"] == "job-1"
    assert payload["job_data"]["project_id"] == "project-1"
    assert payload["job_data"]["storage_profile"] == "seaweed"
    assert payload["job_data"]["zip"] is True
    assert payload["job_data"]["main_file"] == "scene.blend"
    assert "upload_receipt" not in payload
    assert "quote_token" not in payload


@pytest.mark.parametrize("profile,provider,endpoint", [
    ("seaweed", "seaweedfs", "https://seaweed.lab.invalid"),
    ("r2", "r2", "https://account.r2.cloudflarestorage.com"),
])
@pytest.mark.parametrize("project_upload", [False, True])
def test_upload_pins_selected_job_storage_before_s3_bytes(tmp_path, profile, provider, endpoint, project_upload):
    ctx = _upload_context(tmp_path, project_upload=project_upload)
    ctx.data.update(pocketbase_url="https://api.lab.invalid", user_token="synthetic-token", storage_profile=profile)
    ctx.storage_future = ctx.storage_thread = None
    ctx.mods["prepare_job_storage"] = worker_utils.prepare_job_storage
    config = {"storage_profile": profile, "storage_provider": provider, "endpoint_url": endpoint,
              "region": "auto", "bucket_name": "job-bucket", "access_key_id": "synthetic",
              "secret_access_key": "synthetic", "binding_id": "job-binding"}
    ctx.session.post.return_value.json.return_value = config
    with mock.patch.object(worker, "_nfc", side_effect=lambda value: value), mock.patch.object(worker, "_s3key_clean", side_effect=lambda value: str(value).replace("\\", "/")), mock.patch.object(worker, "_debug_enabled", return_value=False):
        worker._upload(ctx)
    assert ctx.session.post.call_args.args == ("https://api.lab.invalid/api/farm/org-1/jobs/storage",)
    assert ctx.session.post.call_args.kwargs["json"] == {"project_id": "project-1", "job_id": "job-1", "storage_profile": profile}
    ctx.session.post.assert_called_once()
    ctx.session.put.assert_not_called()
    ctx.session.get.assert_not_called()
    assert ctx.mods["_build_base"].call_args.args[1] == endpoint
    assert ctx.data["storage_profile"] == profile
    if project_upload:
        destinations = [call.args[3] for call in ctx.mods["run_rclone"].call_args_list]
        assert destinations[0] == ":s3:job-bucket/job-1/input/scene.blend"
