"""Run pure tests and the official Blender packaged E2E."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-v"],
    cwd=root,
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "tests.run_blender_e2e", *sys.argv[1:]],
    cwd=root,
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "tests.run_asset_processor_e2e", *sys.argv[1:]],
    cwd=root,
    check=True,
)
