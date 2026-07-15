"""Build, install, and run the packaged bridge against official Blender 5.2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

from tests.mock_market import VALID_TICKET, MockMarketServer, descriptor_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]


def assert_hash_reference(path: Path, reference: str) -> None:
    algorithm, separator, expected = reference.partition(":")
    if algorithm != "SHA256" or separator != ":":
        raise RuntimeError("stock asset listing used an unsupported hash reference")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("stock asset listing hash does not match its document")


def run(
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
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


def default_backend_pocketbase() -> Path:
    return REPO_ROOT.parents[1].parent / "sulu-backend" / "pocketbase"


def validate_with_backend(
    archive: Path,
    backend_pocketbase: Path,
    *,
    env: dict[str, str],
    extension_id: str,
    extension_version: str,
) -> None:
    if not (backend_pocketbase / "market_extension_archive_security.go").is_file():
        raise RuntimeError(
            "Sulu backend PocketBase source was not found; pass --backend-pocketbase so the "
            "exact Bridge archive can be checked by the production extension validator"
        )
    validation_env = env.copy()
    validation_env.update(
        {
            "SULU_EXTENSION_ARCHIVE_FIXTURE": str(archive),
            "SULU_EXTENSION_EXPECTED_ID": extension_id,
            "SULU_EXTENSION_EXPECTED_VERSION": extension_version,
        }
    )
    completed = run(
        [
            "go",
            "test",
            "-count=1",
            "-run",
            "^TestValidateExternalMarketExtensionFixture$",
            "-v",
            ".",
        ],
        env=validation_env,
        cwd=backend_pocketbase,
    )
    marker = (
        f"SULU_EXTENSION_ARCHIVE_VALIDATED id={extension_id} version={extension_version}"
    )
    if marker not in completed.stdout:
        raise RuntimeError("Backend extension validator did not emit its success marker")


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
    parser.add_argument(
        "--backend-pocketbase",
        type=Path,
        default=default_backend_pocketbase(),
        help="Path to sulu-backend/pocketbase for the production archive-validator gate",
    )
    parser.add_argument("--keep-workdir", action="store_true")
    options = parser.parse_args()
    blender = options.blender.resolve()
    if not blender.is_file():
        raise SystemExit(f"Official Blender binary not found: {blender}")
    manifest = tomllib.loads((REPO_ROOT / "blender_manifest.toml").read_text(encoding="utf-8"))
    extension_id = manifest["id"]
    extension_version = manifest["version"]

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
        archive = build_dir / f"{extension_id}-{extension_version}.zip"
        if not archive.is_file():
            raise RuntimeError("Blender did not build the expected versioned Bridge archive")
        with zipfile.ZipFile(archive) as built_extension:
            shipped_scripts = [
                name for name in built_extension.namelist() if "scripts" in Path(name).parts
            ]
        if shipped_scripts:
            raise RuntimeError("Seller processing scripts leaked into the extension ZIP")
        validate_with_backend(
            archive,
            options.backend_pocketbase.resolve(),
            env=env,
            extension_id=extension_id,
            extension_version=extension_version,
        )
        publication = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "sulu_bridge_market_publication.json").read_text(
                encoding="utf-8"
            )
        )

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

        with MockMarketServer(
            artifact,
            extension_archive=archive.read_bytes(),
            extension_publication=publication,
        ) as server:
            repository = publication["repository"]
            run(
                [
                    str(blender),
                    "--online-mode",
                    "--command",
                    "extension",
                    "repo-add",
                    "--clear-all",
                    "--name",
                    repository["name"],
                    "--directory",
                    str(workdir / "user" / "extensions" / repository["id"]),
                    "--url",
                    server.extension_repository_url,
                    "--access-token",
                    repository["access_token"],
                    repository["id"],
                ],
                env=env,
            )
            run(
                [str(blender), "--online-mode", "--command", "extension", "sync"],
                env=env,
            )
            run(
                [
                    str(blender),
                    "--online-mode",
                    "--command",
                    "extension",
                    "install",
                    "-e",
                    publication["version"]["extension_id"],
                ],
                env=env,
            )
            listed = run([str(blender), "--command", "extension", "list"], env=env)
            if "sulu_market_bridge [installed]" not in listed.stdout:
                raise RuntimeError("Repository-installed Bridge was not listed as installed")

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
            extension_paths = [path for path, authorized in server.state.extension_requests if authorized]
            expected_repo_path = (
                f"/api/market/extensions/repo/v1/org/{publication['organization']['id']}/index.json"
            )
            expected_archive_path = (
                f"/api/market/extensions/archive/org/{publication['organization']['id']}/product/"
                f"{publication['product']['id']}/version/{publication['version']['id']}.zip"
            )
            if expected_repo_path not in extension_paths or expected_archive_path not in extension_paths:
                raise RuntimeError(
                    "Stock Blender did not sync the entitled repository and fetch its exact Bridge archive"
                )
            if any(not authorized for _, authorized in server.state.extension_requests):
                raise RuntimeError("Stock Blender omitted repository authorization")
            if any(
                publication["repository"]["access_token"] in path
                for _, path in server.state.requests
            ):
                raise RuntimeError("Repository access token leaked into a request URL")

        cache_root = (
            Path(env["BLENDER_USER_DATAFILES"])
            / "sulu_market_bridge"
            / "redeemed_assets"
        )
        listing = run(
            [
                str(blender),
                "--factory-startup",
                "--disable-autoexec",
                "--offline-mode",
                "--command",
                "asset_listing",
                "generate",
                str(cache_root),
            ],
            env=env,
        )
        if "1 .blend files found" not in listing.stdout:
            raise RuntimeError("stock Blender did not recursively discover the fan-out bridge cache")
        meta = json.loads((cache_root / "_asset-library-meta.json").read_text(encoding="utf-8"))
        index_reference = meta["api_versions"]["v1"]
        index_path = cache_root / index_reference["url"]
        assert_hash_reference(index_path, index_reference["hash"])
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if index["asset_count"] != 1 or len(index["pages"]) != 1:
            raise RuntimeError("stock Blender emitted the wrong bridge cache listing cardinality")
        page_reference = index["pages"][0]
        page_path = cache_root / page_reference["url"]
        assert_hash_reference(page_path, page_reference["hash"])
        page = json.loads(page_path.read_text(encoding="utf-8"))
        expected_relative = f"objects/{expected_sha256[:2]}/{expected_sha256}.blend"
        if (
            len(page["files"]) != 1
            or page["files"][0]["path"] != expected_relative
            or page["files"][0]["hash"] != f"SHA256:{expected_sha256}"
        ):
            raise RuntimeError("stock Blender listing did not preserve the fan-out path and hash")
        if len(page["assets"]) != 1 or page["assets"][0]["name"] != "SuluFixtureObject":
            raise RuntimeError("stock Blender listing did not discover the redeemed OBJECT asset")

        print(
            f"SULU_BRIDGE_PACKAGED_E2E_OK blender={blender} "
            f"sha256={expected_sha256} distribution=entitled_remote_repository "
            f"isolated_user={workdir / 'user'}"
        )
    finally:
        if options.keep_workdir:
            print(f"Keeping E2E work directory: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
