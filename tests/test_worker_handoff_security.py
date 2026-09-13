from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from utils import worker_utils


@pytest.fixture
def handoff_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(worker_utils.tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def _capture_launch(monkeypatch):
    launched = []
    monkeypatch.setattr(
        worker_utils, "launch_in_terminal", lambda command: launched.append(command)
    )
    return launched


def _require_symlink(directory: Path) -> None:
    target = directory / "symlink-capability-target"
    link = directory / "symlink-capability-link"
    target.write_text("sentinel", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    else:
        link.unlink()


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "",
        ".",
        "..",
        "../outside.json",
        "nested/handoff.json",
        r"..\outside.json",
        r"nested\handoff.json",
        "/tmp/outside.json",
        r"C:\Temp\outside.json",
        r"C:drive-relative.json",
        r"\\server\share\outside.json",
    ],
)
def test_handoff_name_must_be_a_cross_platform_basename(
    monkeypatch, handoff_dir, unsafe_name
):
    launched = _capture_launch(monkeypatch)

    with pytest.raises(ValueError, match="plain basename"):
        worker_utils.launch_worker_secure(
            handoff_dir / "worker.py",
            {"user_token": "dummy-test-token"},
            unsafe_name,
            python_executable="python",
        )

    assert launched == []
    assert list(handoff_dir.iterdir()) == []


def test_handoff_name_must_be_a_string(monkeypatch, handoff_dir):
    launched = _capture_launch(monkeypatch)

    with pytest.raises(TypeError, match="must be a string"):
        worker_utils.launch_worker_secure(
            handoff_dir / "worker.py",
            {"user_token": "dummy-test-token"},
            Path("handoff.json"),
            python_executable="python",
        )

    assert launched == []
    assert list(handoff_dir.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_handoff_is_owner_only_and_preserves_worker_command(
    monkeypatch, handoff_dir
):
    launched = _capture_launch(monkeypatch)
    payload = {"user_token": "dummy-test-token", "environment": "test"}
    worker = handoff_dir / "worker.py"

    previous_umask = os.umask(0)
    try:
        handoff_path = worker_utils.launch_worker_secure(
            worker,
            payload,
            "superluminal_test-job.json",
            python_executable="/opt/blender/python",
            python_args=("--factory-startup",),
        )
    finally:
        os.umask(previous_umask)

    assert handoff_path == handoff_dir / "superluminal_test-job.json"
    assert json.loads(handoff_path.read_text("utf-8")) == payload
    assert stat.S_IMODE(handoff_path.stat().st_mode) == 0o600
    assert launched == [
        [
            "/opt/blender/python",
            "--factory-startup",
            "-I",
            "-u",
            str(worker),
            str(handoff_path),
        ]
    ]


def test_existing_symlink_is_replaced_without_touching_its_target(
    monkeypatch, handoff_dir
):
    _require_symlink(handoff_dir)
    launched = _capture_launch(monkeypatch)
    victim = handoff_dir / "victim.json"
    victim.write_text("sentinel", encoding="utf-8")
    handoff_path = handoff_dir / "superluminal_linked.json"
    handoff_path.symlink_to(victim)

    result = worker_utils.launch_worker_secure(
        handoff_dir / "worker.py",
        {"user_token": "dummy-test-token"},
        handoff_path.name,
        python_executable="python",
    )

    assert result == handoff_path
    assert not handoff_path.is_symlink()
    assert victim.read_text("utf-8") == "sentinel"
    assert json.loads(handoff_path.read_text("utf-8")) == {
        "user_token": "dummy-test-token"
    }
    assert len(launched) == 1


def test_raced_path_is_never_opened_or_removed(monkeypatch, handoff_dir):
    _require_symlink(handoff_dir)
    launched = _capture_launch(monkeypatch)
    victim = handoff_dir / "race-victim.json"
    victim.write_text("sentinel", encoding="utf-8")
    handoff_path = handoff_dir / "superluminal_race.json"
    real_open = os.open
    inserted = False

    def insert_link_before_open(path, flags, mode=0o777):
        nonlocal inserted
        if Path(path) == handoff_path and not inserted:
            assert flags & os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                assert flags & os.O_NOFOLLOW
            inserted = True
            handoff_path.symlink_to(victim)
        return real_open(path, flags, mode)

    monkeypatch.setattr(worker_utils.os, "open", insert_link_before_open)

    with pytest.raises(FileExistsError):
        worker_utils.launch_worker_secure(
            handoff_dir / "worker.py",
            {"user_token": "dummy-test-token"},
            handoff_path.name,
            python_executable="python",
        )

    assert inserted is True
    assert handoff_path.is_symlink()
    assert victim.read_text("utf-8") == "sentinel"
    assert launched == []


def test_non_posix_path_does_not_require_posix_permission_apis(
    monkeypatch, handoff_dir
):
    launched = _capture_launch(monkeypatch)
    monkeypatch.setattr(worker_utils, "_POSIX_OWNER_PERMISSIONS", False)

    def unavailable(*_args, **_kwargs):
        raise AssertionError("POSIX-only permission API was called")

    if hasattr(worker_utils.os, "fchmod"):
        monkeypatch.setattr(worker_utils.os, "fchmod", unavailable)
    if hasattr(worker_utils.os, "geteuid"):
        monkeypatch.setattr(worker_utils.os, "geteuid", unavailable)

    handoff_path = worker_utils.launch_worker_secure(
        handoff_dir / "worker.py",
        {"user_token": "dummy-test-token"},
        "superluminal_windows-safe.json",
        python_executable="python.exe",
    )

    assert json.loads(handoff_path.read_text("utf-8"))["user_token"] == (
        "dummy-test-token"
    )
    assert len(launched) == 1


def test_launch_failure_removes_the_owned_handoff(monkeypatch, handoff_dir):
    handoff_path = handoff_dir / "superluminal_launch-failure.json"

    def fail_launch(_command):
        raise RuntimeError("terminal unavailable")

    monkeypatch.setattr(worker_utils, "launch_in_terminal", fail_launch)

    with pytest.raises(RuntimeError, match="terminal unavailable"):
        worker_utils.launch_worker_secure(
            handoff_dir / "worker.py",
            {"user_token": "dummy-test-token"},
            handoff_path.name,
            python_executable="python",
        )

    assert not handoff_path.exists()
