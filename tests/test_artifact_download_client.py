from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

package = types.ModuleType("sulu_blender_addon")
package.__path__ = [str(Path(__file__).parents[1])]
sys.modules.setdefault("sulu_blender_addon", package)
module = importlib.import_module("sulu_blender_addon.transfers.download.artifact_client")


class Response:
    def __init__(self, data=b"abcdefgh", status=206, headers=None):
        self.data, self.status_code = data, status
        self.headers = headers if headers is not None else {"ETag": '"generation"', "Content-Length": "8", "Content-Range": "bytes 0-7/8"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, _):
        if isinstance(self.data, Exception):
            yield b"ab"
            raise self.data
        yield self.data


def artifact(**fields):
    return {"output_ref": "output", "logical_name": "frame0001.exr", "relative_path": "frame0001.exr", "layout": "attempt-1", "generation": "generation", "object_key": "job/output/_attempt_outputs/1/a/frame0001.exr", "etag": "generation", "size": 8, "downloadable": True, **fields}


def setup(tmp_path, *, get=lambda *_args, **_options: Response(), tool=None, wait=lambda _: None):
    calls = []

    def default_tool(name, body):
        calls.append((name, body))
        if tool:
            return tool(name, body)
        return {"transfers": [{"output_ref": "output", "generation": "generation", "transfer_ref": "transfer", "href": "https://evil.invalid/steal", "expires_at": 9999999999}]}

    client = SimpleNamespace(base="https://api.example", headers={"Authorization": "private-token"}, session=SimpleNamespace(get=lambda *_a, **_k: pytest.fail("API session cannot transfer output bytes")), tool=default_tool)
    storage = {"endpoint_url": "https://storage.example", "bucket_name": "job-bucket", "region": "auto", "access_key_id": "synthetic", "secret_access_key": "synthetic"}
    return module.ArtifactDownloader(client, "organization", "job", tmp_path, wait=wait, storage_loader=lambda: storage, storage_session=SimpleNamespace(get=get, close=lambda: None)), calls


def test_download_uses_direct_job_s3_and_durable_receipts_have_no_tokens(tmp_path):
    seen = []

    def get(address, **options):
        seen.append((address, options))
        return Response()

    downloader, calls = setup(tmp_path, get=get)
    target = downloader.download(artifact())
    assert target.read_bytes() == b"abcdefgh"
    assert seen[0][0].startswith("https://storage.example/job-bucket/job/output/_attempt_outputs/1/a/frame0001.exr?")
    assert "X-Amz-Signature=" in seen[0][0]
    assert seen[0][1]["allow_redirects"] is False
    assert seen[0][1]["headers"]["If-Match"] == '"generation"'
    assert "Authorization" not in seen[0][1]["headers"]
    assert "private-token" not in downloader.state_path.read_text()
    assert "https://" not in downloader.state_path.read_text()
    assert downloader.download(artifact()) == target
    assert len(calls) == 0


def test_interrupted_range_is_rolled_back_then_resumed_from_committed_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "CHUNK_BYTES", 4)
    seen = []
    replies = iter([
        Response(b"abcd", headers={"ETag": '"generation"', "Content-Length": "4", "Content-Range": "bytes 0-3/8"}),
        Response(requests.ConnectionError("private upstream"), headers={"ETag": '"generation"', "Content-Length": "4", "Content-Range": "bytes 4-7/8"}),
        Response(b"efgh", headers={"ETag": '"generation"', "Content-Length": "4", "Content-Range": "bytes 4-7/8"}),
    ])

    def get(_address, **options):
        seen.append(options["headers"]["Range"])
        return next(replies)

    downloader, _ = setup(tmp_path, get=get)
    assert downloader.download(artifact()).read_bytes() == b"abcdefgh"
    assert seen == ["bytes=0-3", "bytes=4-7", "bytes=4-7"]


def test_provider_etag_and_cached_job_credentials_cover_multiple_outputs(tmp_path):
    seen = []
    def get(address, **options):
        seen.append((address, options))
        return Response(headers={"ETag": '"opaque-storage-etag"', "Content-Length": "8", "Content-Range": "bytes 0-7/8"})
    downloader, calls = setup(tmp_path, get=get)
    downloader.storage_loader = Mock(wraps=downloader.storage_loader)
    first = artifact(generation="logical-generation", etag="opaque-storage-etag", version_id="version-one")
    second = artifact(output_ref="output-two", relative_path="frame0002.exr", object_key="job/output/_attempt_outputs/1/a/frame0002.exr", generation="another-generation", etag="opaque-storage-etag")
    downloader.download(first)
    downloader.download(second)
    downloader.storage_loader.assert_called_once()
    assert seen[0][1]["headers"]["If-Match"] == '"opaque-storage-etag"'
    assert "versionId=version-one" in seen[0][0]
    assert calls == []


@pytest.mark.parametrize("name", ["/x", "../x", "a/../x", "a//x", "a\\x", "C:/x", "a/./x", "a\nx", "a/"])
def test_path_escape_and_invalid_output_names_are_rejected(name):
    with pytest.raises(module.CoordinatorError):
        module.artifact_relative_path(artifact(relative_path=name))


