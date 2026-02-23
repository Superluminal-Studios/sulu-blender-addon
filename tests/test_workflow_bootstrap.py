from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_bootstrap = importlib.import_module("transfers.submit.workflow_bootstrap")


class TestWorkflowBootstrap(unittest.TestCase):
    def test_resolve_bootstrap_deps_builds_typed_container(self):
        safe_input_calls = []
        set_logger_calls = []

        worker_utils = types.SimpleNamespace(
            logger=lambda msg: None,
            safe_input=lambda prompt, default, log_fn=None: safe_input_calls.append(
                (prompt, default, log_fn)
            )
            or "ok",
            clear_console=lambda: None,
            shorten_path=lambda p: p,
            is_blend_saved=lambda *args, **kwargs: None,
            requests_retry_session=lambda: None,
            _build_base=lambda *args, **kwargs: ["rclone"],
            CLOUDFLARE_R2_DOMAIN="example.com",
            open_folder=lambda *args, **kwargs: None,
            count=lambda n, w: f"{n} {w}",
            format_size=lambda n: str(n),
            normalize_nfc=lambda s: s,
            debug_enabled=lambda: False,
            is_interactive=lambda: False,
            norm_abs_for_detection=lambda p: p,
            relpath_safe=lambda p, b: p,
            s3key_clean=lambda k: k,
            samepath=lambda a, b: a == b,
            mac_permission_help=lambda p, e: "",
        )

        module_map = {
            "pkg.utils.worker_utils": worker_utils,
            "pkg.utils.bat_utils": types.SimpleNamespace(
                pack_blend=lambda *args, **kwargs: ({}, None),
                trace_dependencies=lambda *args, **kwargs: ([], set(), {}, [], set()),
                compute_project_root=lambda *args, **kwargs: (Path("/"), [], []),
                classify_out_of_root_ok_files=lambda *args, **kwargs: [],
            ),
            "pkg.utils.project_upload_validator": types.SimpleNamespace(
                validate_project_upload=lambda **kwargs: None,
                validate_manifest_entries=lambda *args, **kwargs: None,
            ),
            "pkg.utils.diagnostic_schema": types.SimpleNamespace(
                META_PROJECT_VALIDATION_VERSION="project_validation_version",
                META_PROJECT_VALIDATION_STATS="project_validation_stats",
                META_MANIFEST_ENTRY_COUNT="manifest_entry_count",
                META_MANIFEST_SOURCE_MATCH_COUNT="manifest_source_match_count",
                META_MANIFEST_VALIDATION_STATS="manifest_validation_stats",
                DEFAULT_PROJECT_VALIDATION_VERSION="1.0",
                UPLOAD_TOUCHED_LT_MANIFEST="UPLOAD_TOUCHED_LT_MANIFEST",
            ),
            "pkg.transfers.submit.workflow_prompts": types.SimpleNamespace(
                prompt_continue_with_reports=lambda **kwargs: True
            ),
            "pkg.transfers.submit.workflow_manifest": types.SimpleNamespace(
                build_project_manifest_from_map=lambda **kwargs: None,
                apply_manifest_validation=lambda **kwargs: ([], True),
                write_manifest_file=lambda *args, **kwargs: None,
                validate_manifest_writeback=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_upload": types.SimpleNamespace(
                split_manifest_by_first_dir=lambda rel: {},
                record_manifest_touch_mismatch=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_submit": types.SimpleNamespace(
                build_job_payload=lambda **kwargs: {},
            ),
            "pkg.transfers.submit.workflow_trace": types.SimpleNamespace(
                apply_project_validation=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_preflight": types.SimpleNamespace(
                run_preflight_phase=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_trace_project_runner": types.SimpleNamespace(
                run_trace_project_stage=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_trace_zip_runner": types.SimpleNamespace(
                run_trace_zip_stage=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_pack_project_runner": types.SimpleNamespace(
                run_pack_project_stage=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_pack_zip_runner": types.SimpleNamespace(
                run_pack_zip_stage=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_trace_pack_runner": types.SimpleNamespace(
                run_trace_and_pack_stage=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_upload_runner": types.SimpleNamespace(
                run_upload_stage=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_no_submit": types.SimpleNamespace(
                handle_no_submit_mode=lambda **kwargs: None,
            ),
            "pkg.transfers.submit.workflow_finalize": types.SimpleNamespace(
                finalize_submission=lambda **kwargs: None,
            ),
            "pkg.utils.cloud_files": types.SimpleNamespace(),
            "pkg.utils.submit_logger": types.SimpleNamespace(
                create_logger=lambda *args, **kwargs: None
            ),
            "pkg.transfers.rclone_utils": types.SimpleNamespace(
                run_rclone=lambda *args, **kwargs: None,
                ensure_rclone=lambda *args, **kwargs: "rclone",
            ),
            "pkg.utils.diagnostic_report": types.SimpleNamespace(
                DiagnosticReport=object,
                generate_test_report=lambda **kwargs: ({}, None),
            ),
        }

        def _fake_import(name):
            return module_map[name]

        with patch.object(workflow_bootstrap.importlib, "import_module", side_effect=_fake_import):
            deps = workflow_bootstrap.resolve_bootstrap_deps(
                pkg_name="pkg",
                set_logger_fn=lambda fn: set_logger_calls.append(fn),
                log_fn=lambda msg: None,
            )

        self.assertEqual("pkg", deps.pkg_name)
        self.assertEqual(1, len(set_logger_calls))
        self.assertIs(set_logger_calls[0], worker_utils.logger)
        self.assertEqual("ok", deps.safe_input("Prompt", "Default"))
        self.assertEqual("Prompt", safe_input_calls[0][0])
        self.assertEqual("Default", safe_input_calls[0][1])
        self.assertTrue(callable(deps.run_trace_project_stage))
        self.assertTrue(callable(deps.run_trace_zip_stage))
        self.assertTrue(callable(deps.run_pack_project_stage))
        self.assertTrue(callable(deps.run_pack_zip_stage))


if __name__ == "__main__":
    unittest.main()
