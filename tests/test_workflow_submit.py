from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


workflow_submit = importlib.import_module("transfers.submit.workflow_submit")


class TestWorkflowSubmit(unittest.TestCase):
    def test_build_job_payload_project_mode(self):
        data = {
            "job_id": "job-1",
            "project": {"id": "proj-1"},
            "packed_addons": [],
            "job_name": "Render",
            "start_frame": 1,
            "end_frame": 3,
            "frame_stepping_size": 1,
            "image_format": "PNG",
            "render_engine": "CYCLES",
            "blender_version": "4.2",
            "ignore_errors": False,
            "use_bserver": False,
            "use_async_upload": True,
            "farm_url": "https://farm",
        }

        payload = workflow_submit.build_job_payload(
            data=data,
            org_id="org-1",
            project_name="MyProject",
            blend_path="/tmp/proj/scene.blend",
            project_root_str="/tmp/proj",
            main_blend_s3="input/scene.blend",
            required_storage=123,
            use_project=True,
            normalize_nfc_fn=lambda x: x,
            clean_key_fn=lambda x: x.strip("/"),
        )

        self.assertEqual("input/scene.blend", payload["job_data"]["main_file"])
        self.assertEqual([1, 2, 3], payload["job_data"]["tasks"])
        self.assertFalse(payload["job_data"]["zip"])

    def test_build_job_payload_zip_mode_main_file_relative(self):
        data = {
            "job_id": "job-1",
            "project": {"id": "proj-1"},
            "packed_addons": [],
            "job_name": "Render",
            "start_frame": 1,
            "end_frame": 1,
            "image_format": "SCENE",
            "render_engine": "CYCLES",
            "blender_version": "4.2",
            "ignore_errors": False,
            "use_bserver": False,
            "use_async_upload": False,
            "farm_url": "https://farm",
        }

        payload = workflow_submit.build_job_payload(
            data=data,
            org_id="org-1",
            project_name="MyProject",
            blend_path="/tmp/proj/scenes/shot.blend",
            project_root_str="/tmp/proj",
            main_blend_s3="ignored.blend",
            required_storage=456,
            use_project=False,
            normalize_nfc_fn=lambda x: x,
            clean_key_fn=lambda x: x,
        )

        self.assertEqual("scenes/shot.blend", payload["job_data"]["main_file"])
        self.assertTrue(payload["job_data"]["zip"])
        self.assertTrue(payload["job_data"]["use_scene_image_format"])


if __name__ == "__main__":
    unittest.main()
