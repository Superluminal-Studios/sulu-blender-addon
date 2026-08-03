from __future__ import annotations

from unittest import mock

from utils import worker_utils


def test_operator_signature_skips_stability_sleep(tmp_path):
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"BLENDER")
    stat_result = blend.stat()

    with mock.patch.object(worker_utils.time, "sleep") as sleep:
        worker_utils.is_blend_saved(
            blend,
            expected_signature={
                "size": stat_result.st_size,
                "mtime_ns": stat_result.st_mtime_ns,
            },
        )

    sleep.assert_not_called()


def test_recent_blend_gets_short_stability_check(tmp_path):
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"BLENDER")

    with mock.patch.object(worker_utils.time, "sleep") as sleep:
        worker_utils.is_blend_saved(blend)

    assert sleep.call_count == 5
    sleep.assert_called_with(0.1)


def test_submission_preflight_can_reuse_required_api_date_header():
    with mock.patch.object(worker_utils, "check_time_sync") as check_time:
        ok, issues = worker_utils.run_preflight_checks(check_clock=False)

    assert ok is True
    assert issues == []
    check_time.assert_not_called()
