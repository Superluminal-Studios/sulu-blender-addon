#!/usr/bin/env python3
"""Invoke the seller asset processor with an official Blender binary."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from asset_processing_contract import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    DEFAULT_MAX_ASSETS,
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
    HARD_MAX_ARTIFACT_BYTES,
    HARD_MAX_ASSETS,
    HARD_MAX_INPUT_BYTES,
    HARD_MAX_TOTAL_OUTPUT_BYTES,
    ContractError,
    read_strict_json,
    validate_processing_manifest,
    validated_limit,
)

DEFAULT_TIMEOUT_SECONDS = 900
HARD_MAX_TIMEOUT_SECONDS = 6 * 60 * 60


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert marked OBJECT assets in one untrusted .blend upload into "
            "canonical per-asset artifacts. Run this wrapper inside a disposable OS sandbox."
        )
    )
    parser.add_argument("--blender", required=True, type=Path, help="official Blender 5.2 binary")
    parser.add_argument("--input", required=True, type=Path, help="untrusted seller .blend upload")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new server-controlled output directory",
    )
    parser.add_argument(
        "--mappings",
        type=Path,
        help="optional server-owned immutable-ID mappings from an earlier process",
    )
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
    parser.add_argument("--max-assets", type=int, default=DEFAULT_MAX_ASSETS)
    parser.add_argument("--max-artifact-bytes", type=int, default=DEFAULT_MAX_ARTIFACT_BYTES)
    parser.add_argument(
        "--max-total-output-bytes",
        type=int,
        default=DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
    )
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--expected-blender-build-hash",
        help="pin production processing to one audited official Blender 5.2 build",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        limits = {
            "max_input_bytes": validated_limit(
                arguments.max_input_bytes,
                label="max input bytes",
                hard_maximum=HARD_MAX_INPUT_BYTES,
            ),
            "max_assets": validated_limit(
                arguments.max_assets,
                label="max assets",
                hard_maximum=HARD_MAX_ASSETS,
            ),
            "max_artifact_bytes": validated_limit(
                arguments.max_artifact_bytes,
                label="max artifact bytes",
                hard_maximum=HARD_MAX_ARTIFACT_BYTES,
            ),
            "max_total_output_bytes": validated_limit(
                arguments.max_total_output_bytes,
                label="max total output bytes",
                hard_maximum=HARD_MAX_TOTAL_OUTPUT_BYTES,
            ),
        }
        timeout = validated_limit(
            arguments.timeout_seconds,
            label="timeout seconds",
            hard_maximum=HARD_MAX_TIMEOUT_SECONDS,
        )
    except ContractError as error:
        _parser().error(str(error))

    blender = arguments.blender.expanduser().resolve()
    if not blender.is_file():
        _parser().error("--blender must identify an existing binary")

    processor = Path(__file__).with_name("process_assets_blender.py")
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--offline-mode",
        "--python-exit-code",
        "1",
        "--python",
        str(processor),
        "--",
        "--input",
        str(arguments.input),
        "--output",
        str(arguments.output),
    ]
    if arguments.mappings is not None:
        command.extend(["--mappings", str(arguments.mappings)])
    if arguments.expected_blender_build_hash is not None:
        command.extend(["--expected-blender-build-hash", arguments.expected_blender_build_hash])
    for name, value in limits.items():
        command.extend([f"--{name.replace('_', '-')}", str(value)])

    try:
        subprocess.run(command, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise SystemExit("asset processing exceeded its wall-clock timeout") from error
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"asset processing failed with Blender exit code {error.returncode}"
        ) from error

    manifest_path = arguments.output / "manifest.json"
    try:
        manifest = read_strict_json(manifest_path, maximum_bytes=1024 * 1024)
        validate_processing_manifest(manifest)
    except ContractError as error:
        raise SystemExit(f"processor returned an invalid manifest: {error}") from error
    print(f"Processed and verified {len(manifest['assets'])} OBJECT asset(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
