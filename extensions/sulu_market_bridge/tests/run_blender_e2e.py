"""Build, install, and run the packaged bridge against official Blender 5.2."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from tests.mock_market import VALID_TICKET, MockMarketServer, descriptor_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    print(completed.stdout, end="")
    if completed.returncode:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}: {command[0]}")
    return completed


def isolated_environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = {
        "BLENDER_USER_CONFIG": root / "config",
        "BLENDER_USER_SCRIPTS": root / "scripts",
        "BLENDER_USER_EXTENSIONS": root / "extensions",
        "BLENDER_USER_DATAFILES": root / "datafiles",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    env.update({name: str(path) for name, path in paths.items()})
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--blender",
        type=Path,
        default=Path("/Volumes/Blender/Blender.app/Contents/MacOS/Blender"),
    )
    parser.add_argument("--keep-workdir", action="store_true")
    options = parser.parse_args()
    blender = options.blender.resolve()
    if not blender.is_file():
        raise SystemExit(f"Official Blender binary not found: {blender}")

    workdir = Path(tempfile.mkdtemp(prefix="sulu-market-bridge-e2e-"))
    try:
        env = isolated_environment(workdir / "user")
        build_dir = workdir / "build"
        build_dir.mkdir()
        fixture_path = workdir / "fixture" / "sulu-fixture.blend"

        run([str(blender), "--command", "extension", "validate", str(REPO_ROOT)], env=env)
        run(
            [
                str(blender),
                "--command",
                "extension",
                "build",
                "--source-dir",
                str(REPO_ROOT),
                "--output-dir",
                str(build_dir),
            ],
            env=env,
        )
        archive = build_dir / "sulu_market_bridge-0.1.0.zip"
        run(
            [
                str(blender),
                "--command",
                "extension",
                "repo-add",
                "--clear-all",
                "--name",
                "Sulu Bridge E2E",
                "--directory",
                str(workdir / "user" / "extensions" / "user_default"),
                "user_default",
            ],
            env=env,
        )
        run(
            [
                str(blender),
                "--command",
                "extension",
                "install-file",
                "-r",
                "user_default",
                "-e",
                str(archive),
            ],
            env=env,
        )
        listed = run([str(blender), "--command", "extension", "list"], env=env)
        if "sulu_market_bridge [installed]" not in listed.stdout:
            raise RuntimeError("Packaged bridge was not listed as installed")

        run(
            [
                str(blender),
                "--background",
                "--factory-startup",
                "--python",
                str(REPO_ROOT / "tests" / "blender_fixture_create.py"),
                "--",
                str(fixture_path),
            ],
            env=env,
        )
        artifact = fixture_path.read_bytes()
        expected_sha256 = hashlib.sha256(artifact).hexdigest()

        with MockMarketServer(artifact) as server:
            descriptor_path = workdir / "SuluFixtureObject.suluasset"
            descriptor_path.write_bytes(descriptor_bytes(server.origin, VALID_TICKET))
            completed = run(
                [
                    str(blender),
                    "--background",
                    "--online-mode",
                    "--python",
                    str(REPO_ROOT / "tests" / "blender_e2e_inner.py"),
                    "--",
                    str(descriptor_path),
                    server.origin,
                    expected_sha256,
                ],
                env=env,
            )
            if "SULU_BRIDGE_E2E_OK" not in completed.stdout:
                raise RuntimeError("Real Blender E2E did not emit its success marker")
            paths = [path for _, path in server.state.requests]
            if any(VALID_TICKET in path for path in paths):
                raise RuntimeError("One-use ticket leaked into an HTTP request URL")
            if len(server.state.redeem_bodies) != 2:
                raise RuntimeError("Expected one successful redemption and one denied replay")

        print(
            f"SULU_BRIDGE_PACKAGED_E2E_OK blender={blender} "
            f"sha256={expected_sha256} isolated_user={workdir / 'user'}"
        )
    finally:
        if options.keep_workdir:
            print(f"Keeping E2E work directory: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
