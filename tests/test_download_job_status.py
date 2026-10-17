"""Download/status boundary tests for authenticated backend reads and signed bytes."""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import urlsplit
from contextlib import redirect_stdout
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
        self.denied = False
        self.byte_failure = False
        self.downloaded = []
        self.failures_remaining = {}
        self.contents = {}
        self.object_statuses = {}
        self.before_get = lambda _key: None
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.signatures = 0
        self.expires_in = 600

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.denied:
            return _Response(status=403)
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
            self.active += 1
            self.max_active = max(self.active, self.max_active)
        try:
            self.before_get(key)
            with self.lock:
                remaining = self.failures_remaining.get(key, 0)
                if remaining:
                    self.failures_remaining[key] -= 1
                if self.byte_failure or remaining:
                    raise requests.ConnectionError("Private signed URL: " + url)
                statuses = self.object_statuses.get(key, [])
                status = statuses.pop(0) if statuses else 200
                contents = self.contents.get(key, b"frame")
                content = contents.pop(0) if isinstance(contents, list) else contents
                if status == 200:
                    self.downloaded.append(url)
            return _Response(status=status, content=content)
        finally:
            with self.lock:
                self.active -= 1


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
        self.sessions = []
        self.session_type = requests.Session

        def new_object_session():
            objects = self.session_type()
            objects.get = self.backend.get
            self.sessions.append(objects)
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

    def test_status_uses_authenticated_stored_job_instead_of_old_queue_or_snapshot(self):
        self.assertEqual(self.worker._fetch_job_details(), ("running", 1, 2))
        self.assertEqual(self.backend.calls[0][1], "https://api.superlumin.al/api/jobs/org-1/job-1")
        self.assert_authenticated_backend_calls()

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

    def test_denial_stops_status_and_download_without_using_old_handoff(self):
        self.backend.denied = True
        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            self.worker._fetch_job_details()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(len(self.backend.calls), 2)
        self.assert_authenticated_backend_calls()

    def test_debug_download_logs_omit_signed_query_and_session_credentials(self):
        spec = importlib.util.spec_from_file_location(
            "_signed_download_timing", REPO_ROOT / "utils/worker_utils.py"
        )
        utilities = importlib.util.module_from_spec(spec)
        with patch.object(requests, "Session", self.session_type):
            spec.loader.exec_module(utilities)

        def send(method, url, **kwargs):
            if url.startswith("https://api.superlumin.al/"):
                return self.backend.request(method, url, **kwargs)
            return self.backend.get(url, **kwargs)

        output = io.StringIO()
        with utilities.TimingSession() as transport, tempfile.TemporaryDirectory() as directory, \
             patch.object(self.session_type, "request", side_effect=send), \
             patch.object(utilities, "DEBUG_MODE", True), redirect_stdout(output):
            self.worker.session = transport
            self.worker._run_selected_downloader(directory, "single")
        self.assertIn("/api/jobs/org-1/job-1/source_urls", output.getvalue())
        self.assertNotIn("signature=", output.getvalue())
        self.assertNotIn("session-fixture", output.getvalue())
        self.assertNotIn("retired-key-fixture", output.getvalue())

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

    def test_resume_skips_complete_local_files_without_signing_or_fetching_them(self):
        self.backend.manifests = iter([[_source(1), _source(2)]])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "composite"
            root.mkdir()
            (root / "0001.png").write_bytes(b"local")
            (root / "0002.png").write_bytes(b"local")
            modified_ns = _source(1)["last_modified"] * 1_000_000
            os.utime(root / "0001.png", ns=(modified_ns, modified_ns))
            os.utime(root / "0002.png", ns=(modified_ns, modified_ns))
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual((root / "0001.png").read_bytes(), b"local")
            self.assertEqual((root / "0002.png").read_bytes(), b"local")
        self.assertEqual([url for _method, url, _kwargs in self.backend.calls], [
            "https://api.superlumin.al/api/jobs/org-1/job-1/source_manifest"
        ])
        self.assertEqual(self.sessions, [])

    def test_foreign_job_keys_are_skipped_and_backend_formats_are_kept(self):
        own = {**_source(1), "key": "job-1/output/compositor/frame0001.jxl"}
        foreign = {**_source(2), "key": "input-job/output/composite/0002.png"}
        self.backend.manifests = iter([[foreign, own]])
        self.worker.data["debug_mode"] = True
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual((Path(directory) / "compositor/frame0001.jxl").read_bytes(), b"frame")
            self.assertEqual(list(Path(directory).rglob("0002.png")), [])
        issued = [source["key"] for _method, url, kwargs in self.backend.calls
                  if url.endswith("/source_urls") for source in kwargs["json"]["sources"]]
        self.assertEqual(issued, [own["key"]])
        self.worker.logger.info.assert_called()
        self.assert_authenticated_backend_calls()

    def test_failed_files_get_fresh_urls_while_successful_files_are_not_repeated(self):
        self.backend.manifests = iter([[_source(1), _source(2)]])
        self.backend.failures_remaining[_source(2)["key"]] = 1
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual((Path(directory) / "composite/0002.png").read_bytes(), b"frame")
        issued = [kwargs["json"]["sources"] for _method, url, kwargs in self.backend.calls
                  if url.endswith("/source_urls")]
        self.assertEqual(issued, [
            [{"frame": "0001", "key": _source(1)["key"]}, {"frame": "0002", "key": _source(2)["key"]}],
            [{"frame": "0002", "key": _source(2)["key"]}],
        ])
        failed_urls = [url for _method, url, _kwargs in self.backend.calls
                       if url.startswith("https://storage.example/") and "/0002.png?" in url]
        self.assertEqual(len(set(failed_urls)), 2)
        self.assertEqual(len(self.backend.downloaded), 2)
        self.assert_authenticated_backend_calls()

    def test_sliding_transfers_start_later_files_while_an_earlier_file_is_still_pending(self):
        self.backend.manifests = iter([[_source(number) for number in range(1, 12)]])
        later_started = threading.Event()

        def keep_first_pending(key):
            number = int(Path(key).stem)
            if number == 1:
                if not later_started.wait(timeout=3):
                    raise AssertionError("Later files could not start while an earlier transfer was pending")
            elif number > 8:
                later_started.set()

        self.backend.before_get = keep_first_pending
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(len(list(Path(directory).rglob("*.png"))), 11)
        self.assertTrue(later_started.is_set())
        self.assertGreater(self.backend.max_active, 1)
        self.assertLessEqual(self.backend.max_active, 8)
        batches = [kwargs["json"]["sources"] for _method, url, kwargs in self.backend.calls
                   if url.endswith("/source_urls")]
        self.assertTrue(any(len(batch) > 1 for batch in batches))
        self.assertTrue(all(len(batch) <= 100 for batch in batches))
        progress = [call.args for call in self.worker.logger.transfer_progress.call_args_list]
        self.assertTrue(all(total == 55 and 0 <= count <= total for count, total in progress))
        self.assertEqual(progress[-1], (55, 55))
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

    def test_invalid_source_mtime_fails_before_signing_or_overwriting_local_files(self):
        source = {**_source(1), "last_modified": 0}
        self.backend.manifests = iter([[source]])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "composite/0001.png"
            target.parent.mkdir()
            target.write_bytes(b"older")
            with self.assertRaisesRegex(RuntimeError, "Invalid output modification time"):
                self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(target.read_bytes(), b"older")
        self.assertEqual(self.backend.signatures, 0)
        self.assertEqual(self.sessions, [])

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

    def test_auto_404_recovers_before_five_deferrals_even_after_settle_deadline(self):
        source = _source(1)
        self.backend.manifests = iter([[source]] * 6)
        self.backend.statuses = iter([("finished", 1, 1)])
        self.backend.object_statuses[source["key"]] = [404] * 4 + [200]
        clock = _FakeClock()
        fetch_times = []
        self.backend.before_get = lambda _key: fetch_times.append(clock.now)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(self.worker, "_wait_for_download_actions", side_effect=clock.sleep):
            outcome = self.worker.auto_downloader(directory, poll_seconds=10, terminal_settle_seconds=30)
            self.assertEqual(outcome, "finished")
            self.assertEqual((Path(directory) / "composite/0001.png").read_bytes(), b"frame")
        self.assertGreater(clock.now, 30)
        self.assertGreater(fetch_times[-1], 30)
        self.assertEqual(len(self.backend.downloaded), 1)
        self.assert_authenticated_backend_calls()

    def test_auto_download_ends_incomplete_and_names_file_after_five_consecutive_deferrals(self):
        source = _source(1)
        self.backend.manifests = iter([[source]] * 5)
        self.backend.statuses = iter([("finished", 1, 1)])
        self.backend.object_statuses[source["key"]] = [404] * 5
        clock = _FakeClock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(self.worker, "_wait_for_download_actions", side_effect=clock.sleep):
            outcome = self.worker.auto_downloader(directory, poll_seconds=5)
        self.assertEqual(outcome, "incomplete")
        self.assertEqual(sum(url.endswith("/source_manifest") for _method, url, _kwargs in self.backend.calls), 5)
        warning = self.worker.logger.warning.call_args.args[0]
        self.assertIn("composite/0001.png", warning)
        self.assertIn("5 consecutive listings", warning)
        self.worker.logger.success.assert_not_called()

    def test_auto_deferrals_reset_when_a_listing_no_longer_defers_the_file(self):
        source = _source(1)
        self.backend.manifests = iter([[source]] * 4 + [[]] + [[source]] * 6)
        self.backend.statuses = iter([("finished", 1, 1)])
        self.backend.object_statuses[source["key"]] = [404] * 8 + [200]
        clock = _FakeClock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(self.worker, "_wait_for_download_actions", side_effect=clock.sleep):
            outcome = self.worker.auto_downloader(directory, poll_seconds=5)
            self.assertEqual(outcome, "finished")
            self.assertEqual((Path(directory) / "composite/0001.png").read_bytes(), b"frame")
        self.assertEqual(len(self.backend.downloaded), 1)

    def test_signing_buffer_batches_long_downloads_instead_of_posting_one_url_per_file(self):
        sources = [_source(number) for number in range(1, 41)]
        self.backend.manifests = iter([sources])
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(len(list(Path(directory).rglob("*.png"))), len(sources))
        batches = [kwargs["json"]["sources"] for _method, url, kwargs in self.backend.calls
                   if url.endswith("/source_urls")]
        self.assertTrue(all(len(batch) >= 8 for batch in batches[:-1]))
        self.assertTrue(all(len(batch) <= 100 for batch in batches))
        issued = [source["key"] for batch in batches for source in batch]
        self.assertEqual(len(issued), len(sources))
        self.assertEqual(set(issued), {source["key"] for source in sources})

    def test_buffered_url_older_than_response_ttl_margin_is_resigned_before_fetch(self):
        sources = [_source(number) for number in range(1, 10)]
        self.backend.manifests = iter([sources])
        self.backend.expires_in = 180
        clock = _FakeClock()
        advanced = threading.Event()

        def let_buffer_age(key):
            if key == sources[0]["key"]:
                clock.now = 61
                advanced.set()
            elif not advanced.wait(timeout=3):
                raise AssertionError("The first transfer did not advance the clock")

        self.backend.before_get = let_buffer_age
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic):
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual((Path(directory) / "composite/0009.png").read_bytes(), b"frame")
        last_key = sources[-1]["key"]
        issued = [source["key"] for _method, url, kwargs in self.backend.calls
                  if url.endswith("/source_urls") for source in kwargs["json"]["sources"]]
        self.assertEqual(issued.count(last_key), 2)
        fetched = [url for _method, url, _kwargs in self.backend.calls
                   if url.startswith("https://storage.example/" + last_key + "?")]
        self.assertEqual(len(fetched), 1)
        self.assertNotIn("signature=private-1", fetched[0])
        self.assert_authenticated_backend_calls()

    def test_long_transfer_touches_temporary_file_at_most_once_per_minute(self):
        source = {**_source(1), "size": 7}
        self.backend.manifests = iter([[source]])
        clock = _FakeClock()
        real_utime = os.utime

        def timed_chunks(_response, _chunk_size):
            for timestamp in (10, 20, 59, 60, 90, 119, 120):
                clock.now = timestamp
                yield b"x"

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(_Response, "iter_content", timed_chunks), \
             patch.object(self.worker.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(self.worker.os, "utime", wraps=real_utime) as touch:
            self.worker._run_selected_downloader(directory, "single")
            target = Path(directory) / "composite/0001.png"
            self.assertEqual(target.read_bytes(), b"xxxxxxx")
            self.assertEqual(target.stat().st_mtime_ns // 1_000_000, source["last_modified"])
        heartbeats = [call for call in touch.call_args_list if call.args[1:] == (None,)]
        self.assertEqual(len(heartbeats), 2)

    def test_single_mode_relists_after_size_change_and_uses_the_new_snapshot(self):
        old = _source(1)
        new = {**old, "size": 7, "last_modified": old["last_modified"] + 2000}
        self.backend.manifests = iter([[old], [new]])
        self.backend.contents[old["key"]] = [b"updated", b"updated"]
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
            target = Path(directory) / "composite/0001.png"
            self.assertEqual(target.read_bytes(), b"updated")
            self.assertEqual(target.stat().st_mtime_ns // 1_000_000, new["last_modified"])
            self.assertEqual(list(Path(directory).rglob(".sulu-download-*")), [])
        self.assertEqual(sum(url.endswith("/source_manifest") for _method, url, _kwargs in self.backend.calls), 2)

    def test_single_mode_reports_a_persistent_404_after_one_relisting(self):
        source = _source(1)
        self.backend.manifests = iter([[source], [source]])
        self.backend.object_statuses[source["key"]] = [404, 404]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "still changing or unavailable"):
                self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(list(Path(directory).rglob(".sulu-download-*")), [])
        self.assertEqual(sum(url.endswith("/source_manifest") for _method, url, _kwargs in self.backend.calls), 2)
        self.assertEqual(len(self.sessions), 2)

    def test_manifest_case_collision_refuses_second_name_and_preserves_first_bytes(self):
        first = {**_source(1), "frame": "A", "key": "job-1/output/composite/A.png"}
        second = {**_source(2), "frame": "a", "key": "job-1/output/composite/a.png"}
        self.backend.manifests = iter([[first, second]])
        self.backend.contents[first["key"]] = b"first"
        self.backend.contents[second["key"]] = b"other"
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual([path.name for path in Path(directory).rglob("*.png")], ["A.png"])
            self.assertEqual((Path(directory) / "composite/A.png").read_bytes(), b"first")
        self.assertEqual(len(self.backend.downloaded), 1)
        self.assertTrue(any("case-insensitive name collision" in str(call) for call in self.worker.logger.warning.call_args_list))

    def test_existing_target_case_collision_never_overwrites_the_local_copy(self):
        source = {**_source(1), "frame": "a", "key": "job-1/output/composite/a.png"}
        self.backend.manifests = iter([[source]])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "composite/A.png"
            target.parent.mkdir()
            target.write_bytes(b"local")
            self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(target.read_bytes(), b"local")
            self.assertEqual([path.name for path in target.parent.iterdir()], ["A.png"])
        self.assertEqual(self.sessions, [])
        self.assertTrue(any("refusing to overwrite" in str(call) for call in self.worker.logger.warning.call_args_list))

    def test_start_keeps_fresh_transfer_files_and_removes_only_old_ones_without_counting_either(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "composite"
            nested.mkdir()
            fresh = root / ".sulu-download-live"
            old = nested / ".sulu-download-orphan"
            fresh.write_bytes(b"active")
            old.write_bytes(b"partial")
            old_time = time.time() - 601
            os.utime(old, (old_time, old_time))
            (root / "keep.txt").write_bytes(b"keep")
            self.worker._run_selected_downloader(directory, "single")
            self.assertFalse(old.exists())
            self.assertEqual(fresh.read_bytes(), b"active")
            self.assertEqual((root / "keep.txt").read_bytes(), b"keep")
            self.assertEqual((nested / "0001.png").read_bytes(), b"frame")
        self.worker.logger.resume_info.assert_called_once_with(1)

    def test_start_skips_old_transfer_files_that_are_locked_or_vanish_during_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            locked = root / ".sulu-download-locked"
            vanished = root / ".sulu-download-vanishing"
            old_time = time.time() - 601
            for path in (locked, vanished):
                path.write_bytes(b"partial")
                os.utime(path, (old_time, old_time))
            real_unlink = Path.unlink

            def concurrent_unlink(path, missing_ok=False):
                if path == locked:
                    raise PermissionError(13, "Locked transfer")
                if path == vanished:
                    real_unlink(path)
                    raise FileNotFoundError(2, "Transfer already removed")
                return real_unlink(path, missing_ok=missing_ok)

            with patch.object(Path, "unlink", concurrent_unlink):
                self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(locked.read_bytes(), b"partial")
            self.assertFalse(vanished.exists())
            self.assertEqual((root / "composite/0001.png").read_bytes(), b"frame")

    def test_signed_connection_errors_use_zero_adapter_retries_and_surface_safely(self):
        sent = []
        sessions = []

        def new_objects():
            objects = self.session_type()
            sessions.append(objects)
            return objects

        def connection_error(_adapter, request, **_kwargs):
            sent.append(request)
            raise requests.ConnectionError("Private signed URL: " + request.url)

        with patch.object(self.worker.requests, "Session", side_effect=new_objects), \
             patch.object(requests.sessions, "get_netrc_auth", return_value=("fixture-user", "fixture-password")), \
             patch.object(requests.adapters.HTTPAdapter, "send", autospec=True, side_effect=connection_error), \
             tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "Check your connection") as raised:
                self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(list(Path(directory).rglob(".sulu-download-*")), [])
        self.assertTrue(sent)
        self.assertTrue(sessions)
        for objects in sessions:
            self.assertEqual(objects.get_adapter("https://storage.example").max_retries.total, 0)
        for request in sent:
            self.assertNotIn("Authorization", request.headers)
        self.assertNotIn("signature", str(raised.exception))
        self.assertNotIn("private-", str(raised.exception))

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

    def test_download_cannot_follow_a_local_symlink_outside_the_destination(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            (Path(directory) / "composite").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "leaves the download folder"):
                self.worker._run_selected_downloader(directory, "single")
            self.assertEqual(list(Path(outside).iterdir()), [])
        self.assert_authenticated_backend_calls()

    def test_single_download_does_not_report_empty_manifest_as_complete(self):
        self.backend = _BackendSession(manifests=[[]])
        self.worker.session = self.backend
        with tempfile.TemporaryDirectory() as directory:
            self.worker._run_selected_downloader(directory, "single")
        self.worker.logger.transfer_complete.assert_not_called()
        self.worker.logger.warning.assert_called_once_with(
            "No frames ready yet. Run again later to download."
        )

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
