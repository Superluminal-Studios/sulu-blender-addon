from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

import requests

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

workflow_types = importlib.import_module("transfers.download.workflow_types")
workflow_storage = importlib.import_module("transfers.download.workflow_storage")


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, mode: str):
        self.mode = mode

    def get(self, *args, **kwargs):
        if self.mode == "request_error":
            raise requests.RequestException("network down")
        if self.mode == "empty":
            return _Response({"items": []})
        if self.mode == "missing_key":
            return _Response({"items": [{"id": "x"}]})
        return _Response({"items": [{"bucket_name": "render-bucket", "key": "value"}]})


def _context() -> workflow_types.DownloadRunContext:
    return workflow_types.DownloadRunContext(
        data={"project": {"id": "project-1"}, "pocketbase_url": "https://pb"},
        job_id="job1",
        job_name="Job 1",
        download_path="/tmp",
        dest_dir="/tmp/Job 1",
        download_type="single",
        sarfis_url=None,
        sarfis_token=None,
    )


class TestDownloadWorkflowStorage(unittest.TestCase):
    def test_resolve_storage_success(self):
        result = workflow_storage.resolve_storage(
            context=_context(),
            session=_Session("ok"),
            headers={"Authorization": "token"},
            rclone_bin="/tmp/rclone",
            build_base_fn=lambda *args: ["rclone", "base"],
            cloudflare_r2_domain="example.com",
        )
        self.assertIsNone(result.fatal_error)
        self.assertEqual("render-bucket", result.bucket)
        self.assertEqual(["rclone", "base"], result.base_cmd)
        self.assertEqual("render-bucket", result.s3info["bucket_name"])

    def test_resolve_storage_empty_items_returns_fatal(self):
        result = workflow_storage.resolve_storage(
            context=_context(),
            session=_Session("empty"),
            headers={"Authorization": "token"},
            rclone_bin="/tmp/rclone",
            build_base_fn=lambda *args: ["rclone"],
            cloudflare_r2_domain="example.com",
        )
        self.assertIn("Couldn't connect to storage", result.fatal_error or "")

    def test_resolve_storage_request_error_returns_fatal(self):
        result = workflow_storage.resolve_storage(
            context=_context(),
            session=_Session("request_error"),
            headers={"Authorization": "token"},
            rclone_bin="/tmp/rclone",
            build_base_fn=lambda *args: ["rclone"],
            cloudflare_r2_domain="example.com",
        )
        self.assertIn("Couldn't connect to storage", result.fatal_error or "")

    def test_resolve_storage_missing_bucket_returns_fatal(self):
        result = workflow_storage.resolve_storage(
            context=_context(),
            session=_Session("missing_key"),
            headers={"Authorization": "token"},
            rclone_bin="/tmp/rclone",
            build_base_fn=lambda *args: ["rclone"],
            cloudflare_r2_domain="example.com",
        )
        self.assertIn("Couldn't connect to storage", result.fatal_error or "")


if __name__ == "__main__":
    unittest.main()
