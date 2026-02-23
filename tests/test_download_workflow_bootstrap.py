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

workflow_bootstrap = importlib.import_module("transfers.download.workflow_bootstrap")
workflow_types = importlib.import_module("transfers.download.workflow_types")


class TestDownloadWorkflowBootstrap(unittest.TestCase):
    def test_resolve_bootstrap_deps_builds_typed_container(self):
        worker_utils = types.SimpleNamespace(
            clear_console=lambda: None,
            open_folder=lambda path: None,
            requests_retry_session=lambda: object(),
            run_preflight_checks=lambda **kwargs: (True, []),
            _build_base=lambda *args, **kwargs: ["rclone"],
            CLOUDFLARE_R2_DOMAIN="example.com",
        )

        module_map = {
            "pkg.utils.worker_utils": worker_utils,
            "pkg.utils.download_logger": types.SimpleNamespace(
                DownloadLogger=object,
                create_logger=lambda: object(),
            ),
            "pkg.transfers.rclone_utils": types.SimpleNamespace(
                ensure_rclone=lambda **kwargs: "/tmp/rclone",
                run_rclone=lambda *args, **kwargs: None,
            ),
            "pkg.transfers.download.workflow_context": types.SimpleNamespace(
                build_download_context=lambda data: "ctx",
                ensure_dir=lambda path: None,
            ),
            "pkg.transfers.download.workflow_preflight": types.SimpleNamespace(
                run_preflight_phase=lambda **kwargs: "preflight",
            ),
            "pkg.transfers.download.workflow_storage": types.SimpleNamespace(
                resolve_storage=lambda **kwargs: "storage",
            ),
            "pkg.transfers.download.workflow_transfer": types.SimpleNamespace(
                run_download_dispatch=lambda **kwargs: "dispatch",
            ),
            "pkg.transfers.download.workflow_finalize": types.SimpleNamespace(
                finalize_download=lambda **kwargs: None,
            ),
        }

        def _fake_import(name):
            return module_map[name]

        with patch.object(workflow_bootstrap.importlib, "import_module", side_effect=_fake_import):
            deps = workflow_bootstrap.resolve_bootstrap_deps(pkg_name="pkg")

        self.assertIsInstance(deps, workflow_types.BootstrapDeps)
        self.assertEqual("example.com", deps.cloudflare_r2_domain)
        self.assertTrue(callable(deps.clear_console))
        self.assertTrue(callable(deps.open_folder))
        self.assertTrue(callable(deps.requests_retry_session))
        self.assertTrue(callable(deps.run_preflight_checks))
        self.assertTrue(callable(deps.ensure_rclone))
        self.assertTrue(callable(deps.run_rclone))
        self.assertTrue(callable(deps.build_base_fn))
        self.assertTrue(callable(deps.create_logger))
        self.assertTrue(callable(deps.build_download_context))
        self.assertTrue(callable(deps.run_preflight_phase))
        self.assertTrue(callable(deps.resolve_storage))
        self.assertTrue(callable(deps.run_download_dispatch))
        self.assertTrue(callable(deps.finalize_download))


if __name__ == "__main__":
    unittest.main()
