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


def client(tmp_path, session, confirm=lambda *_: True):
    return module.RenderCoordinatorClient("https://api.example", "private-token", session, tmp_path / "receipt.json", "stable-intent", confirm, sleep=lambda _: None)


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


def test_resumable_upload_recovers_lost_put_and_never_follows_returned_href(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    source = tmp_path / "input.blend"
    source.write_bytes(b"abcdefghij")
    state = {"offset": 0, "put": 0}
    pieces, paths = [], []

    def head(path, **kwargs):
        paths.append(path)
        assert kwargs["allow_redirects"] is False
        return Response(headers={"Upload-Offset": str(state["offset"]), "Upload-Length": "10"})

    def put(path, **kwargs):
        paths.append(path)
        assert kwargs["allow_redirects"] is False
        pieces.append(kwargs["data"])
        state["offset"] += len(kwargs["data"])
        state["put"] += 1
        if state["put"] == 1:
            raise requests.ConnectionError("lost response")
        return Response(status=204)

    uploader = client(tmp_path, SimpleNamespace(head=head, put=put))
    assert uploader.upload_file(source, {"file_ref": "opaque123", "size": 10, "href": "https://evil.example/steal"}) == 10
    assert pieces == [b"abcd", b"efgh", b"ij"]
    assert all(path == "https://api.example/api/render/v1/transfers/u_opaque123" for path in paths)


@pytest.mark.parametrize("name", ["../x", "a/../x", "/x", "a//x", "a\\x", "C:/x", "a\nx", "./x"])
def test_logical_paths_reject_escape_inputs(name):
    with pytest.raises(ValueError):
        module.logical_name(name)


