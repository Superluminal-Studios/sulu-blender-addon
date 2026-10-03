#!/usr/bin/env python3
"""
Tests for bulletproof upload logging.

Covers:
- DiagnosticReport.complete_upload_step() warning generation
- rclone_utils._redact_cmd() credential masking
- submit_worker._log_upload_result() terminal output
- submit_worker._is_filesystem_root() detection

Usage:
    python -m pytest tests/test_upload_logging.py -v
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from concurrent.futures import Future
from pathlib import Path
from unittest import mock

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


def _load_module_directly(name: str, filepath: Path):
    """Load a single .py file as a module, bypassing package __init__.py."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _synthesize_addon_package() -> str:
    """Create the package tree workers use without importing add-on __init__.py."""
    pkg_name = "_test_sulu_blender_addon"
    packages = {
        pkg_name: _addon_dir,
        f"{pkg_name}.utils": _addon_dir / "utils",
        f"{pkg_name}.transfers": _addon_dir / "transfers",
        f"{pkg_name}.transfers.submit": _addon_dir / "transfers" / "submit",
    }
    for name, path in packages.items():
        if name in sys.modules:
            continue
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
    return pkg_name


_pkg_name = _synthesize_addon_package()
_diagnostic_report = importlib.import_module(f"{_pkg_name}.utils.diagnostic_report")
_logger_utils = importlib.import_module(f"{_pkg_name}.utils.logger_utils")
_submit_logger = importlib.import_module(f"{_pkg_name}.utils.submit_logger")
_rclone_utils = importlib.import_module(f"{_pkg_name}.transfers.rclone_utils")
_submit_worker = importlib.import_module(
    f"{_pkg_name}.transfers.submit.submit_worker"
)
_environment = importlib.import_module(f"{_pkg_name}.environment")
_farm_upload_harness = _load_module_directly(
    "farm_upload_harness", _addon_dir / "tests" / "realworld" / "test_farm_upload.py"
)


def _settings_by_flag(settings):
    """Return flag/value pairs from the upload settings under test."""
    result = {}
    index = 0
    while index < len(settings):
        flag = settings[index]
        if flag in {"--no-traverse", "--no-check-dest", "--s3-disable-checksum"}:
            result[flag] = True
            index += 1
        else:
            result[flag] = settings[index + 1]
            index += 2
    return result


class TestZipUploadTuning(unittest.TestCase):
    """ZIP archives use Cloudflare-oriented single/multipart boundaries."""

    def test_single_zip_upload_skips_destination_checks(self):
        zip_values = _settings_by_flag(
            _submit_worker._build_rclone_upload_settings(
                single_zip_archive=True,
            )
        )
        project_values = _settings_by_flag(
            _submit_worker._build_rclone_upload_settings()
        )

        self.assertIs(zip_values["--no-check-dest"], True)
        self.assertEqual(zip_values["--transfers"], "1")
        self.assertNotIn("--no-check-dest", project_values)

    def test_multipart_zip_skips_redundant_whole_archive_md5_pass(self):
        cutoff = _submit_worker._ZIP_SINGLE_PUT_CUTOFF_BYTES
        at_cutoff = _settings_by_flag(
            _submit_worker._build_rclone_upload_settings(
                single_zip_archive=True,
                archive_size_bytes=cutoff,
            )
        )
        above_cutoff = _settings_by_flag(
            _submit_worker._build_rclone_upload_settings(
                single_zip_archive=True,
                archive_size_bytes=cutoff + 1,
            )
        )

        self.assertNotIn("--s3-disable-checksum", at_cutoff)
        self.assertIs(above_cutoff["--s3-disable-checksum"], True)

    def test_required_api_date_header_replaces_separate_clock_probe(self):
        drift = _submit_worker._clock_drift_from_http_date(
            "Sun, 02 Aug 2026 22:00:00 GMT",
            local_time=1785708007.0,
        )
        self.assertEqual(drift, 7)
        self.assertIsNone(_submit_worker._clock_drift_from_http_date("invalid"))


class TestStorageCredentialPrefetch(unittest.TestCase):
    def test_main_rejects_mixed_environment_before_starting_work(self):
        clear_console = mock.Mock()
        session_factory = mock.Mock()
        mods = {
            "validate_handoff_environment": _environment.validate_handoff_environment,
            "clear_console": clear_console,
            "requests_retry_session": session_factory,
        }
        handoff = {
            "environment": "test",
            "pocketbase_url": "https://api.superlumin.al",
            "project": {
                "id": "project-1",
                "organization_id": "org-1",
                "sqid": "Project1",
            },
            "job_id": "job-1",
        }

        with (
            mock.patch.object(
                _submit_worker,
                "_load_handoff_from_argv",
                return_value=handoff,
            ),
            mock.patch.object(
                _submit_worker,
                "_bootstrap_addon_modules",
                return_value=mods,
            ),
            self.assertRaisesRegex(ValueError, "mixes Sulu environments"),
        ):
            _submit_worker.main()

        clear_console.assert_not_called()
        session_factory.assert_not_called()

    def test_pack_time_prefetch_removes_credential_request_from_upload_boundary(self):
        payload = {"items": [{"bucket_name": "redacted"}]}
        worker_session = mock.MagicMock()
        fetch = mock.Mock(return_value=payload)
        ctx = types.SimpleNamespace(
            no_submit=False,
            test_mode=False,
            storage_future=None,
            storage_thread=None,
            data={
                "pocketbase_url": "https://api.invalid",
                "user_token": "redacted",
                "project": {"id": "project-1"},
            },
            mods={
                "requests_retry_session": mock.Mock(return_value=worker_session),
                "fetch_project_storage": fetch,
            },
            session=mock.MagicMock(),
            phase_timings={},
            report=None,
        )

        _submit_worker._start_storage_prefetch(ctx)
        result = _submit_worker._project_storage_payload(ctx)

        self.assertEqual(result, payload)
        fetch.assert_called_once_with(
            worker_session,
            "https://api.invalid",
            "redacted",
            "project-1",
        )
        worker_session.close.assert_called_once_with()
        self.assertTrue(ctx.phase_timings["storage_credentials"]["overlapped"])

    def test_prefetch_wait_does_not_override_the_retry_policy_with_a_timeout(self):
        payload = {"items": [{"bucket_name": "redacted"}]}
        future = mock.Mock()
        future.result.return_value = (payload, 123.0)
        ctx = types.SimpleNamespace(
            storage_future=future,
            storage_thread=mock.MagicMock(),
            phase_timings={},
            report=None,
        )

        result = _submit_worker._project_storage_payload(ctx)

        self.assertEqual(result, payload)
        future.result.assert_called_once_with()
        self.assertIsNone(ctx.storage_future)
        self.assertIsNone(ctx.storage_thread)

    def test_prefetch_thread_is_daemon_and_cleanup_never_waits_for_it(self):
        started = threading.Event()
        release = threading.Event()
        worker_session = mock.MagicMock()

        def blocked_fetch(*_args):
            started.set()
            release.wait(timeout=5)
            return {"items": []}

        ctx = types.SimpleNamespace(
            no_submit=False,
            test_mode=False,
            storage_future=None,
            storage_thread=None,
            data={
                "pocketbase_url": "https://api.invalid",
                "user_token": "redacted",
                "project": {"id": "project-1"},
            },
            mods={
                "requests_retry_session": mock.Mock(return_value=worker_session),
                "fetch_project_storage": blocked_fetch,
            },
        )

        _submit_worker._start_storage_prefetch(ctx)
        self.assertTrue(started.wait(timeout=1))
        thread = ctx.storage_thread
        self.assertIsNotNone(thread)
        self.assertTrue(thread.daemon)

        _submit_worker._cancel_storage_prefetch(ctx)
        self.assertIsNone(ctx.storage_future)
        self.assertIsNone(ctx.storage_thread)
        self.assertTrue(thread.is_alive())

        release.set()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        worker_session.close.assert_called_once_with()

    def test_prefetch_session_construction_failure_is_delivered(self):
        failure = RuntimeError("session setup failed")
        ctx = types.SimpleNamespace(
            no_submit=False,
            test_mode=False,
            storage_future=None,
            storage_thread=None,
            data={
                "pocketbase_url": "https://api.invalid",
                "user_token": "redacted",
                "project": {"id": "project-1"},
            },
            mods={
                "requests_retry_session": mock.Mock(side_effect=failure),
                "fetch_project_storage": mock.Mock(),
            },
            session=mock.MagicMock(),
            phase_timings={},
            report=None,
        )

        _submit_worker._start_storage_prefetch(ctx)

        with self.assertRaisesRegex(RuntimeError, "session setup failed"):
            _submit_worker._project_storage_payload(ctx)

    def test_main_cleans_prefetch_on_success_error_and_cancel(self):
        scenarios = (
            ("success", None, None),
            ("error", RuntimeError("packing failed"), RuntimeError),
            ("cancel", SystemExit(1), SystemExit),
        )

        for name, trace_side_effect, expected_exception in scenarios:
            with self.subTest(name=name):
                session = mock.MagicMock()
                logger = mock.MagicMock()
                mods = {
                    "clear_console": mock.Mock(),
                    "create_logger": mock.Mock(return_value=logger),
                    "requests_retry_session": mock.Mock(return_value=session),
                    "validate_handoff_environment": mock.Mock(),
                }

                def mark_prefetch_started(ctx):
                    ctx.storage_future = Future()
                    ctx.storage_thread = mock.MagicMock()

                with (
                    mock.patch.object(
                        _submit_worker,
                        "_load_handoff_from_argv",
                        return_value={"project": {}},
                    ),
                    mock.patch.object(
                        _submit_worker,
                        "_bootstrap_addon_modules",
                        return_value=mods,
                    ),
                    mock.patch.object(_submit_worker, "_preflight"),
                    mock.patch.object(_submit_worker, "_ensure_farm_ready"),
                    mock.patch.object(_submit_worker, "_start_update_discovery"),
                    mock.patch.object(_submit_worker, "_show_update_before_submit"),
                    mock.patch.object(
                        _submit_worker,
                        "_start_storage_prefetch",
                        side_effect=mark_prefetch_started,
                    ),
                    mock.patch.object(
                        _submit_worker,
                        "_trace_and_pack",
                        side_effect=trace_side_effect,
                    ),
                    mock.patch.object(_submit_worker, "_upload"),
                    mock.patch.object(_submit_worker, "_register_job"),
                    mock.patch.object(_submit_worker, "_finish"),
                    mock.patch.object(
                        _submit_worker,
                        "_cancel_storage_prefetch",
                        wraps=_submit_worker._cancel_storage_prefetch,
                    ) as cancel_prefetch,
                    mock.patch.object(_submit_worker, "_cancel_update_discovery"),
                ):
                    if expected_exception is None:
                        _submit_worker.main()
                    else:
                        with self.assertRaises(expected_exception):
                            _submit_worker.main()

                cancel_prefetch.assert_called_once()
                cleaned_ctx = cancel_prefetch.call_args.args[0]
                self.assertIsNone(cleaned_ctx.storage_future)
                self.assertIsNone(cleaned_ctx.storage_thread)
                session.close.assert_called_once_with()


class TestBackgroundUpdateDiscovery(unittest.TestCase):
    def test_development_build_skips_discovery(self):
        ctx = types.SimpleNamespace(
            data={"addon_build_channel": "development"},
            update_future=None,
            update_thread=None,
        )

        with mock.patch.object(_submit_worker.requests, "Session") as session:
            _submit_worker._start_update_discovery(ctx)

        session.assert_not_called()
        self.assertIsNone(ctx.update_future)

    def test_pending_discovery_is_resolved_before_submit(self):
        ctx = types.SimpleNamespace(
            update_future=Future(),
            update_thread=mock.MagicMock(),
            logger=mock.MagicMock(),
        )
        ctx.update_future.set_result(False)

        _submit_worker._show_update_before_submit(ctx)

        ctx.logger.version_update.assert_not_called()
        self.assertIsNone(ctx.update_future)

    def test_completed_discovery_preserves_update_notification(self):
        future = Future()
        future.set_result(True)
        logger = mock.MagicMock()
        logger.version_update.return_value = "n"
        ctx = types.SimpleNamespace(
            update_future=future,
            update_thread=mock.MagicMock(),
            logger=logger,
        )

        _submit_worker._show_update_before_submit(ctx)

        logger.version_update.assert_called_once()
        self.assertIsNone(ctx.update_future)
        self.assertIsNone(ctx.update_thread)

    def test_update_notification_error_cannot_fail_completed_submit(self):
        future = Future()
        future.set_result(True)
        logger = mock.MagicMock()
        logger.version_update.side_effect = RuntimeError("terminal closed")
        ctx = types.SimpleNamespace(
            update_future=future,
            update_thread=mock.MagicMock(),
            logger=logger,
        )

        _submit_worker._show_update_before_submit(ctx)

        self.assertIsNone(ctx.update_future)


class TestUploadResultVisibility(unittest.TestCase):
    def test_marker_is_printed_only_when_the_harness_requests_it(self):
        payload = {"status": "success"}
        with mock.patch.object(
            _submit_worker, "_emit_upload_success_payload"
        ) as emit:
            _submit_worker._emit_upload_success_payload_if_requested({}, payload)
            emit.assert_not_called()
            _submit_worker._emit_upload_success_payload_if_requested(
                {"emit_upload_result": True}, payload
            )

        emit.assert_called_once_with(payload)


class TestIntegratedDownloadHandoff(unittest.TestCase):
    def _context(self, *, enabled: bool):
        report = mock.MagicMock()
        report.get_reports_dir.return_value = Path("/tmp/sulu-reports")
        logger = mock.MagicMock()
        logger.logo_end.return_value = "c"
        return types.SimpleNamespace(
            data={
                "job_id": "job-live-download",
                "job_name": "Nebula Passage",
                "environment": "production",
                "download_after_submit": enabled,
                "download_path": "/tmp/renders",
                "packed_addons": [],
            },
            mods={
                "pkg_name": _pkg_name,
                "open_folder": mock.Mock(),
                "job_page_url": lambda _environment, project, job: (
                    f"https://superlumin.al/p/{project}/farm/jobs/{job}"
                ),
            },
            logger=logger,
            report=report,
            t_start=0.0,
            use_project=False,
            project_sqid="project-sqid",
            rel_manifest=[],
            main_blend_s3="scene.zip",
            blend_path="/tmp/scene.blend",
        )

    def test_enabled_handoff_continues_in_same_terminal(self):
        ctx = self._context(enabled=True)

        with (
            mock.patch.object(
                _submit_worker,
                "_run_integrated_download",
                return_value="/tmp/renders/Nebula Passage",
            ) as run_download,
            self.assertRaises(SystemExit) as raised,
        ):
            _submit_worker._finish(ctx)

        self.assertEqual(raised.exception.code, 0)
        ctx.logger.logo_end.assert_called_once()
        self.assertTrue(
            ctx.logger.logo_end.call_args.kwargs["continue_to_download"]
        )
        download_handoff = run_download.call_args.args[0]
        self.assertEqual(run_download.call_args.args[1], _pkg_name)
        self.assertEqual(
            download_handoff["job_url"],
            "https://superlumin.al/p/project-sqid/farm/jobs/job-live-download",
        )
        self.assertEqual(download_handoff["report_path"], str(Path("/tmp/sulu-reports")))

    def test_disabled_handoff_keeps_existing_completion_prompt(self):
        ctx = self._context(enabled=False)

        with (
            mock.patch.object(_submit_worker, "_run_integrated_download") as run_download,
            self.assertRaises(SystemExit) as raised,
        ):
            _submit_worker._finish(ctx)

        self.assertEqual(raised.exception.code, 0)
        self.assertFalse(
            ctx.logger.logo_end.call_args.kwargs["continue_to_download"]
        )
        run_download.assert_not_called()

    def test_transition_screen_never_waits_for_input(self):
        messages = []
        input_fn = mock.Mock(return_value="j")
        logger = _submit_logger.SubmitLogger(log_fn=messages.append, input_fn=input_fn)
        logger.console = None

        choice = logger.logo_end(continue_to_download=True)

        self.assertEqual(choice, "c")
        input_fn.assert_not_called()
        self.assertIn("Downloading frames as they finish.", messages)
        self.assertIn("  [Next] Live download", messages)


class TestSubmitHandoffCleanup(unittest.TestCase):
    def test_malformed_handoff_is_still_removed(self):
        with tempfile.NamedTemporaryFile(
            prefix="sulu_bad_submit_handoff_",
            suffix=".json",
            delete=False,
        ) as handoff:
            handoff_path = Path(handoff.name)
        handoff_path.write_text("{", encoding="utf-8")

        with self.assertRaises(json.JSONDecodeError):
            _submit_worker._load_handoff_from_argv(
                ["submit_worker.py", str(handoff_path)]
            )

        self.assertFalse(handoff_path.exists())


class TestFinalizingStatusRendering(unittest.TestCase):
    """The upload-only finalizing state is visible in rich and plain output."""

    def test_rich_and_plain_progress_name_finalization(self):
        rich = _logger_utils.TranscriptLogger._progress_status_text(
            None,
            checks=0,
            transfers=0,
            status="finalizing",
            current_file="archive.zip",
        )
        plain = _logger_utils.TranscriptLogger._plain_transfer_progress_ext(
            None,
            cur=999,
            total=1000,
            checks=0,
            transfers=0,
            status="finalizing",
            current_file="archive.zip",
        )
        self.assertIn("Finalizing upload", rich)
        self.assertIn("99.9%", plain)
        self.assertIn("Finalizing upload", plain)

    def test_complete_status_defers_to_upload_complete_panel(self):
        rich_status = _logger_utils.TranscriptLogger._progress_status_text(
            None,
            checks=1,
            transfers=1,
            status="complete",
            current_file="",
        )
        plain = _logger_utils.TranscriptLogger._plain_transfer_progress_ext(
            None,
            cur=1000,
            total=1000,
            checks=1,
            transfers=1,
            status="complete",
            current_file="",
        )
        self.assertEqual(rich_status, "")
        self.assertNotIn("Finalizing", plain)
        self.assertNotIn("Complete", plain)


class TestZipProgressRendering(unittest.TestCase):
    def test_plain_zip_progress_shows_total_percent_file_and_rate(self):
        logger = _submit_logger.SubmitLogger(log_fn=lambda _message: None)
        logger.console = None
        stderr = io.StringIO()

        with mock.patch.object(sys, "stderr", stderr):
            logger.zip_start(total_files=2, source_bytes=1000)
            logger.zip_progress(
                index=1,
                total_files=2,
                arcname="scenes/scene.blend",
                file_bytes_done=500,
                file_size=800,
                source_bytes_done=500,
                source_bytes=1000,
                method="Stored · Gzip source",
                file_elapsed=2.0,
                total_elapsed=3.0,
            )
            logger.zip_done(
                "archive.zip",
                2,
                source_bytes=1000,
                archive_bytes=600,
                preparation_elapsed=1.0,
                archive_write_elapsed=2.0,
                total_elapsed=3.0,
            )

        output = stderr.getvalue()
        self.assertIn("50.0%", output)
        self.assertIn("[1/2] scene.blend", output)
        self.assertIn("250 B/s", output)

    def test_zip_progress_keeps_completed_and_current_file_rows(self):
        logger = _submit_logger.SubmitLogger(log_fn=lambda _message: None)
        logger.console = None

        with mock.patch.object(sys, "stderr", io.StringIO()):
            logger.zip_start(total_files=2, source_bytes=1500)
            logger.zip_progress(
                index=1,
                total_files=2,
                arcname="scenes/scene.blend",
                file_bytes_done=600,
                file_size=1200,
                source_bytes_done=600,
                source_bytes=1500,
                method="Zstandard-9",
                file_elapsed=2.0,
                total_elapsed=3.0,
            )
            logger.zip_entry(
                1,
                2,
                "scenes/scene.blend",
                1200,
                800,
                "Zstandard-9",
                4.0,
            )
            logger.zip_progress(
                index=2,
                total_files=2,
                arcname="textures/board.png",
                file_bytes_done=150,
                file_size=300,
                source_bytes_done=1350,
                source_bytes=1500,
                method="Deflate-1",
                file_elapsed=1.0,
                total_elapsed=5.0,
            )

        self.assertEqual(logger._zip_live_rows[1]["done"], 1200)
        self.assertEqual(logger._zip_live_rows[1]["total"], 1200)
        self.assertEqual(logger._zip_live_rows[1]["elapsed"], 4.0)
        self.assertEqual(logger._zip_live_rows[2]["done"], 150)
        self.assertEqual(logger._zip_live_rows[2]["total"], 300)
        self.assertEqual(logger._zip_live_rows[2]["method"], "Deflate-1")

    def test_zip_summary_keeps_source_and_archive_sizes_explicit(self):
        messages = []
        logger = _submit_logger.SubmitLogger(log_fn=messages.append)
        logger.console = None

        logger.zip_start(total_files=2, source_bytes=1500)
        logger.zip_entry(
            1,
            2,
            "scenes/scene.blend",
            1200,
            800,
            "Zstandard-9",
            61.0,
        )
        logger.zip_done(
            "archive.zip",
            2,
            source_bytes=1500,
            archive_bytes=1000,
            preparation_elapsed=1.0,
            archive_write_elapsed=2.0,
            total_elapsed=3.0,
        )

        self.assertIn("  Source files (before ZIP): 1.5 KB", messages)
        self.assertIn("  ZIP archive (after ZIP): 1.0 KB", messages)
        self.assertIn("  Reduced by: 500 B (33.3%)", messages)

    def test_zip_summary_names_container_overhead_instead_of_negative_savings(self):
        messages = []
        logger = _submit_logger.SubmitLogger(log_fn=messages.append)
        logger.console = None

        logger.zip_start(total_files=1, source_bytes=1000)
        logger.zip_done(
            "archive.zip",
            1,
            source_bytes=1000,
            archive_bytes=1100,
            preparation_elapsed=0.5,
            archive_write_elapsed=1.0,
            total_elapsed=1.5,
        )

        self.assertIn("  Archive overhead: 100 B (10.0%)", messages)


class TestRcloneFinalizingProgress(unittest.TestCase):
    """100% is emitted only after the rclone process confirms success."""

    class _Logger:
        def __init__(self):
            self.calls = []

        def transfer_progress(self, current, total):
            self.calls.append((current, total, ""))

        def transfer_progress_ext(
            self,
            current,
            total,
            *,
            status="",
            current_file="",
            checks=0,
            transfers=0,
        ):
            self.calls.append((current, total, status))

    class _Process:
        def __init__(self, lines, exit_code=0):
            self.stdout = lines
            self.exit_code = exit_code

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def wait(self, timeout=None):
            return self.exit_code

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    def test_holds_at_99_9_until_process_exit_and_records_boundary(self):
        stats_line = json.dumps(
            {
                "stats": {
                    "bytes": 1000,
                    "totalBytes": 1000,
                    "checks": 1,
                    "transfers": 1,
                    "errors": 0,
                    "elapsedTime": 2.0,
                    "transferring": ["archive.zip"],
                }
            }
        )
        process = self._Process([stats_line + "\n"])
        logger = self._Logger()

        with mock.patch.object(
            _rclone_utils,
            "_rclone_supports_flag",
            return_value=False,
        ), mock.patch.object(
            _rclone_utils.subprocess,
            "Popen",
            return_value=process,
        ), mock.patch.object(
            _rclone_utils.time,
            "perf_counter",
            side_effect=[10.0, 12.0, 15.0],
        ):
            result = _rclone_utils.run_rclone(
                ["rclone"],
                "move",
                "/tmp/archive.zip",
                ":s3:bucket/",
                logger=logger,
                total_bytes=1000,
            )

        self.assertIn((999, 1000, "finalizing"), logger.calls)
        self.assertEqual(logger.calls[-1], (1000, 1000, "complete"))
        self.assertEqual(result["bytes_transferred"], 1000)
        self.assertEqual(result["process_elapsed_time"], 5.0)
        self.assertEqual(result["reported_bytes_complete_time"], 2.0)
        self.assertEqual(result["finalization_time"], 3.0)

    def test_progress_helper_preserves_in_flight_values(self):
        self.assertEqual(
            _rclone_utils._progress_while_process_is_running(
                400,
                1000,
                "transferring",
            ),
            (400, "transferring"),
        )

    def test_progress_helper_clamps_near_total_before_rounding_to_100(self):
        current, status = _rclone_utils._progress_while_process_is_running(
            9999,
            10000,
            "transferring",
        )

        self.assertEqual((current, status), (9990, "transferring"))
        self.assertEqual(f"{(current / 10000) * 100.0:.1f}", "99.9")

    def test_failed_process_never_emits_terminal_100_percent(self):
        lines = [
            json.dumps(
                {
                    "stats": {
                        "bytes": 1000,
                        "totalBytes": 1000,
                        "checks": 0,
                        "transfers": 0,
                        "errors": 1,
                        "elapsedTime": 2.0,
                    }
                }
            )
            + "\n",
            json.dumps(
                {
                    "level": "error",
                    "msg": "connection reset by peer",
                }
            )
            + "\n",
        ]
        process = self._Process(lines, exit_code=1)
        logger = self._Logger()

        with mock.patch.object(
            _rclone_utils,
            "_rclone_supports_flag",
            return_value=False,
        ), mock.patch.object(
            _rclone_utils.subprocess,
            "Popen",
            return_value=process,
        ), mock.patch.object(
            _rclone_utils.time,
            "perf_counter",
            side_effect=[10.0, 12.0, 15.0],
        ):
            with self.assertRaises(_rclone_utils.RcloneError):
                _rclone_utils.run_rclone(
                    ["rclone"],
                    "move",
                    "/tmp/archive.zip",
                    ":s3:bucket/",
                    logger=logger,
                    total_bytes=1000,
                )

        self.assertIn((999, 1000, "finalizing"), logger.calls)
        self.assertNotIn((1000, 1000, "complete"), logger.calls)

    def test_download_progress_is_not_changed_by_upload_finalization_guard(self):
        stats_line = json.dumps(
            {
                "stats": {
                    "bytes": 1000,
                    "totalBytes": 1000,
                    "checks": 1,
                    "transfers": 1,
                    "errors": 0,
                    "elapsedTime": 2.0,
                }
            }
        )
        process = self._Process([stats_line + "\n"])
        logger = self._Logger()

        with mock.patch.object(
            _rclone_utils,
            "_rclone_supports_flag",
            return_value=False,
        ), mock.patch.object(
            _rclone_utils.subprocess,
            "Popen",
            return_value=process,
        ), mock.patch.object(
            _rclone_utils.time,
            "perf_counter",
            side_effect=[10.0, 15.0],
        ):
            result = _rclone_utils.run_rclone(
                ["rclone"],
                "copy",
                ":s3:bucket/results/",
                "/tmp/results",
                logger=logger,
                total_bytes=1000,
            )

        self.assertIn((1000, 1000, ""), logger.calls)
        self.assertNotIn((999, 1000, "finalizing"), logger.calls)
        self.assertIsNone(result["reported_bytes_complete_time"])
        self.assertIsNone(result["finalization_time"])

    def test_action_callback_cancels_active_rclone_process(self):
        process = self._Process(["working\n"])

        class CancelDownload(Exception):
            pass

        with mock.patch.object(
            _rclone_utils,
            "_rclone_supports_flag",
            return_value=False,
        ), mock.patch.object(
            _rclone_utils.subprocess,
            "Popen",
            return_value=process,
        ):
            with self.assertRaises(CancelDownload):
                _rclone_utils.run_rclone(
                    ["rclone"],
                    "copy",
                    ":s3:bucket/results/",
                    "/tmp/results",
                    action_callback=lambda: (_ for _ in ()).throw(
                        CancelDownload()
                    ),
                )

        self.assertTrue(process.terminated)


class TestSubmitPhaseTimings(unittest.TestCase):
    """Monotonic durations are persisted as bounded structured metadata."""

    class _Report:
        def __init__(self):
            self.values = {}

        def set_metadata(self, key, value):
            self.values[key] = value

    def test_archive_and_finalization_timings_are_separate(self):
        report = self._Report()
        ctx = types.SimpleNamespace(phase_timings={}, report=report)

        original_debug = _submit_worker._debug_enabled
        _submit_worker._debug_enabled = lambda: False
        try:
            _submit_worker._record_archive_rclone_timings(
                ctx,
                {
                    "process_elapsed_time": 5.0,
                    "reported_bytes_complete_time": 2.0,
                    "finalization_time": 3.0,
                },
            )
        finally:
            _submit_worker._debug_enabled = original_debug

        timings = report.values["phase_timings"]
        self.assertEqual(timings["archive_upload"]["duration_ms"], 5000.0)
        self.assertEqual(
            timings["archive_upload"]["reported_bytes_complete_ms"],
            2000.0,
        )
        self.assertEqual(
            timings["archive_finalization"]["duration_ms"],
            3000.0,
        )
        self.assertEqual(
            timings["archive_finalization"]["boundary"],
            "reported_bytes_complete_to_process_exit",
        )

    def test_registration_records_schema_and_job_post_durations(self):
        report = self._Report()
        response = mock.MagicMock()
        response.raise_for_status.return_value = None
        session = mock.MagicMock()
        session.post.return_value = response
        ctx = types.SimpleNamespace(
            data={
                "job_id": "job-1",
                "project": {"id": "project-1"},
                "packed_addons": [],
                "job_name": "Timing test",
                "start_frame": 1,
                "image_format": "PNG",
                "render_engine": "CYCLES",
                "blender_version": "blender51",
                "ignore_errors": False,
                "use_bserver": False,
                "farm_url": "https://farm.invalid",
                "pocketbase_url": "https://api.invalid",
                "settings_schema_key": "bl510-timing",
                "settings_schema": {
                    "blender_version": "5.1.0",
                    "groups": [],
                },
            },
            logger=mock.MagicMock(),
            session=session,
            report=report,
            headers={"Authorization": "redacted"},
            blend_path="/tmp/project/scene.blend",
            use_project=False,
            org_id="org-1",
            project_name="project",
            project_root_str="/tmp/project",
            main_blend_s3="scene.blend",
            effective_end_frame=1,
            frame_step_val=1,
            render_order="LINEAR",
            render_tasks=[1],
            required_storage=1000,
            phase_timings={},
        )

        with mock.patch.object(
            _submit_worker,
            "_nfc",
            side_effect=lambda value: value,
        ), mock.patch.object(
            _submit_worker,
            "_s3key_clean",
            side_effect=lambda value: value,
        ), mock.patch.object(
            _submit_worker,
            "_debug_enabled",
            return_value=False,
        ):
            _submit_worker._register_job(ctx)

        registration = report.values["phase_timings"]["registration"]
        self.assertEqual(registration["outcome"], "completed")
        self.assertGreaterEqual(registration["duration_ms"], 0)
        self.assertGreater(registration["schema_payload_bytes"], 0)
        self.assertGreaterEqual(registration["job_post_ms"], 0)
        session.post.assert_called_once()
        posted = json.loads(session.post.call_args.kwargs["data"])
        self.assertEqual(
            posted["settings_schema_registration"]["schema_key"],
            "bl510-timing",
        )
        self.assertEqual(
            posted["job_data"]["settings_schema_key"],
            "bl510-timing",
        )


# DiagnosticReport warning generation


class TestUploadStepWarnings(unittest.TestCase):
    """Test complete_upload_step() warning generation."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.report = _diagnostic_report.DiagnosticReport(
            reports_dir=Path(self._tmpdir),
            job_id="warn-test",
            blend_name="warn",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_step(self, bytes_transferred, rclone_stats,
                  expected_bytes=None):
        """Start + complete an upload step, return the step dict."""
        self.report.start_stage("upload")
        self.report.start_upload_step(
            1, 1, "test step",
            expected_bytes=expected_bytes,
        )
        self.report.complete_upload_step(
            bytes_transferred=bytes_transferred,
            rclone_stats=rclone_stats,
        )
        steps = self.report._data["stages"]["upload"]["steps"]
        return steps[-1]

    def test_warning_table(self):
        def stats(checks, transfers, errors=0, received=True):
            return {
                "stats_received": received,
                "checks": checks,
                "transfers": transfers,
                "errors": errors,
            }

        # (name, bytes, rclone_stats, expected_bytes, required, forbidden)
        cases = [
            ("no stats", 0, stats(0, 0, received=False), None,
             ["no transfer stats"], []),
            ("no stats + expected", 0, stats(0, 0, received=False), 1_000_000,
             ["no transfer stats", "Expected 1000000 bytes"], []),
            ("no stats overrides checks", 0, stats(50, 0, received=False), None,
             ["no transfer stats"], ["checked 50 files"]),
            ("empty manifest", 0, stats(0, 0), None,
             ["manifest may be empty"], []),
            ("empty manifest + expected", 0, stats(0, 0), 1_000_000,
             ["manifest may be empty", "; ", "Expected 1000000 bytes but transferred 0"], []),
            ("checked not transferred", 0, stats(42, 0), None,
             ["checked 42 files but transferred 0"], []),
            ("expected but zero", 0, stats(10, 0), 500_000,
             ["Expected 500000 bytes but transferred 0"], []),
            ("under half", 100_000, stats(10, 5), 500_000, ["20%"], []),
            ("errors despite exit 0", 500_000, stats(50, 50, errors=3), 500_000,
             ["3 error(s)", "some files may not have uploaded"], []),
            ("errors + checks + bytes", 0, stats(10, 0, errors=2), 100_000,
             ["checked 10 files but transferred 0", "2 error(s)", "Expected 100000 bytes"], []),
        ]
        for name, transferred, rclone_stats, expected, required, forbidden in cases:
            with self.subTest(name):
                warning = self._run_step(transferred, rclone_stats, expected)["warning"]
                for text in required:
                    self.assertIn(text, warning)
                for text in forbidden:
                    self.assertNotIn(text, warning)

    def test_healthy_or_unmeasured_uploads_do_not_warn(self):
        def stats(checks, transfers, errors=0):
            return {
                "stats_received": True,
                "checks": checks,
                "transfers": transfers,
                "errors": errors,
            }

        cases = [
            ("success", 1_000_000, stats(50, 50), 1_000_000),
            ("above half", 300_000, stats(10, 10), 500_000),
            ("errors None", 500_000, stats(50, 50, errors=None), 500_000),
            ("no stats object", 1024, None, None),
            ("expected zero", 0, stats(5, 5), 0),
            ("expected unknown", 0, stats(5, 5), None),
        ]
        for name, transferred, rclone_stats, expected in cases:
            with self.subTest(name):
                step = self._run_step(transferred, rclone_stats, expected)
                self.assertNotIn("warning", step)


# _redact_cmd


class TestRedactCmd(unittest.TestCase):
    """Test credential redaction in rclone commands."""

    def setUp(self):
        self._redact_cmd = _rclone_utils._redact_cmd

    def test_basic_redaction(self):
        """Sensitive flag values should be replaced with ***."""
        cmd = [
            "/usr/bin/rclone", "copy", "/src", ":s3:bucket/dst",
            "--s3-access-key-id", "AKIAEXAMPLE",
            "--s3-secret-access-key", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "--s3-session-token", "FwoGZXIvYXdzEBYaDHqa0",
            "--transfers", "4",
        ]
        result = self._redact_cmd(cmd)
        self.assertNotIn("AKIAEXAMPLE", result)
        self.assertNotIn("wJalrXUtnFEMI", result)
        self.assertNotIn("FwoGZXIvYXdzEBYaDHqa0", result)
        self.assertIn("--s3-access-key-id ***", result)
        self.assertIn("--s3-secret-access-key ***", result)
        self.assertIn("--s3-session-token ***", result)
        # Non-sensitive flags preserved
        self.assertIn("--transfers 4", result)
        self.assertIn("/usr/bin/rclone", result)
        self.assertIn("copy", result)

    def test_sensitive_flag_at_end(self):
        """A dangling sensitive flag (no value) must not crash or mask paths."""
        result = self._redact_cmd(
            ["/usr/bin/rclone", "copy", "/src", ":s3:dst", "--s3-access-key-id"]
        )
        self.assertEqual(result, "/usr/bin/rclone copy /src :s3:dst --s3-access-key-id")
        self.assertEqual(self._redact_cmd([]), "")

    def test_preserves_paths_and_flags(self):
        """Non-sensitive parts of command should be fully preserved."""
        cmd = [
            "/usr/bin/rclone", "copy",
            "/home/user/project", ":s3:my-bucket/prefix/",
            "--files-from-raw", "/tmp/filelist.txt",
            "--transfers", "4",
            "--s3-access-key-id", "AKIA",
            "--stats", "0.1s",
        ]
        self.assertEqual(
            self._redact_cmd(cmd),
            "/usr/bin/rclone copy /home/user/project :s3:my-bucket/prefix/ "
            "--files-from-raw /tmp/filelist.txt --transfers 4 "
            "--s3-access-key-id *** --stats 0.1s",
        )


# _log_upload_result (submit_worker)


class TestLogUploadResult(unittest.TestCase):
    """Test terminal stats logging helper."""

    def setUp(self):
        self._mod = _submit_worker
        self._log_upload_result = self._mod._log_upload_result
        self._captured = []

        # Patch _LOG, _format_size, and _debug_enabled
        self._orig_log = self._mod._LOG
        self._orig_fmt = self._mod._format_size
        self._orig_debug = self._mod._debug_enabled
        self._mod._LOG = lambda msg: self._captured.append(str(msg))
        self._mod._format_size = lambda n: f"{n} B"
        self._mod._debug_enabled = lambda: True

    def tearDown(self):
        self._mod._LOG = self._orig_log
        self._mod._format_size = self._orig_fmt
        self._mod._debug_enabled = self._orig_debug

    def test_none_result(self):
        self._log_upload_result(None, label="Test: ")
        self.assertEqual(len(self._captured), 1)
        self.assertIn("Test: ", self._captured[0])
        self.assertIn("no stats", self._captured[0])

    def test_stats_line_and_optional_command_line(self):
        base = {
            "bytes_transferred": 1024,
            "checks": 10,
            "transfers": 10,
            "errors": 0,
            "stats_received": True,
        }
        self._log_upload_result(base, expected_bytes=2000, label="Deps: ")
        self._log_upload_result(
            {**base, "errors": 2, "stats_received": False, "command": ""},
        )
        self._log_upload_result(
            {**base, "command": "rclone copy /src :s3:dst --s3-access-key-id ***"},
            label="Arc: ",
        )

        self.assertEqual(
            self._captured,
            [
                "  Deps: transferred=1024 B, expected=2000 B, checks=10, transfers=10",
                "  stats_received=False, transferred=1024 B, checks=10, transfers=10, errors=2",
                "  Arc: transferred=1024 B, checks=10, transfers=10",
                "  Arc: cmd: rclone copy /src :s3:dst --s3-access-key-id ***",
            ],
        )


# _is_filesystem_root


class TestIsFilesystemRoot(unittest.TestCase):
    """Test filesystem root detection."""

    def test_roots_and_non_roots(self):
        roots = ["/", "", "C:/", "C:\\", "G:", "/Volumes/MyDrive", "/mnt/data", "/media/user/usb"]
        non_roots = [
            "/home/user/projects/myproject",
            "C:/Users/me/Documents",
            "/Volumes/MyDrive/Projects",
            "/mnt/data/projects",
        ]
        for path in roots:
            with self.subTest(path=path):
                self.assertTrue(_submit_worker._is_filesystem_root(path))
        for path in non_roots:
            with self.subTest(path=path):
                self.assertFalse(_submit_worker._is_filesystem_root(path))


# _split_manifest_by_first_dir


class TestSplitManifest(unittest.TestCase):
    """Test manifest splitting for filesystem-root uploads."""

    def setUp(self):
        self._split = _submit_worker._split_manifest_by_first_dir

    def test_basic_split(self):
        manifest = [
            "Users/artist/textures/a.png",
            "Users/artist/textures/b.png",
            "Projects/assets/c.exr",
        ]
        groups = self._split(manifest)
        self.assertEqual(set(groups.keys()), {"Users", "Projects"})
        self.assertEqual(len(groups["Users"]), 2)
        self.assertEqual(len(groups["Projects"]), 1)
        # Check that the first-dir prefix is stripped from entries
        self.assertIn("artist/textures/a.png", groups["Users"])

    def test_files_at_root(self):
        """Files without a directory component go to the '' group."""
        manifest = ["readme.txt", "dir/file.png"]
        groups = self._split(manifest)
        self.assertIn("", groups)
        self.assertEqual(groups[""], ["readme.txt"])
        self.assertEqual(groups["dir"], ["file.png"])

    def test_empty_manifest(self):
        self.assertEqual(self._split([]), {})


# Structured upload success marker


class TestUploadSuccessMarker(unittest.TestCase):
    """Test the worker marker consumed by the live upload harness."""

    def test_project_payload_counts_scene_files_and_manifest(self):
        payload = _submit_worker._build_upload_success_payload(
            job_id="job-1",
            job_name="Smoke",
            job_url="https://superlumin.al/p/proj/farm/jobs/job-1",
            upload_type="PROJECT",
            rel_manifest=["textures/a.png", "cache/b.vdb"],
            main_blend_s3="scene.blend",
            blend_path="/tmp/scene.blend",
            packed_addons=["addon.zip"],
            report_path="/tmp/reports",
            elapsed=1.23456,
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["uploaded_file_count"], 3)
        self.assertEqual(payload["dependency_file_count"], 2)
        self.assertEqual(payload["manifest_file_count"], 3)
        self.assertEqual(payload["storage_object_count"], 5)
        self.assertEqual(payload["addon_file_count"], 1)
        self.assertEqual(payload["main_file"], "scene.blend")
        self.assertEqual(payload["elapsed_sec"], 1.235)

    def test_zip_payload_counts_archive_as_one_scene_file(self):
        payload = _submit_worker._build_upload_success_payload(
            job_id="job-2",
            job_name="Zip",
            job_url="https://superlumin.al/p/proj/farm/jobs/job-2",
            upload_type="ZIP",
            rel_manifest=["ignored.png"],
            main_blend_s3="",
            blend_path="/tmp/project/scene.blend",
        )

        self.assertEqual(payload["uploaded_file_count"], 1)
        self.assertEqual(payload["dependency_file_count"], 0)
        self.assertEqual(payload["manifest_file_count"], 0)
        self.assertEqual(payload["storage_object_count"], 1)
        self.assertEqual(payload["main_file"], "scene.blend")

    def test_harness_parses_marker_with_job_url_and_file_count(self):
        output = (
            "noise before\n"
            'SULU_UPLOAD_RESULT {"status":"success","job_id":"job-3",'
            '"job_url":"https://superlumin.al/p/proj/farm/jobs/job-3",'
            '"uploaded_file_count":4}\n'
            "noise after\n"
        )

        payload, error = _farm_upload_harness.parse_upload_success_line(output)

        self.assertIsNone(error)
        self.assertEqual(payload["job_id"], "job-3")
        self.assertEqual(payload["uploaded_file_count"], 4)
        self.assertEqual(
            payload["job_url"],
            "https://superlumin.al/p/proj/farm/jobs/job-3",
        )

    def test_harness_rejects_missing_marker(self):
        payload, error = _farm_upload_harness.parse_upload_success_line(
            "Submission complete"
        )

        self.assertIsNone(payload)
        self.assertIn("SULU_UPLOAD_RESULT", error)

    def test_harness_rejects_bad_count(self):
        payload, error = _farm_upload_harness.parse_upload_success_line(
            'SULU_UPLOAD_RESULT {"status":"success","job_id":"job-4",'
            '"job_url":"https://superlumin.al/p/proj/farm/jobs/job-4",'
            '"uploaded_file_count":0}'
        )

        self.assertIsNone(payload)
        self.assertIn("uploaded_file_count", error)


# _is_empty_upload


class TestRcloneHelpers(unittest.TestCase):
    def test_is_empty_upload(self):
        cases = [
            (None, 10, True),
            ({"stats_received": False}, 10, True),
            ({"stats_received": True, "transfers": 0}, 10, True),
            ({"stats_received": True, "transfers": 5}, 10, False),
            (None, 0, False),
        ]
        for result, expected_files, empty in cases:
            with self.subTest(result=result, expected_files=expected_files):
                self.assertIs(
                    _submit_worker._is_empty_upload(result, expected_files), empty
                )


# Diagnostic report persistence


class TestReportJsonRoundTrip(unittest.TestCase):
    """Everything recorded during a submission survives the on-disk report."""

    def test_recorded_sections_persist_to_disk(self):
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d),
                job_id="roundtrip-test",
                blend_name="test",
                metadata={"upload_type": "PROJECT", "job_name": "MyJob"},
            )
            self.assertEqual(report._data["metadata"]["status"], "in_progress")
            report.set_environment("rclone_version", "v1.65.0")
            report.record_preflight(False, ["Disk full"], True)
            report.record_user_choice(
                "Dependency issues found", "y", options=["Continue", "Cancel"]
            )
            report.record_user_choice("Continue?", "n")
            report.start_stage("pack")
            report.set_pack_dependency_size(999)
            report.complete_stage("pack")
            report.start_stage("upload")
            report.start_upload_step(
                1, 1, "deps",
                manifest_entries=42,
                expected_bytes=1_000_000,
                source="/mnt/data",
                destination=":s3:bucket/proj/",
                verb="copy",
            )
            report.add_upload_split_group(
                group_name="textures", file_count=3,
                source="/textures", destination=":s3:bucket/proj/textures/",
                rclone_stats={"bytes_transferred": 1234, "checks": 3, "transfers": 3,
                              "errors": 0, "stats_received": True},
            )
            report.complete_upload_step(
                bytes_transferred=0,
                rclone_stats={
                    "stats_received": False,
                    "checks": 0,
                    "transfers": 0,
                    "command": "rclone copy /src :s3:bucket/ --s3-access-key-id ***",
                },
            )
            report.complete_stage("upload")
            report.finalize()

            with open(report.get_path(), "r", encoding="utf-8") as f:
                data = json.load(f)

        meta = data["metadata"]
        self.assertEqual(meta["upload_type"], "PROJECT")
        self.assertEqual(meta["job_name"], "MyJob")
        self.assertEqual(meta["status"], "completed")
        self.assertIsNotNone(meta["completed_at"])
        self.assertEqual(data["environment"]["rclone_version"], "v1.65.0")
        self.assertIn("os", data["environment"])
        self.assertEqual(
            data["preflight"],
            {"passed": False, "issues": ["Disk full"], "user_override": True},
        )
        choices = data["user_choices"]
        self.assertEqual([c["choice"] for c in choices], ["y", "n"])
        self.assertEqual(choices[0]["options"], ["Continue", "Cancel"])
        self.assertNotIn("options", choices[1])
        self.assertEqual(
            data["stages"]["pack"]["summary"]["dependency_total_size"], 999
        )
        step = data["stages"]["upload"]["steps"][0]
        self.assertEqual(
            (step["source"], step["destination"], step["verb"]),
            ("/mnt/data", ":s3:bucket/proj/", "copy"),
        )
        self.assertEqual(step["manifest_entries"], 42)
        self.assertIn("no transfer stats", step["warning"])
        self.assertEqual(
            step["rclone_stats"]["command"],
            "rclone copy /src :s3:bucket/ --s3-access-key-id ***",
        )
        self.assertGreaterEqual(step["elapsed_seconds"], 0)
        group = step["split_groups"][0]
        self.assertEqual((group["group_name"], group["bytes_transferred"]), ("textures", 1234))
        for section in ("missing_files", "unreadable_files", "cross_drive_files"):
            self.assertIn(section, data["issues"])


# Report v3.0: upload summary (computed in complete_stage)


class TestReportUploadSummary(unittest.TestCase):
    """Test upload stage summary computation."""

    def test_upload_summary_computed(self):
        """complete_stage('upload') should compute summary from all steps."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="sum-test", blend_name="test",
            )
            report.start_stage("upload")

            # Step 1
            report.start_upload_step(1, 2, "Blend")
            report.complete_upload_step(
                bytes_transferred=5000,
                rclone_stats={"checks": 1, "transfers": 1, "errors": 0, "stats_received": True},
            )

            # Step 2 — with warning
            report.start_upload_step(2, 2, "Dependencies", expected_bytes=10000)
            report.complete_upload_step(
                bytes_transferred=0,
                rclone_stats={"checks": 0, "transfers": 0, "errors": 1, "stats_received": True},
            )

            report.complete_stage("upload")

            summary = report._data["stages"]["upload"]["summary"]
            self.assertEqual(summary["total_bytes_transferred"], 5000)
            self.assertEqual(summary["total_checks"], 1)
            self.assertEqual(summary["total_transfers"], 1)
            self.assertEqual(summary["total_errors"], 1)
            self.assertEqual(summary["step_count"], 2)
            self.assertTrue(summary["has_warnings"])
            self.assertIsInstance(summary["total_elapsed_seconds"], float)


# Report v3.0: elapsed_seconds and tail_lines truncation


class TestReportStepDetails(unittest.TestCase):
    """Test elapsed_seconds and tail_lines truncation in upload steps."""

    def test_tail_lines_truncated(self):
        """tail_lines > 20 should be truncated to last 20 entries."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="tail-test", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "test")

            long_tail = [f"line_{i}" for i in range(100)]
            report.complete_upload_step(
                bytes_transferred=1000,
                rclone_stats={
                    "checks": 5, "transfers": 5, "errors": 0,
                    "stats_received": True, "tail_lines": long_tail,
                },
            )

            step = report._data["stages"]["upload"]["steps"][0]
            stored_tail = step["rclone_stats"]["tail_lines"]
            self.assertEqual(len(stored_tail), 20)
            # Should keep the LAST 20 lines
            self.assertEqual(stored_tail[0], "line_80")
            self.assertEqual(stored_tail[-1], "line_99")
            self.assertTrue(step["rclone_stats"]["tail_lines_truncated"])

    def test_short_tail_not_truncated(self):
        """tail_lines <= 20 should not be truncated."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="short-tail", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "test")

            short_tail = [f"line_{i}" for i in range(5)]
            report.complete_upload_step(
                bytes_transferred=1000,
                rclone_stats={
                    "checks": 5, "transfers": 5, "errors": 0,
                    "stats_received": True, "tail_lines": short_tail,
                },
            )

            step = report._data["stages"]["upload"]["steps"][0]
            self.assertEqual(len(step["rclone_stats"]["tail_lines"]), 5)
            self.assertNotIn("tail_lines_truncated", step["rclone_stats"])


# Report v3.0: split upload groups


class TestReportSplitGroups(unittest.TestCase):
    """Test split upload group recording."""

    def test_split_groups_recorded(self):
        """add_upload_split_group should store group details in current step."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="split-test", blend_name="test",
            )
            report.start_stage("upload")
            report.start_upload_step(1, 1, "Uploading deps (split)")

            report.add_upload_split_group(
                group_name="Users",
                file_count=10,
                source="/Users",
                destination=":s3:bucket/proj/Users/",
                rclone_stats={
                    "bytes_transferred": 5000,
                    "checks": 10, "transfers": 10, "errors": 0,
                    "stats_received": True,
                },
            )
            report.add_upload_split_group(
                group_name="Projects",
                file_count=5,
                source="/Projects",
                destination=":s3:bucket/proj/Projects/",
                rclone_stats={
                    "bytes_transferred": 0,
                    "checks": 5, "transfers": 0, "errors": 0,
                    "stats_received": True,
                },
            )

            step = report._data["stages"]["upload"]["steps"][0]
            self.assertIn("split_groups", step)
            groups = step["split_groups"]
            self.assertEqual(len(groups), 2)

            self.assertEqual(groups[0]["group_name"], "Users")
            self.assertEqual(groups[0]["file_count"], 10)
            self.assertEqual(groups[0]["bytes_transferred"], 5000)
            self.assertNotIn("warning", groups[0])

            self.assertEqual(groups[1]["group_name"], "Projects")
            self.assertEqual(groups[1]["transfers"], 0)
            self.assertIn("warning", groups[1])

    def test_split_group_without_step(self):
        """add_upload_split_group with no current step should be a no-op."""
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="split-noop", blend_name="test",
            )
            # No start_upload_step called
            report.add_upload_split_group(
                group_name="test", file_count=1,
                source="/src", destination="/dst",
            )
            # Should not crash; upload steps list stays empty
            self.assertEqual(len(report._data["stages"]["upload"]["steps"]), 0)


# ZIP pack summary


class TestReportZipPackSummary(unittest.TestCase):
    def test_zip_pack_sizes_timings_and_member_stats_are_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            report = _diagnostic_report.DiagnosticReport(
                reports_dir=Path(d), job_id="zip-metrics", blend_name="test"
            )
            report.start_stage("pack")
            report.add_pack_entry(
                "scene.blend",
                "scene.blend",
                file_size=1500,
                archive_size=1000,
                method="Zstandard-9",
                elapsed_seconds=61.0,
            )
            report.set_zip_pack_summary(
                source_bytes=1500,
                archive_bytes=1150,
                preparation_elapsed=5.0,
                archive_write_elapsed=61.0,
                total_elapsed=66.0,
            )
            report.complete_stage("pack")

            entry = report._data["stages"]["pack"]["entries"][0]
            summary = report._data["stages"]["pack"]["summary"]
            self.assertEqual(entry["source_size_bytes"], 1500)
            self.assertEqual(entry["archive_data_size_bytes"], 1000)
            self.assertEqual(entry["archive_method"], "Zstandard-9")
            self.assertEqual(entry["elapsed_seconds"], 61.0)
            self.assertEqual(summary["source_size_bytes"], 1500)
            self.assertEqual(summary["zip_archive_size_bytes"], 1150)
            self.assertEqual(summary["preparation_elapsed_seconds"], 5.0)
            self.assertEqual(summary["archive_write_elapsed_seconds"], 61.0)
            self.assertEqual(summary["total_elapsed_seconds"], 66.0)


# _check_risky_path_chars


class TestCheckRiskyPathChars(unittest.TestCase):
    """Test preflight warning for shell-risky path characters."""

    def setUp(self):
        self._check = _submit_worker._check_risky_path_chars

    def test_lists_every_risky_character_found(self):
        result = self._check("C:/Dropbox (Personal)/Grog's $project/file.blend")
        for shown in ("'('", "')'", "\"'\"", "' '", "'$'"):
            self.assertIn(shown, result)

    def test_each_risky_character_is_detected(self):
        for char in "()'\"` &|;$!#":
            with self.subTest(char=char):
                self.assertIsNotNone(self._check(f"/path/with{char}char/file.blend"))

    def test_safe_paths_do_not_warn(self):
        for path in (
            "/home/user/projects/my_project/scene.blend",
            "",
            "C:\\Users\\artist\\project\\file.blend",
        ):
            with self.subTest(path=path):
                self.assertIsNone(self._check(path))


# Farm ZIP unpack filename guards


class TestFarmZipUnpackGuards(unittest.TestCase):
    """Test submit-side guards for ZIP names the farm extractor skips."""

    def test_consecutive_dots_blocked_anywhere_in_archive_name(self):
        blocked = _submit_worker._farm_unpack_blocked_archive_names(
            ["Animation/Animations/On its own, a discrepancy between....blend"]
        )
        self.assertEqual(
            blocked,
            ["Animation/Animations/On its own, a discrepancy between....blend"],
        )

    def test_normal_archive_names_allowed(self):
        blocked = _submit_worker._farm_unpack_blocked_archive_names(
            [
                "Animation/Animations/Camille made a phone call.blend",
                "textures/painted.v001.png",
            ]
        )
        self.assertEqual(blocked, [])

    def test_leading_slash_blocked(self):
        blocked = _submit_worker._farm_unpack_blocked_archive_names(
            ["/Animation/Animations/scene.blend"]
        )
        self.assertEqual(blocked, ["/Animation/Animations/scene.blend"])

    def test_cross_platform_basename_handles_windows_paths(self):
        name = _submit_worker._path_basename_cross_platform(
            "G:\\Dropbox\\Animation\\broken....blend"
        )
        self.assertEqual(name, "broken....blend")

    def test_blocking_message_explains_rename_and_resubmit(self):
        msg = _submit_worker._format_farm_unpack_blocking_message(
            ["Animation/Animations/broken....blend"]
        )
        self.assertIn("Submission cancelled", msg)
        self.assertIn("consecutive dots", msg)
        self.assertIn("save the .blend", msg)
        self.assertIn("submit again", msg)
        self.assertIn("Animation/Animations/broken....blend", msg)

    def test_zip_member_validation_reads_actual_archive_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "scene.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Animation/Animations/broken....blend", b"")
                archive.writestr("textures/safe.png", b"")

            blocked = _submit_worker._farm_unpack_blocked_zip_members(zip_path)

        self.assertEqual(blocked, ["Animation/Animations/broken....blend"])


if __name__ == "__main__":
    unittest.main()
