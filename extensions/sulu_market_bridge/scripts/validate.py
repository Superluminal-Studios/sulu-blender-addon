"""Run pure tests and the official Blender packaged E2E."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser()
parser.add_argument(
    "--blender",
    type=Path,
    default=Path("/Volumes/Blender/Blender.app/Contents/MacOS/Blender"),
)
parser.add_argument(
    "--backend-pocketbase",
    type=Path,
    default=root.parents[1].parent / "sulu-backend" / "pocketbase",
)
parser.add_argument("--keep-workdir", action="store_true")
options = parser.parse_args()

subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-v"],
    cwd=root,
    check=True,
)
shared = ["--blender", str(options.blender)]
if options.keep_workdir:
    shared.append("--keep-workdir")
subprocess.run(
    [
        sys.executable,
        "-m",
        "tests.run_blender_e2e",
        *shared,
        "--backend-pocketbase",
        str(options.backend_pocketbase),
    ],
    cwd=root,
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "tests.run_asset_processor_e2e", *shared],
    cwd=root,
    check=True,
)
