"""Submit worker contract: provider pin, direct bytes, receipt, and backend ID."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

import pytest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


root = Path(__file__).parents[1]
worker = load("submission_boundary_worker", root / "transfers/submit/submit_worker.py")
coordinator = load("submission_boundary.transfers.submit.coordinator_client", root / "transfers/submit/coordinator_client.py")


class Response:
    def __init__(self, value=None, status=200, headers=None):
        self.value, self.status_code, self.headers = value, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, _):
        yield json.dumps(self.value).encode()


@pytest.mark.parametrize("profile,provider,host", [
    ("selected-r2", "r2", "account.r2.cloudflarestorage.com"),
    ("selected-seaweed", "seaweedfs", "seaweed.example"),
])
def test_submission_uses_selected_profile_and_direct_storage_before_receipt(tmp_path, monkeypatch, profile, provider, host):
    monkeypatch.setattr(coordinator, "CHUNK_BYTES", 4)
    scene = tmp_path / "scene.blend"
    scene.write_bytes(b"blend")
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"archive")
    addons = tmp_path / "addons"
    addons.mkdir()
    (addons / "tool.zip").write_bytes(b"addon")
    trace, parts_by_ref, intended = [], {}, {}
    confirmed = set()

    def descriptor(item, number):
        ref = "file" + str(number)
        parts = [{"part_number": part, "offset": offset, "size": min(4, item["size"] - offset),
                  "href": f"https://{host}/bucket/input?uploadId={ref}&partNumber={part}",
                  "method": "PUT", "headers": {}} for part, offset in enumerate(range(0, item["size"], 4), 1)]
        parts_by_ref[ref] = parts
        return {"file_ref": ref, **item, "part_count": len(parts), "parts": parts[:1],
                "parts_href": f"/api/render/v1/uploads/session/parts/{ref}?start=2"}

    def post(url, **options):
        body = options["json"]
        trace.append(("control", url, body))
        assert options["headers"] == {"Authorization": "synthetic-session"}
        assert options["allow_redirects"] is False
        if url.endswith("render_capacity_get"):
            assert body == {"organization_id": "org"}
            return Response({"available": True})
        if url.endswith("render_job_quote"):
            assert body["upload_receipt"] == "verified-receipt"
            assert body["template"]["storage_profile"] == profile
            return Response({"quote_token": "synthetic-quote", "balance_sufficient": True})
        if url.endswith("/api/blender_schemas"):
            assert body["schema_key"] == "bl520-0123456789abcdef"
            return Response({"registered": True})
        stage = url.rsplit("/", 1)[-1]
        assert stage in {"render_upload_prepare", "render_upload_finalize", "render_job_submit"}
        if stage not in confirmed:
            confirmed.add(stage)
            intended[stage] = {key: value for key, value in body.items() if key != "confirmation_token"}
            return Response({"operation_id": stage, "state": "confirmation_required", "confirmation_token": "synthetic-confirmation", "impact": {}})
        assert body["confirmation_token"] == "synthetic-confirmation"
        assert {key: value for key, value in body.items() if key != "confirmation_token"} == intended[stage]
        if stage == "render_upload_prepare":
            assert body["storage_profile"] == profile
            assert body["main_file"] == "scene.blend" and body["input_mode"] == "zip"
            assert body["archive_file"] == "render-input.zip" and body["packed_addons"] == ["addons/tool.zip"]
            value = {"storage_profile": profile, "storage_provider": provider, "upload_session": "session",
                     "upload_method": "direct_s3_multipart", "files": [descriptor(item, number) for number, item in enumerate(body["files"], 1)]}
        elif stage == "render_upload_finalize":
            assert body["upload_session"] == "session"
            value = {"upload_receipt": "verified-receipt"}
        else:
            assert body["quote_token"] == "synthetic-quote"
            template = body["template"]
            assert template["name"] == "Classroom" and template["frame_start"] == 1 and template["frame_end"] == 200
            assert template["storage_profile"] == profile and template["scene_metadata"]["samples"] == 16
            assert "settings_schema" not in template["scene_metadata"]
            assert template["settings_schema_key"] == "bl520-0123456789abcdef"
            assert "id" not in template and "job_id" not in body
            value = {"job_id": "server-created-job"}
        return Response({"operation_id": stage, "state": "succeeded", "result": value})

    def get(url, **options):
        trace.append(("plan", url, None))
        ref = url.split("?")[0].rsplit("/", 1)[-1]
        return Response({"file_ref": ref, "part_count": len(parts_by_ref[ref]), "parts": parts_by_ref[ref][1:]})

    def put(url, **options):
        trace.append(("bytes", url, options["data"]))
        assert options["headers"] == {} and options["allow_redirects"] is False
        assert host in url
        return Response(headers={"ETag": '"provider-etag"'})

    client = coordinator.RenderCoordinatorClient("https://api.example", "synthetic-session", SimpleNamespace(post=post, get=get),
                                                tmp_path / "journal.json", "immutable-local-intent", lambda *_: True,
                                                sleep=lambda _: None, storage_session=SimpleNamespace(put=put))
    data = {"job_id": "local-intent", "storage_profile": profile, "job_name": "Classroom", "blender_version": "blender52",
            "start_frame": 1, "image_format": "SCENE", "render_engine": "CYCLES", "use_bserver": False,
            "packed_addons": ["tool"], "packed_addons_path": str(addons), "project": {"id": "project"},
            "scene_metadata": {"samples": 16, "settings_schema": {"private": "embedded"}},
            "settings_schema_key": "bl520-0123456789abcdef",
            "settings_schema": {"schema_version": 1, "blender_version": "5.2.0", "groups": []}}
    ctx = SimpleNamespace(data=data, proj={"id": "project"}, org_id="org", mods={"pkg_name": "submission_boundary"},
                          logger=mock.MagicMock(), report=mock.MagicMock(), phase_timings={}, use_project=False,
                          blend_path=str(scene), project_root_str=str(tmp_path), zip_file=archive,
                          effective_end_frame=200, frame_step_val=1, render_order="LINEAR")
    monkeypatch.setattr(worker, "_coordinator", lambda _: client)
    monkeypatch.setattr(worker, "_nfc", lambda value: value)
    client.tool("render_capacity_get", {"organization_id": "org"})
    worker._upload(ctx)
    worker._register_job(ctx)
    assert data["job_id"] == ctx.job_id == "server-created-job"
    assert data["storage_profile"] == profile and data["render_coordinator"] is True
    first = next(index for index, item in enumerate(trace) if item[0] == "bytes")
    last = max(index for index, item in enumerate(trace) if item[0] == "bytes")
    assert sum(item[0] == "plan" for item in trace[:first]) == 2
    assert all(item[0] == "bytes" for item in trace[first:last + 1])
    assert b"".join(item[2] for item in trace if item[0] == "bytes") == b"archiveaddon"
    retained = (tmp_path / "journal.json").read_text()
    assert "synthetic-session" not in retained and "synthetic-confirmation" not in retained


def test_retained_upload_cannot_be_reused_with_changed_storage(tmp_path, monkeypatch):
    client = SimpleNamespace(completed=lambda stage: {"upload_receipt": "original-receipt"} if stage == "render_upload_finalize" else {"storage_profile": "original-r2"})
    monkeypatch.setattr(worker, "_coordinator", lambda _: client)
    ctx = SimpleNamespace(data={"storage_profile": "different-seaweed"})
    with pytest.raises(ValueError, match="retained upload uses different storage"):
        worker._upload(ctx)
    assert not hasattr(ctx, "upload_receipt")
