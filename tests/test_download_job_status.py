"""Download/status boundary tests for authenticated backend reads and signed bytes."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_worker_module():
    name = "_test_download_worker"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, REPO_ROOT / "transfers/download/download_worker.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class _Response:
    def __init__(self, body=None, *, status=200, content=b"frame"):
        self.status_code = status
        self.payload = {"status": "success", "body": body}
        self.content = content

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, _chunk_size):
        yield self.content


def _source(number):
    return {
        "key": f"job-1/output/composite/{number:04}.png",
        "frame": f"{number:04}",
        "size": 5,
        "last_modified": 1_700_000_000_123,
    }


class _BackendSession:
    def __init__(self, *, manifests=None, statuses=None):
        self.calls = []
        self.manifests = iter(manifests or [[_source(1)]])
        self.statuses = iter(statuses or [("running", 1, 2)])
        self.byte_failure = False
        self.downloaded = []
        self.contents = {}
        self.lock = threading.Lock()
        self.signatures = 0
        self.expires_in = 600

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/source_manifest"):
            page = next(self.manifests)
            return _Response(page if isinstance(page, dict) else {"files": page, "nextCursor": "", "truncated": False})
        if url.endswith("/source_urls"):
            self.signatures += 1
            body = {"urls": [
                {**source, "url": "https://storage.example/" + source["key"] + f"?signature=private-{self.signatures}"}
                for source in kwargs["json"]["sources"]
            ]}
            if self.expires_in is not None:
                body["expires_in"] = self.expires_in
            return _Response(body)
        if url.endswith("/api/jobs/org-1/job-1"):
            status, finished, total = next(self.statuses)
            return _Response({"job_data": {
                "status": status, "tasks": {"finished": finished}, "total_tasks": total,
            }})
        raise AssertionError("Unexpected request destination")

    def get(self, url, **kwargs):
        key = urlsplit(url).path.lstrip("/")
        with self.lock:
            self.calls.append(("GET", url, kwargs))
            if self.byte_failure:
                raise requests.ConnectionError("Private signed URL: " + url)
            content = self.contents.get(key, b"frame")
            self.downloaded.append(url)
        return _Response(content=content)


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DownloadBackendBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.worker = _load_worker_module()
        self.worker.data = {
            "pocketbase_url": "https://api.superlumin.al",
            "user_token": "session-fixture",
            "project": {"id": "project-1", "organization_id": "org-1"},
            # Old handoffs are accepted, but neither the key nor the snapshot
            # may replace backend authorization or current status.
            "sarfis_url": "https://queue.invalid/farm/org-1",
            "sarfis_token": "retired-key-fixture",
            "job": {"status": "finished", "total_tasks": 50},
        }
        self.worker.job_id = "job-1"
        self.worker.logger = MagicMock()
        self.worker._download_actions = None
        self.worker._SKIPPED_OUTPUTS_WARNED = False
        self.backend = _BackendSession()
        self.worker.session = self.backend
        self.session_type = requests.Session

        def new_object_session():
            objects = self.session_type()
            objects.get = self.backend.get
            return objects

        patcher = patch.object(self.worker.requests, "Session", side_effect=new_object_session)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.retry_wait = patch.object(self.worker, "_wait_for_download_actions")
        self.retry_wait.start()
        self.addCleanup(self.retry_wait.stop)

    def assert_authenticated_backend_calls(self):
        for _method, url, kwargs in self.backend.calls:
            self.assertNotIn("render_queues", url)
            self.assertNotIn("queue.invalid", url)
            self.assertNotIn("Auth-Token", kwargs["headers"])
            if url.startswith("https://api.superlumin.al/"):
                self.assertEqual(kwargs["headers"], {"Authorization": "session-fixture"})
            else:
                self.assertNotIn("Authorization", kwargs["headers"])
            self.assertIs(kwargs["allow_redirects"], False)

    def test_single_download_uses_backend_manifest_and_scoped_source_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            outcome = self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(outcome, "available")
            self.assertEqual((Path(directory) / "composite/0001.png").read_bytes(), b"frame")
        self.assertEqual([call[1].split("?")[0] for call in self.backend.calls], [
            "https://api.superlumin.al/api/jobs/org-1/job-1/source_manifest",
            "https://api.superlumin.al/api/jobs/org-1/job-1/source_urls",
            "https://storage.example/job-1/output/composite/0001.png",
        ])
        self.assertEqual(self.backend.calls[1][2]["json"], {"sources": [
            {"frame": "0001", "key": "job-1/output/composite/0001.png"}
        ]})
        self.assert_authenticated_backend_calls()

    def test_manifest_pagination_follows_opaque_cursors_even_after_empty_pages(self):
        self.backend.manifests = iter([
            {"files": [_source(1)], "nextCursor": "opaque %+==", "truncated": True},
            {"files": [], "nextCursor": "next /+==", "truncated": True},
            {"files": [_source(2)], "nextCursor": "", "truncated": False},
        ])
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual((Path(directory) / "composite/0001.png").read_bytes(), b"frame")
            self.assertEqual((Path(directory) / "composite/0002.png").read_bytes(), b"frame")
        pages = [call[2]["params"] for call in self.backend.calls if call[1].endswith("/source_manifest")]
        self.assertEqual(pages, [
            {"cursor": "", "limit": 2000},
            {"cursor": "opaque %+==", "limit": 2000},
            {"cursor": "next /+==", "limit": 2000},
        ])
        self.assert_authenticated_backend_calls()

    def test_same_size_rerender_refreshes_bytes_and_mtime_then_resumes_without_fetching(self):
        old = _source(1)
        new = {**old, "last_modified": old["last_modified"] + 4000}
        self.backend.manifests = iter([[new], [new]])
        self.backend.contents[new["key"]] = b"newer"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "composite/0001.png"
            target.parent.mkdir()
            target.write_bytes(b"older")
            old_ns = old["last_modified"] * 1_000_000
            os.utime(target, ns=(old_ns, old_ns))
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(target.read_bytes(), b"newer")
            self.assertEqual(target.stat().st_mtime_ns // 1_000_000, new["last_modified"])
            self.worker._run_selected_downloader(directory, "single")
        self.assertEqual(len(self.backend.downloaded), 1)
        self.assertEqual(sum(url.endswith("/source_urls") for _method, url, _kwargs in self.backend.calls), 1)

    def test_finished_auto_download_resumes_on_a_filesystem_with_one_second_mtimes(self):
        source = _source(1)
        self.backend.manifests = iter([[source], [source]])
        self.backend.statuses = iter([("finished", 1, 1)])
        real_utime = os.utime

        def round_mtime(path, times=None, *, ns=None):
            if ns is None:
                return real_utime(path, times)
            rounded = tuple(value // 1_000_000_000 * 1_000_000_000 for value in ns)
            return real_utime(path, ns=rounded)

        clock = _FakeClock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.worker.os, "utime", side_effect=round_mtime), \
             patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(self.worker, "_wait_for_download_actions", side_effect=clock.sleep):
            outcome = self.worker.auto_downloader(directory, poll_seconds=5)
            self.assertEqual(outcome, "finished")
            target = Path(directory) / "composite/0001.png"
            self.assertEqual(target.read_bytes(), b"frame")
            self.assertNotEqual(target.stat().st_mtime_ns // 1_000_000, source["last_modified"])
        self.assertEqual(len(self.backend.downloaded), 1)
        self.assertEqual(self.backend.signatures, 1)

    def test_failed_signed_download_preserves_local_file_and_redacts_url(self):
        self.backend.byte_failure = True
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "composite/0001.png"
            target.parent.mkdir()
            target.write_bytes(b"previous")
            with self.assertRaisesRegex(RuntimeError, "Check your connection") as raised:
                self.worker._run_selected_downloader(directory, "single")
            self.assertNotIn("signature", str(raised.exception))
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertEqual(list(target.parent.iterdir()), [target])
        self.assert_authenticated_backend_calls()

    def test_auto_download_waits_for_late_terminal_outputs_without_refetching_complete_files(self):
        self.backend = _BackendSession(
            statuses=[("running", 1, 3), ("running", 2, 3), ("finished", 3, 3)],
            manifests=[
                [_source(1)], [_source(1), _source(2)],
                [_source(1), _source(2), _source(3)],
                [_source(1), _source(2), _source(3)],
            ],
        )
        self.worker.session = self.backend
        clock = _FakeClock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(self.worker, "_wait_for_download_actions", side_effect=clock.sleep):
            outcome = self.worker.auto_downloader(
                directory, poll_seconds=5, batch_frames=2, batch_seconds=60,
                refresh_seconds=60, terminal_stable_passes=1, terminal_settle_seconds=30,
            )
            self.assertEqual(outcome, "finished")
            self.assertEqual(sorted(path.name for path in Path(directory).rglob("*.png")),
                             ["0001.png", "0002.png", "0003.png"])
        self.assertEqual(len(self.backend.downloaded), 3)
        self.worker.logger.success.assert_called_once_with("3 frames downloaded")
        self.assert_authenticated_backend_calls()


if __name__ == "__main__":
    unittest.main()
