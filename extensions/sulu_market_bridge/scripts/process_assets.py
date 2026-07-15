#!/usr/bin/env python3
"""Invoke the seller asset processor with an official Blender binary."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

try:
    from .asset_processing_contract import (
        DEFAULT_MAX_ARTIFACT_BYTES,
        DEFAULT_MAX_ASSETS,
        DEFAULT_MAX_INPUT_BYTES,
        DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
        HARD_MAX_ARTIFACT_BYTES,
        HARD_MAX_ASSETS,
        HARD_MAX_INPUT_BYTES,
        HARD_MAX_TOTAL_OUTPUT_BYTES,
        ContractError,
        load_trusted_metadata,
        read_strict_json,
        validate_processing_manifest,
        validated_limit,
    )
except ImportError:  # Direct executable invocation.
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
        load_trusted_metadata,
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
            "canonical per-asset artifacts through the configured production sandbox runner."
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
    parser.add_argument(
        "--trusted-metadata",
        required=True,
        type=Path,
        help="server-owned seller_org_id, author, and license JSON",
    )
    parser.add_argument(
        "--sandbox-runner",
        type=Path,
        help=(
            "production sandbox runner implementing docs/sandbox-runner-contract-v1.md"
        ),
    )
    parser.add_argument(
        "--allow-unsafe-direct",
        action="store_true",
        help="development/test only: run Blender directly without an OS sandbox",
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


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _run_process_group(command: list[str], *, timeout: int) -> None:
    process = subprocess.Popen(command, start_new_session=True)
    previous_handlers: dict[int, signal.Handlers] = {}

    def forward_signal(signum: int, _frame: object) -> None:
        _terminate_process_group(process)
        raise SystemExit(f"asset processing was cancelled by signal {signum}")

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, forward_signal)
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _terminate_process_group(process)
        raise SystemExit("asset processing exceeded its wall-clock timeout") from error
    except KeyboardInterrupt:
        _terminate_process_group(process)
        raise SystemExit("asset processing was cancelled") from None
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    if return_code:
        raise SystemExit(f"asset processing failed with exit code {return_code}")


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

    processor = Path(__file__).with_name("process_assets_blender.py").resolve()
    input_path = Path(os.path.abspath(os.fspath(arguments.input.expanduser())))
    output_path = Path(os.path.abspath(os.fspath(arguments.output.expanduser())))
    trusted_metadata = Path(
        os.path.abspath(os.fspath(arguments.trusted_metadata.expanduser()))
    )
    mappings_path = (
        Path(os.path.abspath(os.fspath(arguments.mappings.expanduser())))
        if arguments.mappings is not None
        else None
    )
    try:
        load_trusted_metadata(trusted_metadata)
    except ContractError as error:
        _parser().error(f"--trusted-metadata is invalid: {error}")
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
        str(input_path),
        "--output",
        str(output_path),
        "--trusted-metadata",
        str(trusted_metadata),
    ]
    if mappings_path is not None:
        command.extend(["--mappings", str(mappings_path)])
    if arguments.expected_blender_build_hash is not None:
        command.extend(["--expected-blender-build-hash", arguments.expected_blender_build_hash])
    for name, value in limits.items():
        command.extend([f"--{name.replace('_', '-')}", str(value)])

    if arguments.sandbox_runner is not None and arguments.allow_unsafe_direct:
        _parser().error("choose --sandbox-runner or --allow-unsafe-direct, not both")
    if arguments.sandbox_runner is None and not arguments.allow_unsafe_direct:
        _parser().error(
            "production processing requires --sandbox-runner; "
            "--allow-unsafe-direct is development/test only"
        )
    if arguments.sandbox_runner is not None:
        sandbox_runner = arguments.sandbox_runner.expanduser().resolve()
        if not sandbox_runner.is_file() or not os.access(sandbox_runner, os.X_OK):
            _parser().error("--sandbox-runner must identify an executable file")
        sandbox_command = [
            str(sandbox_runner),
            "--contract-version",
            "1",
            "--input-ro",
            str(input_path),
            "--output-rw",
            str(output_path),
            "--trusted-metadata-ro",
            str(trusted_metadata),
            "--blender-ro",
            str(blender),
            "--processor-ro",
            str(processor),
            "--timeout-seconds",
            str(timeout),
        ]
        if mappings_path is not None:
            sandbox_command.extend(["--mappings-ro", str(mappings_path)])
        sandbox_command.extend(["--", *command])
        command = sandbox_command

    _run_process_group(command, timeout=timeout + 10)

    manifest_path = output_path / "manifest.json"
    try:
        manifest = read_strict_json(manifest_path, maximum_bytes=1024 * 1024)
        validate_processing_manifest(manifest)
    except ContractError as error:
        raise SystemExit(f"processor returned an invalid manifest: {error}") from error
    print(f"Processed and verified {len(manifest['assets'])} OBJECT asset(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
