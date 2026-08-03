from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest import mock


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_r2_upload.py"
_SPEC = importlib.util.spec_from_file_location("benchmark_r2_upload", _SCRIPT)
benchmark = importlib.util.module_from_spec(_SPEC)
sys.modules["benchmark_r2_upload"] = benchmark
_SPEC.loader.exec_module(benchmark)


def test_profiles_keep_risky_request_elisions_orthogonal():
    no_dest = benchmark.PROFILES["shipping-no-dest-check"].flags()
    no_head = benchmark.PROFILES["shipping-no-head"].flags()
    no_checksum = benchmark.PROFILES["shipping-no-checksum"].flags()

    assert "--no-check-dest" in no_dest
    assert "--s3-no-head" not in no_dest
    assert "--s3-no-head" in no_head
    assert "--no-check-dest" not in no_head
    assert "--s3-disable-checksum" in no_checksum
    assert "--s3-no-head" not in no_checksum


def test_historical_and_forced_single_controls_are_available():
    legacy = benchmark.PROFILES["legacy"]
    forced = benchmark.PROFILES["forced-single"]

    assert (legacy.cutoff, legacy.chunk_size, legacy.concurrency) == (
        "64M",
        "64M",
        4,
    )
    assert forced.cutoff == "5G"


def test_size_parser_uses_explicit_decimal_and_binary_units():
    assert benchmark.parse_size("64MiB") == 64 * 1024 * 1024
    assert benchmark.parse_size("64MB") == 64_000_000


def test_cleanup_timeout_is_contained_without_exposing_the_command():
    timeout = subprocess.TimeoutExpired(
        ["rclone", "purge", ":s3:secret-bucket/secret-prefix"],
        120,
    )
    with (
        mock.patch.object(benchmark, "_run", side_effect=timeout),
        mock.patch.object(benchmark.time, "sleep"),
    ):
        assert benchmark._purge_prefix(
            ["rclone"],
            ":s3:secret-bucket/secret-prefix",
            env={},
        ) is False


def test_cleanup_timeout_reaches_main_as_a_sanitized_failure(tmp_path, capsys):
    rclone = tmp_path / "rclone"
    rclone.touch()
    secret_bucket = "secret-bucket"
    secret_run_id = "secret-run-id"
    purge_attempts = 0

    def run_with_cleanup_timeout(command, **_kwargs):
        nonlocal purge_attempts
        if "purge" in command:
            purge_attempts += 1
            raise subprocess.TimeoutExpired(command, 120)
        return subprocess.CompletedProcess(command, 0, "", "")

    run_id = mock.Mock()
    run_id.hex = secret_run_id
    with (
        mock.patch.object(benchmark, "_load_session", return_value=("token", "project")),
        mock.patch.object(benchmark, "_fetch_storage", return_value=({}, secret_bucket)),
        mock.patch.object(
            benchmark,
            "_credential_env",
            return_value={
                "AWS_ACCESS_KEY_ID": "secret-access-key",
                "AWS_SECRET_ACCESS_KEY": "secret-key",
            },
        ),
        mock.patch.object(benchmark, "_version", return_value="rclone test"),
        mock.patch.object(benchmark, "_run", side_effect=run_with_cleanup_timeout),
        mock.patch.object(benchmark.uuid, "uuid4", return_value=run_id),
        mock.patch.object(benchmark.time, "sleep"),
    ):
        exit_code = benchmark.main(
            [
                "--live",
                "--rclone",
                str(rclone),
                "--sizes",
                "5MiB",
                "--profiles",
                "shipping",
            ]
        )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert exit_code == 2
    assert purge_attempts == 3
    assert secret_bucket not in output
    assert secret_run_id not in output
    assert "could not be purged" in captured.err
