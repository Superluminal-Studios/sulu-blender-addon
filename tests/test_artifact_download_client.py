from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

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
    return {"output_ref": "output", "logical_name": "frame0001.exr", "relative_path": "frame0001.exr", "layout": "attempt-1", "generation": "generation", "size": 8, "downloadable": True, **fields}


def setup(tmp_path, *, get=lambda *_args, **_options: Response(), tool=None, wait=lambda _: None):
    calls = []

    def default_tool(name, body):
        calls.append((name, body))
        if tool:
            return tool(name, body)
        return {"transfers": [{"output_ref": "output", "generation": "generation", "transfer_ref": "transfer", "href": "https://evil.invalid/steal", "expires_at": 9999999999}]}

    client = SimpleNamespace(base="https://api.example", headers={"Authorization": "private-token"}, session=SimpleNamespace(get=get), tool=default_tool)
    return module.ArtifactDownloader(client, "organization", "job", tmp_path, wait=wait), calls


@pytest.mark.parametrize("expiry", [1, True, float("nan")])
def test_invalid_or_expired_transfer_metadata_never_starts_a_byte_request(tmp_path, expiry):
    reads = []
    def tool(_name, _body):
        return {"transfers": [{"output_ref": "output", "generation": "generation", "transfer_ref": "transfer", "expires_at": expiry}]}
    downloader, _ = setup(tmp_path, tool=tool, get=lambda *_a, **_kw: reads.append(True))
    with pytest.raises(module.CoordinatorError):
        downloader.download(artifact())
    assert reads == []
    downloader.close()


def test_download_never_follows_external_url_and_durable_receipts_have_no_tokens(tmp_path):
    seen = []

    def get(address, **options):
        seen.append((address, options))
        return Response()

    downloader, calls = setup(tmp_path, get=get)
    target = downloader.download(artifact())
    assert target.read_bytes() == b"abcdefgh"
    assert seen[0][0] == "https://api.example/api/render/v1/transfers/d_transfer"
    assert seen[0][1]["allow_redirects"] is False
    assert seen[0][1]["headers"]["If-Match"] == '"generation"'
    assert "private-token" not in downloader.state_path.read_text()
    assert "https://" not in downloader.state_path.read_text()
    assert downloader.download(artifact()) == target
    assert len(calls) == 1  # Completed local files are not re-transferred per poll.


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


@pytest.mark.parametrize("response", [Response(status=412), Response(headers={"ETag": '"other"', "Content-Length": "8", "Content-Range": "bytes 0-7/8"}), Response(headers={"ETag": '"generation"', "Content-Length": "8", "Content-Range": "bytes 1-8/8"}), Response(headers={"ETag": '"generation"', "Content-Length": "8", "Content-Range": "bytes 0-7/8", "Content-Encoding": "gzip"}), Response(b"a" * 9)])
def test_changed_generation_invalid_ranges_and_oversized_body_are_not_committed(tmp_path, response):
    downloader, _ = setup(tmp_path, get=lambda *_args, **_kwargs: response)
    with pytest.raises(module.CoordinatorError):
        downloader.download(artifact())
    entries = [json.loads(row[0]) for row in downloader.receipts.execute("SELECT receipt FROM outputs")]
    assert entries[0]["offset"] == 0
    assert (tmp_path / entries[0]["local_path"]).read_bytes() == b""


def test_restart_rejects_modified_partial_bytes_even_if_size_matches(tmp_path):
    downloader, _ = setup(tmp_path)
    target = downloader.download(artifact())
    target.write_bytes(b"tampered")
    downloader.close()
    restarted, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="changed locally"):
        restarted.download(artifact())


def test_resume_discards_bytes_from_a_range_that_never_committed_its_receipt(tmp_path):
    downloader, _ = setup(tmp_path)
    target = downloader.download(artifact())
    identity = next(iter(downloader.active_outputs))
    entry = downloader._entry(identity)
    entry.update(offset=4, sha256=hashlib.sha256(b"abcd").hexdigest(), complete=False)
    downloader._save_entry(identity, entry)
    downloader.close()
    restarted, _ = setup(tmp_path, get=lambda *_args, **_kwargs: Response(b"efgh", headers={"ETag": '"generation"', "Content-Length": "4", "Content-Range": "bytes 4-7/8"}))
    assert restarted.download(artifact()).read_bytes() == b"abcdefgh"


@pytest.mark.parametrize("name", ["/x", "../x", "a/../x", "a//x", "a\\x", "C:/x", "a/./x", "a\nx", "a/"])
def test_path_escape_and_invalid_output_names_are_rejected(name):
    with pytest.raises(module.CoordinatorError):
        module.artifact_relative_path(artifact(relative_path=name))


def test_aliases_generations_unicode_and_windows_case_do_not_collide():
    names = ["A.exr", "a.exr", "%41.exr", "CON.txt", "con.txt", "雪.exr", "é.exr", "é.exr", "trailing."]
    paths = [str(module.artifact_relative_path(artifact(relative_path=name))) for name in names]
    assert len({path.casefold() for path in paths}) == len(names)
    assert module.artifact_relative_path(artifact(layout="other")) != module.artifact_relative_path(artifact())
    assert module.artifact_relative_path(artifact(generation="other")) != module.artifact_relative_path(artifact())


def test_catalog_iterates_all_pages_without_merging_distinct_aliases(tmp_path):
    pages = iter([
        {"outputs": [artifact(layout="legacy"), artifact(layout="attempt1")], "snapshot": "snapshot", "catalog_state": "terminal_snapshot", "next_cursor": "next"},
        {"outputs": [artifact(relative_path="report.txt"), artifact(relative_path="video.mp4")], "snapshot": "snapshot", "catalog_state": "terminal_snapshot", "next_cursor": None},
    ])
    downloader, calls = setup(tmp_path, tool=lambda _name, _body: next(pages))
    assert sum(len(page["outputs"]) for page in downloader.pages()) == 4
    assert [call[1].get("cursor") for call in calls] == [None, "next"]
    assert all(call[1]["limit"] == 200 for call in calls)


@pytest.mark.parametrize("changed", [False, True])
def test_repeated_cursor_or_changed_snapshot_is_not_silent_completion(tmp_path, changed):
    pages = iter([
        {"outputs": [], "snapshot": "snapshot", "catalog_state": "live", "next_cursor": "next"},
        {"outputs": [], "snapshot": "changed" if changed else "snapshot", "catalog_state": "live", "next_cursor": "next"},
    ])
    downloader, _ = setup(tmp_path, tool=lambda _name, _body: next(pages))
    with pytest.raises(module.CoordinatorError, match="OUTPUT_SETTLING"):
        list(downloader.pages())


def test_zero_byte_output_is_a_verified_empty_transfer(tmp_path):
    downloader, _ = setup(tmp_path, get=lambda *_args, **_kwargs: Response(b"", status=200, headers={"ETag": '"generation"', "Content-Length": "0"}))
    assert downloader.download(artifact(size=0)).read_bytes() == b""


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    try:
        (tmp_path / "attempt-1").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    downloader, _ = setup(tmp_path)
    with pytest.raises(module.CoordinatorError):
        downloader.download(artifact())
    assert not list(outside.iterdir())


def test_two_workers_cannot_mix_writes_in_one_destination(tmp_path):
    first, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="Another downloader"):
        setup(tmp_path)
    first.close()
    second, _ = setup(tmp_path)
    assert second.download(artifact()).read_bytes() == b"abcdefgh"


def test_video_sequence_can_span_immutable_task_layouts_but_never_guesses_retries(tmp_path):
    downloader, _ = setup(tmp_path)
    for number in range(1, 4):
        identity = str(number)
        downloader.active_outputs.add(identity)
        downloader._save_entry(identity, {"complete": True, "layout": f"attempt_{number}", "relative_path": f"composite/frame{number:04}.png", "local_path": f"attempt_{number}/generation/composite/frame{number:04}.png"})
    assert len(downloader.video_sequence({".png"})) == 3
    downloader.active_outputs.add("retry")
    downloader._save_entry("retry", {"complete": True, "layout": "attempt_retry", "relative_path": "composite/frame0001.png", "local_path": "attempt_retry/generation/composite/frame0001.png"})
    assert downloader.video_sequence({".png"}) == []
