from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import bpy

from .worker_utils import launch_in_terminal


def blender_python_args() -> list[str]:
    """Return Blender's recommended Python flags when available."""
    try:
        args = getattr(bpy.app, "python_args", ())
        return list(args) if args else []
    except Exception:
        return []


def launch_worker(worker_py: str | Path, handoff: dict[str, Any], tmp_name: str) -> Path:
    """Write a worker handoff and launch it with Blender's Python."""
    handoff_path = Path(tempfile.gettempdir()) / tmp_name
    # The handoff carries user_token and sarfis_token into a world-readable temp
    # dir, so it must never be created with default permissions. The worker
    # unlinks it right after reading. Unlink first: O_CREAT's mode is ignored for
    # an existing path, so a stale handoff would keep its old permissions.
    handoff_path.unlink(missing_ok=True)
    fd = os.open(handoff_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(handoff, fh)

    # -I makes Python ignore PYTHON* env vars & user-site, preventing stdlib leakage.
    cmd = [
        sys.executable,
        *blender_python_args(),
        "-I",
        "-u",
        str(worker_py),
        str(handoff_path),
    ]
    launch_in_terminal(cmd)
    return handoff_path
