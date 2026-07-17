"""Exercise hostile seller processing and Blender's native remote listing end to end."""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Any

from scripts.asset_processing_contract import (
    mappings_document_from_manifest,
    validate_processing_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSOR = REPO_ROOT / "scripts" / "process_assets.py"
FIXTURE_CREATOR = REPO_ROOT / "tests" / "asset_processor_fixture_create.py"
IMPORT_VERIFIER = REPO_ROOT / "tests" / "asset_processor_import_verify.py"
NATIVE_ONLINE_VERIFIER = REPO_ROOT / "tests" / "native_online_asset_e2e_inner.py"


def isolated_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    paths = {
        "BLENDER_USER_CONFIG": root / "config",
        "BLENDER_USER_SCRIPTS": root / "scripts",
        "BLENDER_USER_EXTENSIONS": root / "extensions",
        "BLENDER_USER_DATAFILES": root / "datafiles",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    environment.update({name: str(path) for name, path in paths.items()})
    return environment


def run(
    command: list[str],
    *,
    environment: dict[str, str],
    expect_success: bool = True,
    expected_text: str | None = None,
    timeout: int = 240,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    print(completed.stdout, end="")
    if expect_success != (completed.returncode == 0):
        expectation = "succeed" if expect_success else "fail"
        raise RuntimeError(f"command was expected to {expectation}: {command[0]}")
    if expected_text is not None and expected_text not in completed.stdout:
        raise RuntimeError(f"command output did not contain expected marker: {expected_text}")
    return completed


def create_fixture(
    blender: Path,
    environment: dict[str, str],
    path: Path,
    kind: str,
) -> None:
    run(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "1",
            "--python",
            str(FIXTURE_CREATOR),
            "--",
            "--output",
            str(path),
            "--kind",
            kind,
        ],
        environment=environment,
        expected_text=f"SULU_ASSET_PROCESSOR_FIXTURE_OK kind={kind}",
    )


def processor_command(
    *,
    blender: Path,
    build_hash: str,
    source: Path,
    output: Path,
    mappings: Path | None = None,
    extra: list[str] | None = None,
    trusted_metadata: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(PROCESSOR),
        "--blender",
        str(blender),
        "--input",
        str(source),
        "--output",
        str(output),
        "--trusted-metadata",
        str(trusted_metadata),
        "--allow-unsafe-direct",
        "--expected-blender-build-hash",
        build_hash,
        "--timeout-seconds",
        "180",
    ]
    if mappings is not None:
        command.extend(["--mappings", str(mappings)])
    if extra:
        command.extend(extra)
    return command


def read_manifest(output: Path) -> dict[str, Any]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    validate_processing_manifest(manifest)
    return manifest


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def assert_hash_reference(path: Path, reference: str) -> None:
    algorithm, separator, expected = reference.partition(":")
    if algorithm != "SHA256" or separator != ":":
        raise RuntimeError("native listing used an unexpected hash algorithm")
    if sha256_bytes(path.read_bytes()) != expected:
        raise RuntimeError("native listing hash reference does not match its file")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def prove_native_listing_download_and_import(
    *,
    blender: Path,
    environment: dict[str, str],
    output: Path,
    manifest: dict[str, Any],
) -> None:
    run(
        [
            str(blender),
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--command",
            "asset_listing",
            "generate",
            str(output),
        ],
        environment=environment,
        expected_text="asset-index.json",
    )

    meta_path = output / "_asset-library-meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    index_reference = meta["api_versions"]["v1"]
    index_path = output / index_reference["url"]
    assert_hash_reference(index_path, index_reference["hash"])
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index["asset_count"] != len(manifest["assets"]):
        raise RuntimeError("native listing asset count disagrees with normalized manifest")
    if len(index["pages"]) != 1:
        raise RuntimeError("small E2E fixture should generate exactly one listing page")
    page_reference = index["pages"][0]
    page_path = output / page_reference["url"]
    assert_hash_reference(page_path, page_reference["hash"])
    page = json.loads(page_path.read_text(encoding="utf-8"))

    manifest_by_path = {asset["artifact"]["path"]: asset for asset in manifest["assets"]}
    native_files = {entry["path"]: entry for entry in page["files"]}
    if set(native_files) != set(manifest_by_path):
        raise RuntimeError("native listing file set disagrees with normalized manifest")
    for path, asset in manifest_by_path.items():
        native = native_files[path]
        if native["size_in_bytes"] != asset["artifact"]["size"]:
            raise RuntimeError("native listing file size disagrees with normalized manifest")
        if native["hash"] != f"SHA256:{asset['artifact']['sha256']}":
            raise RuntimeError("native listing hash disagrees with normalized manifest")
    listed_assets = {
        (asset["name"], asset["id_type"], tuple(asset["files"])) for asset in page["assets"]
    }
    expected_assets = {
        (asset["name"], asset["id_type"], (asset["artifact"]["path"],))
        for asset in manifest["assets"]
    }
    if listed_assets != expected_assets:
        raise RuntimeError("native asset listing disagrees with normalized manifest")
    native_assets_by_name = {asset["name"]: asset for asset in page["assets"]}
    for asset in manifest["assets"]:
        native_asset = native_assets_by_name[asset["name"]]
        thumbnail = native_asset.get("thumbnail")
        if not isinstance(thumbnail, dict):
            raise RuntimeError("stock listing omitted the processor-generated embedded preview")
        thumbnail_path = output / urllib.parse.unquote(thumbnail["url"])
        assert_hash_reference(thumbnail_path, thumbnail["hash"])

    def handler(*args: Any, **kwargs: Any) -> QuietHandler:
        return QuietHandler(*args, directory=str(output), **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        selected = manifest["assets"][0]
        relative_path = selected["artifact"]["path"]
        selected_thumbnail = native_assets_by_name[selected["name"]]["thumbnail"]
        run(
            [
                str(blender),
                "--background",
                "--factory-startup",
                "--online-mode",
                "--python-exit-code",
                "1",
                "--python",
                str(NATIVE_ONLINE_VERIFIER),
                "--",
                "--origin",
                f"http://127.0.0.1:{server.server_port}/",
                "--relative-path",
                relative_path,
                "--sha256",
                selected["artifact"]["sha256"],
                "--preview-relative-path",
                selected_thumbnail["url"],
                "--preview-hash",
                selected_thumbnail["hash"],
                "--name",
                selected["name"],
                "--immutable-id",
                selected["immutable_id"],
            ],
            environment=environment,
            expected_text="SULU_NATIVE_ONLINE_ASSET_E2E_OK",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    downloaded = output / relative_path
    run(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python-exit-code",
            "1",
            "--python",
            str(IMPORT_VERIFIER),
            "--",
            "--artifact",
            str(downloaded),
            "--name",
            selected["name"],
            "--immutable-id",
            selected["immutable_id"],
        ],
        environment=environment,
        expected_text="SULU_ASSET_PROCESSOR_IMPORT_OK",
    )


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
        raise SystemExit("official Blender 5.2 binary was not found")

    workdir = Path(tempfile.mkdtemp(prefix="sulu-market-processor-e2e-"))
    try:
        environment = isolated_environment(workdir / "user")
        version = run([str(blender), "--version"], environment=environment)
        match = re.search(
            r"Blender 5\.2\.[0-9]+.*?build hash:\s*([0-9a-f]+)",
            version.stdout,
            re.S,
        )
        if match is None:
            raise RuntimeError("E2E binary is not an identifiable official Blender 5.2 build")
        build_hash = match.group(1)

        fixtures = workdir / "fixtures"
        trusted_metadata = workdir / "trusted-metadata.json"
        trusted_metadata.write_text(
            json.dumps(
                {
                    "seller_org_id": "sellerOrg123456",
                    "author": "Canonical Sulu Seller",
                    "license": "CC-BY",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        valid_source = fixtures / "valid.blend"
        unsupported_source = fixtures / "unsupported.blend"
        unmarked_source = fixtures / "unmarked.blend"
        conflicting_source = fixtures / "conflicting.blend"
        for path, kind in (
            (valid_source, "valid"),
            (unsupported_source, "unsupported"),
            (unmarked_source, "unmarked"),
            (conflicting_source, "conflicting"),
        ):
            create_fixture(blender, environment, path, kind)

        first_output = workdir / "processed-first"
        run(
            processor_command(
                blender=blender,
                build_hash=build_hash,
                source=valid_source,
                output=first_output,
                trusted_metadata=trusted_metadata,
            ),
            environment=environment,
            expected_text="Processed and verified 2 OBJECT asset(s).",
        )
        first_manifest = read_manifest(first_output)
        for asset in first_manifest["assets"]:
            if asset["metadata"]["author"] != "Canonical Sulu Seller":
                raise RuntimeError("seller-authored asset author survived canonical processing")
            if asset["metadata"]["license"] != "CC-BY":
                raise RuntimeError("seller-authored asset license survived canonical processing")
        full_source_hash = sha256_bytes(valid_source.read_bytes())
        if first_manifest["source"]["sha256"] != full_source_hash:
            raise RuntimeError("manifest source hash does not cover the complete input file")
        if first_manifest["processor"]["blender_build_hash"] != build_hash:
            raise RuntimeError("manifest does not pin exact Blender build provenance")

        mappings_path = workdir / "server-owned-mappings.json"
        mappings_path.write_text(
            json.dumps(mappings_document_from_manifest(first_manifest), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        second_output = workdir / "processed-second"
        run(
            processor_command(
                blender=blender,
                build_hash=build_hash,
                source=valid_source,
                output=second_output,
                mappings=mappings_path,
                trusted_metadata=trusted_metadata,
            ),
            environment=environment,
            expected_text="Processed and verified 2 OBJECT asset(s).",
        )
        second_manifest = read_manifest(second_output)
        first_by_key = {asset["source_key"]: asset for asset in first_manifest["assets"]}
        second_by_key = {asset["source_key"]: asset for asset in second_manifest["assets"]}
        if set(first_by_key) != set(second_by_key):
            raise RuntimeError("reprocessing changed the source identity set")
        for key, first in first_by_key.items():
            second = second_by_key[key]
            if second["identity_source"] != "existing":
                raise RuntimeError("reprocessing did not identify server-owned existing IDs")
            for field in ("immutable_id",):
                if first[field] != second[field]:
                    raise RuntimeError("immutable identity changed across reprocessing")
            if first["artifact"] != second["artifact"]:
                raise RuntimeError("canonical artifact changed across identical reprocessing")
            if first["preview"] != second["preview"]:
                raise RuntimeError("canonical preview changed across identical reprocessing")

        rejection_cases = (
            (unsupported_source, "unsupported-out", [], "outside the v1 OBJECT-only contract"),
            (unmarked_source, "unmarked-out", [], "contains no marked OBJECT assets"),
            (conflicting_source, "conflicting-out", [], "reserved immutable-ID property"),
            (
                valid_source,
                "input-limit-out",
                ["--max-input-bytes", str(valid_source.stat().st_size - 1)],
                "input exceeds the configured byte limit",
            ),
            (valid_source, "count-limit-out", ["--max-assets", "1"], "count exceeds"),
            (
                valid_source,
                "artifact-limit-out",
                ["--max-artifact-bytes", "1"],
                "artifact exceeds the configured byte limit",
            ),
            (
                valid_source,
                "total-limit-out",
                ["--max-total-output-bytes", "1"],
                "total output byte limit",
            ),
        )
        for source, output_name, extra, expected_text in rejection_cases:
            rejected_output = workdir / output_name
            run(
                processor_command(
                    blender=blender,
                    build_hash=build_hash,
                    source=source,
                    output=rejected_output,
                    trusted_metadata=trusted_metadata,
                    extra=extra,
                ),
                environment=environment,
                expect_success=False,
                expected_text=expected_text,
            )
            if rejected_output.exists():
                raise RuntimeError("failed processing published a partial output directory")

        prove_native_listing_download_and_import(
            blender=blender,
            environment=environment,
            output=first_output,
            manifest=first_manifest,
        )
        print(
            "SULU_ASSET_PROCESSOR_E2E_OK "
            f"blender_build_hash={build_hash} assets={len(first_manifest['assets'])}"
        )
    finally:
        if options.keep_workdir:
            print(f"Keeping E2E work directory: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
