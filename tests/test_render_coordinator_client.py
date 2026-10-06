from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

spec = importlib.util.spec_from_file_location("render_coordinator_test_client", Path(__file__).parents[1] / "transfers/submit/coordinator_client.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Response:
    def __init__(self, data=None, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, _):
        yield json.dumps(self.data).encode()


def client(tmp_path, session, confirm=lambda *_: True, *, storage_session=None):
    return module.RenderCoordinatorClient("https://api.example", "private-token", session, tmp_path / "receipt.json", "stable-intent", confirm, sleep=lambda _: None, storage_session=storage_session)


def test_confirmation_and_lost_response_replay_keep_one_command(tmp_path):
    calls = []
    prepared = {"operation_id": "operation-a", "state": "confirmation_required", "confirmation_token": "private-confirmation", "impact": {"cost": 12}}
    result = {"operation_id": "operation-a", "state": "succeeded", "result": {"job_id": "job-a"}}
    replies = iter([prepared, requests.ConnectionError("private failure"), result])

    def post(path, **options):
        calls.append((path, options))
        response = next(replies)
        if isinstance(response, Exception):
            raise response
        return Response(response)

    session = SimpleNamespace(post=post)
    first = client(tmp_path, session)
    with pytest.raises(module.CoordinatorError, match="DEPENDENCY_UNAVAILABLE"):
        first.mutate("render_job_submit", {"organization_id": "org-a"})
    retained = (tmp_path / "receipt.json").read_text()
    assert "private" not in retained and "operation-a" in retained
    recovered = client(tmp_path, session)
    assert recovered.mutate("render_job_submit", {"organization_id": "org-a"}) == {"job_id": "job-a"}
    assert calls[0][1]["json"]["idempotency_key"] == calls[1][1]["json"]["idempotency_key"]
    assert calls[2][0].endswith("render_operation_get")
    assert all(call[1]["allow_redirects"] is False for call in calls)


def direct_descriptor(size=10):
    parts = [{"part_number": number, "offset": offset, "size": min(4, size-offset),
              "href": f"https://storage.example/bucket/input?uploadId=opaque&partNumber={number}",
              "method": "PUT", "headers": {"Content-Type": "application/octet-stream"}}
             for number, offset in enumerate(range(0, size, 4), 1)]
    return {"file_ref": "opaque123", "size": size, "part_count": len(parts), "parts": parts}


def test_direct_s3_upload_replaces_lost_part_without_application_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcdefghij")
    state = {"put": 0}
    pieces, paths = [], []

    def put(path, **kwargs):
        paths.append(path)
        assert kwargs["allow_redirects"] is False
        pieces.append(kwargs["data"])
        assert "Authorization" not in kwargs["headers"]
        assert "Content-Range" not in kwargs["headers"]
        state["put"] += 1
        if state["put"] == 1:
            raise requests.ConnectionError("lost response")
        return Response(status=200, headers={"ETag": '"opaque-etag"'})

    # No control-plane method exists: byte transfer cannot check its database.
    uploader = client(tmp_path, SimpleNamespace(), storage_session=SimpleNamespace(put=put))
    assert uploader.upload_file(source, direct_descriptor()) == 10
    assert pieces == [b"abcd", b"abcd", b"efgh", b"ij"]
    assert paths[0] == paths[1]
    assert all(path.startswith("https://storage.example/") for path in paths)
    assert not (tmp_path / "receipt.json").exists()


def test_direct_s3_collects_complete_plan_before_first_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcdefghij")
    descriptor = direct_descriptor()
    rest = descriptor["parts"][1:]
    descriptor["parts"] = descriptor["parts"][:1]
    descriptor["parts_href"] = "/api/render/v1/uploads/session1/parts/opaque123?start=2"
    events = []

    def get(path, **options):
        events.append("plan")
        assert options["headers"]["Authorization"] == "private-token"
        return Response({"file_ref": "opaque123", "part_count": 3, "parts": rest})

    def put(path, **options):
        events.append("bytes")
        assert "Authorization" not in options["headers"]
        return Response(status=200, headers={"ETag": '"opaque"'})

    assert client(tmp_path, SimpleNamespace(get=get), storage_session=SimpleNamespace(put=put)).upload_file(source, descriptor) == 10
    assert events == ["plan", "bytes", "bytes", "bytes"]


def test_upload_rejects_generation_mismatch_and_changed_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcd")
    session = SimpleNamespace()
    with pytest.raises(module.CoordinatorError, match="GENERATION_CHANGED"):
        client(tmp_path, session).upload_file(source, direct_descriptor(5))
    with pytest.raises(module.CoordinatorError, match="GENERATION_CHANGED"):
        client(tmp_path, session).upload_file(source, {"file_ref": "opaque", "size": 4})

    def changed():
        source.write_bytes(b"changed")

    with pytest.raises(module.CoordinatorError, match="GENERATION_CHANGED"):
        client(tmp_path, session).upload_file(source, direct_descriptor(4), before_chunk=changed)


@pytest.mark.parametrize("change", ["api-url", "canonical-api-url", "authorization", "gap", "missing-part", "http", "boolean-size", "boolean-part", "malformed-part"])
def test_invalid_direct_plan_cannot_start_upload(tmp_path, monkeypatch, change):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcdefghij")
    descriptor = direct_descriptor()
    if change == "api-url": descriptor["parts"][0]["href"] = "https://api.example/api/render/v1/transfers/u_opaque123"
    if change == "canonical-api-url": descriptor["parts"][0]["href"] = "https://API.EXAMPLE:443/input"
    if change == "authorization": descriptor["parts"][0]["headers"]["Authorization"] = "private-token"
    if change == "gap": descriptor["parts"][1]["offset"] = 5
    if change == "missing-part": descriptor["parts"].pop()
    if change == "http": descriptor["parts"][0]["href"] = "http://storage.example/input"
    if change == "boolean-size": descriptor["size"] = True
    if change == "boolean-part": descriptor["parts"][0]["part_number"] = True
    if change == "malformed-part": descriptor["parts"][0] = None
    with pytest.raises(module.CoordinatorError, match="GENERATION_CHANGED"):
        client(tmp_path, SimpleNamespace(), storage_session=SimpleNamespace()).upload_file(source, descriptor)


@pytest.mark.parametrize("failure", ["empty-page", "nonadvancing-page"])
def test_direct_upload_rejects_plan_pages_without_progress_before_bytes(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcdefghij")
    descriptor = direct_descriptor()
    descriptor["parts"] = descriptor["parts"][:1]
    descriptor["parts_href"] = "/api/render/v1/uploads/session1/parts/opaque123?start=2"
    requests_seen = []

    def get(path, **_options):
        requests_seen.append(path)
        return Response({"file_ref": "opaque123", "part_count": 3,
                         "parts": [] if failure == "empty-page" else direct_descriptor()["parts"][1:2],
                         "parts_href": "/api/render/v1/uploads/session1/parts/opaque123?start=2"})

    # A malformed plan must stop before storage is contacted.
    with pytest.raises(module.CoordinatorError):
        client(tmp_path, SimpleNamespace(get=get), storage_session=SimpleNamespace()).upload_file(source, descriptor)
    assert len(requests_seen) == 1


@pytest.mark.parametrize("name", ["../x", "a/../x", "/x", "a//x", "a\\x", "C:/x", "a\nx", "./x"])
def test_logical_paths_reject_escape_inputs(name):
    with pytest.raises(ValueError):
        module.logical_name(name)


def test_zero_size_input_needs_no_put(tmp_path):
    source = tmp_path / "empty.txt"
    source.write_bytes(b"")
    assert client(tmp_path, SimpleNamespace(), storage_session=SimpleNamespace()).upload_file(source, direct_descriptor(0)) == 0


@pytest.mark.parametrize("contamination", ["bearer", "cookies", "auth", "control-session"])
def test_direct_upload_rejects_transport_that_could_forward_credentials(tmp_path, monkeypatch, contamination):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcd")
    control, storage = requests.Session(), requests.Session()
    if contamination == "bearer": storage.headers["Authorization"] = "private-token"
    if contamination == "cookies": storage.cookies.set("pb_auth", "private-cookie")
    if contamination == "auth": storage.auth = ("private-user", "private-password")
    if contamination == "control-session": storage = control
    with pytest.raises(module.CoordinatorError, match="DEPENDENCY_UNAVAILABLE"):
        client(tmp_path, control, storage_session=storage).upload_file(source, direct_descriptor(4))
    control.close(); storage.close()


def test_direct_upload_does_not_load_environment_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcd")
    storage = requests.Session()
    def put(*_args, **options):
        assert storage.trust_env is False
        assert "Authorization" not in options["headers"]
        return Response(status=200, headers={"ETag": '"opaque"'})
    storage.put = put
    assert client(tmp_path, SimpleNamespace(), storage_session=storage).upload_file(source, direct_descriptor(4)) == 4
    storage.close()


def test_direct_upload_sanitizes_missing_source(tmp_path):
    with pytest.raises(module.CoordinatorError, match="GENERATION_CHANGED") as caught:
        client(tmp_path, SimpleNamespace()).upload_file(tmp_path / "private-filename.blend", direct_descriptor(4))
    assert "private-filename" not in str(caught.value)
