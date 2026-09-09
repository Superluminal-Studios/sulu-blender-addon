from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / relative)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


worker = load("coordinated_submit_test_worker", "transfers/submit/submit_worker.py")
contract = load("coordinated_submit_test_contract", "transfers/submit/coordinator_client.py")


def context(tmp_path, monkeypatch, *, project=True):
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"blend")
    dependency = tmp_path / "texture.png"
    dependency.write_bytes(b"image")
    archive = tmp_path / "packed.zip"
    archive.write_bytes(b"archive")
    project_record = {"id": "project-a", "organization_id": "org-a", "name": "Project A", "sqid": "ProjA"}
    data = {"project": project_record, "job_id": "local-intent", "job_name": "Render A", "start_frame": 1,
            "blender_version": "4.5.2", "image_format": "SCENE", "render_engine": "CYCLES",
            "use_scene_image_format": True, "packed_addons": [], "ignore_errors": False, "use_bserver": True}
    ctx = SimpleNamespace(data=data, mods={"pkg_name": "sulu_test"}, proj=project_record, org_id="org-a",
        use_project=project, blend_path=str(blend), zip_file=archive, common_path=str(tmp_path),
        project_root_str=str(tmp_path), main_blend_s3="scene.blend", rel_manifest=["texture.png"],
        effective_end_frame=10, frame_step_val=2, render_order="TEMPORAL_REFINE", logger=Mock(), report=Mock())
    monkeypatch.setattr(worker, "_nfc", lambda value: value)
    monkeypatch.setattr(worker, "_s3key_clean", lambda value: value.replace("\\", "/"))
    monkeypatch.setattr(worker.importlib, "import_module", lambda _: contract)
    return ctx


def test_project_and_zip_manifest_preserve_packaging_without_physical_keys(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    sources, manifest, mode = worker._receipt_input_files(ctx)
    assert mode == {"input_mode": "project", "main_file": "scene.blend"}
    assert {item["name"] for item in manifest} == {"scene.blend", "texture.png"}
    assert sources["texture.png"] == tmp_path / "texture.png"
    ctx.use_project = False
    sources, manifest, mode = worker._receipt_input_files(ctx)
    assert mode == {"input_mode": "zip", "main_file": "scene.blend", "archive_file": "render-input.zip"}
    assert manifest == [{"name": "render-input.zip", "size": 7}]


def test_packed_addons_are_exact_manifest_zip_names(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch, project=False)
    directory = tmp_path / "addons"
    directory.mkdir()
    (directory / "addon.zip").write_bytes(b"addon")
    ctx.data.update(packed_addons=["addon"], packed_addons_path=str(directory))
    _, manifest, mode = worker._receipt_input_files(ctx)
    assert mode["packed_addons"] == ["addons/addon.zip"]
    assert {item["name"] for item in manifest} == {"render-input.zip", "addons/addon.zip"}


def test_upload_finalize_verifies_every_declared_input_and_returns_receipt(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    client = Mock()
    client.completed.return_value = None
    client.mutate.side_effect = [
        {"upload_session": "session-a", "expires_at": 9999999999, "files": [
            {"name": "scene.blend", "size": 5, "file_ref": "file1"}, {"name": "texture.png", "size": 5, "file_ref": "file2"}]},
        {"upload_receipt": "receipt-a"},
    ]
    monkeypatch.setattr(worker, "_coordinator", lambda _: client)
    worker._upload(ctx)
    assert ctx.upload_receipt == "receipt-a"
    assert client.upload_file.call_count == 2
    assert client.mutate.call_args_list[1].args == ("render_upload_finalize", {"organization_id": "org-a", "upload_session": "session-a"})
    assert not ctx.report.method_calls[0].args or "token" not in str(ctx.report.method_calls)


def test_completed_upload_resume_does_not_reupload_expired_transfer(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    client = Mock()
    client.completed.return_value = {"upload_receipt": "receipt-a"}
    monkeypatch.setattr(worker, "_coordinator", lambda _: client)
    worker._upload(ctx)
    assert ctx.upload_receipt == "receipt-a"
    client.upload_file.assert_not_called()


def test_submission_preserves_artist_settings_and_uses_server_job_identity(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch, project=False)
    ctx.upload_receipt = "receipt-a"
    client = Mock()
    client.journal = {}
    client.completed.return_value = None
    client.tool.return_value = {"quote_token": "quote-a"}
    client.mutate.return_value = {"job_id": "durable-job"}
    monkeypatch.setattr(worker, "_coordinator", lambda _: client)
    worker._register_job(ctx)
    name, body = client.mutate.call_args.args
    assert name == "render_job_submit"
    assert body["template"]["zip"] is True
    assert body["template"]["image_format"] == "SCENE"
    assert body["template"]["render_order"] == "TEMPORAL_REFINE"
    assert body["template"]["frame_step"] == 2
    assert body["upload_receipt"] == "receipt-a" and body["quote_token"] == "quote-a"
    assert "job_data" not in body and "farm_url" not in body["template"]
    assert ctx.job_id == ctx.data["job_id"] == "durable-job"


def test_lost_acceptance_recovers_before_requoting_claimed_receipt(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    ctx.upload_receipt = "receipt-a"
    client = Mock()
    client.journal = {"render_job_submit": {"idempotency_key": "key"}}
    client.completed.return_value = None
    client.mutate.return_value = {"job_id": "durable-job"}
    monkeypatch.setattr(worker, "_coordinator", lambda _: client)
    worker._register_job(ctx)
    client.tool.assert_not_called()
    assert ctx.job_id == "durable-job"


def test_input_paths_cannot_escape_manifest_boundary(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    ctx.rel_manifest = ["../secrets.txt"]
    with pytest.raises(ValueError):
        worker._receipt_input_files(ctx)
