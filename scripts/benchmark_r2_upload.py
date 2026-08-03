#!/usr/bin/env python3
"""Benchmark disposable uploads through the add-on's real Cloudflare R2 path.

This tool never creates a render job. It obtains the current project's temporary
R2 credentials from the authenticated add-on session, uploads sparse local test
objects below a unique benchmark prefix, and purges that exact prefix before it
exits. Credentials, bucket names, account IDs, and object keys are never printed.

Examples:
    python3 scripts/benchmark_r2_upload.py --list-profiles
    python3 scripts/benchmark_r2_upload.py --live --sizes 64MiB \
        --profiles shipping,shipping-no-dest-check,multipart-16x12
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ADDON_DIR = Path(__file__).resolve().parent.parent
SESSION_PATH = ADDON_DIR / "session.json"
POCKETBASE_URL = "https://api.superlumin.al"
R2_ENDPOINT = "https://f09fa628d989ddd93cbe3bf7f7935591.r2.cloudflarestorage.com"
DEFAULT_RCLONE = ADDON_DIR / "transfers" / "rclone" / "osx-arm64" / "rclone"
BENCHMARK_PREFIX_ROOT = "_sulu_upload_benchmark"


@dataclass(frozen=True)
class Profile:
    name: str
    chunk_size: str
    cutoff: str
    concurrency: int
    buffer_size: str = "16M"
    no_check_dest: bool = False
    no_head: bool = False
    disable_checksum: bool = False

    def flags(self) -> list[str]:
        flags = [
            "--transfers",
            "1",
            "--checkers",
            "1",
            "--s3-chunk-size",
            self.chunk_size,
            "--s3-upload-cutoff",
            self.cutoff,
            "--s3-upload-concurrency",
            str(self.concurrency),
            "--buffer-size",
            self.buffer_size,
        ]
        if self.no_check_dest:
            flags.append("--no-check-dest")
        if self.no_head:
            flags.append("--s3-no-head")
        if self.disable_checksum:
            flags.append("--s3-disable-checksum")
        return flags


PROFILES = {
    # Profile captured in the historical provider benchmark reports.
    "legacy": Profile("legacy", "64M", "64M", 4, buffer_size="64M"),
    # Exact settings currently shipped by ZIP submission.
    "shipping": Profile("shipping", "16M", "100M", 8),
    # Safe for job-scoped, UUID-named destinations and avoids the pre-upload HEAD.
    "shipping-no-dest-check": Profile(
        "shipping-no-dest-check", "16M", "100M", 8, no_check_dest=True
    ),
    # Diagnostic only: quantifies the final verification HEAD. Do not ship solely
    # for speed without separately accepting the integrity tradeoff.
    "shipping-no-head": Profile(
        "shipping-no-head", "16M", "100M", 8, no_head=True
    ),
    # Production candidate for multipart, job-unique archives: avoids the full
    # local MD5 pre-read but keeps rclone's final remote HEAD.
    "shipping-no-checksum": Profile(
        "shipping-no-checksum", "16M", "100M", 8, disable_checksum=True
    ),
    "forced-single": Profile(
        "forced-single", "16M", "5G", 1
    ),
    "multipart-8x8": Profile(
        "multipart-8x8", "8M", "5M", 8, buffer_size="8M", no_check_dest=True
    ),
    "multipart-16x8": Profile(
        "multipart-16x8", "16M", "5M", 8, no_check_dest=True
    ),
    "multipart-16x12": Profile(
        "multipart-16x12", "16M", "5M", 12, no_check_dest=True
    ),
    "multipart-16x16": Profile(
        "multipart-16x16", "16M", "5M", 16, no_check_dest=True
    ),
    "multipart-32x8": Profile(
        "multipart-32x8", "32M", "5M", 8, no_check_dest=True
    ),
}


_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?i?b)?\s*$", re.I)
_SIZE_FACTORS = {
    "b": 1,
    "kb": 1_000,
    "mb": 1_000_000,
    "gb": 1_000_000_000,
    "tb": 1_000_000_000_000,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def parse_size(value: str) -> int:
    match = _SIZE_RE.match(str(value))
    if not match:
        raise argparse.ArgumentTypeError(f"invalid size: {value!r}")
    number = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    size = int(round(number * _SIZE_FACTORS[unit]))
    if size < 5 * 1024 * 1024:
        raise argparse.ArgumentTypeError("benchmark sizes must be at least 5 MiB")
    return size


def _load_session(session_path: Path) -> tuple[str, str]:
    try:
        data = json.loads(session_path.read_text("utf-8"))
    except Exception as exc:
        raise RuntimeError("could not read the authenticated add-on session") from exc

    token = str(data.get("user_token") or "").strip()
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        projects = data.get("projects") or []
        if projects and isinstance(projects[0], dict):
            project_id = str(projects[0].get("id") or "").strip()
    if not token or not project_id:
        raise RuntimeError("log in and select a project in the Blender add-on first")
    return token, project_id


def _fetch_storage(token: str, project_id: str) -> tuple[dict, str]:
    query = urllib.parse.urlencode(
        {
            "filter": f"(project_id='{project_id}' && bucket_name~'render-')",
            "sort": "-updated",
            "perPage": "1",
            "skipTotal": "1",
        }
    )
    request = urllib.request.Request(
        f"{POCKETBASE_URL}/api/collections/project_storage/records?{query}",
        headers={
            "Authorization": token,
            "Accept": "application/json",
            # Production rejects urllib's default user agent at the edge. Use a
            # bounded product identifier just like the real add-on transport.
            "User-Agent": "Sulu-Blender-Addon/r2-benchmark",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"storage credential request failed with HTTP {exc.code}") from None
    except Exception as exc:
        raise RuntimeError("storage credential request failed") from exc

    items = payload.get("items") if isinstance(payload, dict) else None
    record = items[0] if isinstance(items, list) and items else None
    if not isinstance(record, dict):
        raise RuntimeError("no render storage is available for the selected project")
    bucket = str(record.get("bucket_name") or "").strip()
    if not bucket:
        raise RuntimeError("the render storage record has no bucket")
    return record, bucket


def _credential_env(record: dict) -> dict[str, str]:
    access_key = str(record.get("access_key_id") or "")
    secret_key = str(record.get("secret_access_key") or "")
    if not access_key or not secret_key:
        raise RuntimeError("the render storage record has incomplete credentials")
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = access_key
    env["AWS_SECRET_ACCESS_KEY"] = secret_key
    session_token = str(record.get("session_token") or "")
    if session_token:
        env["AWS_SESSION_TOKEN"] = session_token
    else:
        env.pop("AWS_SESSION_TOKEN", None)
    return env


def _base_command(rclone: Path) -> list[str]:
    return [
        str(rclone),
        "--s3-endpoint",
        R2_ENDPOINT,
        "--s3-provider",
        "Cloudflare",
        "--s3-env-auth",
        "--s3-region",
        "auto",
        "--s3-no-check-bucket",
    ]


def _safe_error(stderr: str, *, bucket: str, prefix: str, record: dict) -> str:
    text = " ".join((stderr or "").strip().split())[-500:]
    for secret in (
        bucket,
        prefix,
        R2_ENDPOINT,
        str(record.get("access_key_id") or ""),
        str(record.get("secret_access_key") or ""),
        str(record.get("session_token") or ""),
    ):
        if secret:
            text = text.replace(secret, "<redacted>")
    return text or "rclone returned no error detail"


def _run(
    command: Sequence[str],
    *,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _purge_prefix(
    base: Sequence[str],
    remote_prefix: str,
    *,
    env: dict[str, str],
) -> bool:
    for _ in range(3):
        try:
            result = _run(
                [
                    *base,
                    "purge",
                    remote_prefix,
                    "--retries",
                    "3",
                    "--low-level-retries",
                    "3",
                ],
                env=env,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            # The caller emits only a generic cleanup failure. In particular,
            # TimeoutExpired includes the full command, which contains the
            # otherwise-redacted bucket and disposable object prefix.
            result = None
        if result is not None and result.returncode == 0:
            return True
        time.sleep(1)
    return False


def _profile_names(value: str) -> list[str]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [name for name in names if name not in PROFILES]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown profile(s): {', '.join(unknown)}")
    if not names:
        raise argparse.ArgumentTypeError("select at least one profile")
    return names


def _sizes(value: str) -> list[int]:
    return [parse_size(item) for item in value.split(",") if item.strip()]


def _version(rclone: Path) -> str:
    result = subprocess.run(
        [str(rclone), "version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    first = (result.stdout or "").splitlines()
    return first[0].strip() if first else "unknown"


def _result_line(**values: object) -> None:
    print(json.dumps(values, sort_keys=True), flush=True)


def run_benchmark(args: argparse.Namespace) -> int:
    rclone = Path(args.rclone).expanduser().resolve()
    if not rclone.is_file():
        raise RuntimeError("rclone executable was not found")

    token, project_id = _load_session(Path(args.session).expanduser().resolve())
    record, bucket = _fetch_storage(token, project_id)
    env = _credential_env(record)
    base = _base_command(rclone)
    run_id = uuid.uuid4().hex
    remote_prefix = f":s3:{bucket}/{BENCHMARK_PREFIX_ROOT}/{run_id}"
    randomizer = random.Random(args.seed)
    results: list[dict[str, object]] = []
    cleanup_ok = False

    _result_line(
        event="benchmark_start",
        rclone_version=_version(rclone),
        profiles=args.profiles,
        rounds=args.rounds,
        sizes_bytes=args.sizes,
        note="No render job will be created; remote identifiers are redacted.",
    )

    try:
        with tempfile.TemporaryDirectory(prefix="sulu-r2-benchmark-") as temp_dir:
            files: dict[int, Path] = {}
            for size in sorted(set(args.sizes)):
                path = Path(temp_dir) / f"payload-{size}.bin"
                with path.open("wb") as handle:
                    if args.materialize:
                        block = os.urandom(min(size, 1024 * 1024))
                        remaining = size
                        while remaining:
                            chunk = block[: min(len(block), remaining)]
                            handle.write(chunk)
                            remaining -= len(chunk)
                    else:
                        handle.truncate(size)
                files[size] = path

            cases = [
                (round_number, size, profile_name)
                for round_number in range(1, args.rounds + 1)
                for size in args.sizes
                for profile_name in args.profiles
            ]
            randomizer.shuffle(cases)

            for index, (round_number, size, profile_name) in enumerate(cases, start=1):
                profile = PROFILES[profile_name]
                destination = (
                    f"{remote_prefix}/{index:03d}-{round_number}-{size}-{profile_name}.bin"
                )
                command = [
                    *base,
                    "copyto",
                    str(files[size]),
                    destination,
                    *profile.flags(),
                    "--no-traverse",
                    "--retries",
                    "1",
                    "--low-level-retries",
                    "1",
                    "--timeout",
                    "5m",
                    "--contimeout",
                    "30s",
                    "--stats",
                    "0",
                    "--log-level",
                    "ERROR",
                ]
                started = time.perf_counter()
                try:
                    completed = _run(command, env=env, timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    result = {
                        "event": "upload_result",
                        "profile": profile_name,
                        "round": round_number,
                        "size_bytes": size,
                        "ok": False,
                        "error": "timeout",
                    }
                    results.append(result)
                    _result_line(**result)
                    continue
                elapsed = time.perf_counter() - started
                ok = completed.returncode == 0
                result = {
                    "event": "upload_result",
                    "profile": profile_name,
                    "round": round_number,
                    "size_bytes": size,
                    "elapsed_seconds": round(elapsed, 3),
                    "wire_MBps": round((size / 1_000_000) / elapsed, 3),
                    "wire_MiBps": round((size / 1024**2) / elapsed, 3),
                    "ok": ok,
                }
                if not ok:
                    result["error"] = _safe_error(
                        completed.stderr,
                        bucket=bucket,
                        prefix=remote_prefix,
                        record=record,
                    )
                results.append(result)
                _result_line(**result)
    finally:
        cleanup_ok = _purge_prefix(base, remote_prefix, env=env)
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            env.pop(key, None)

    successful = [result for result in results if result.get("ok")]
    _result_line(
        event="benchmark_end",
        attempted=len(results),
        successful=len(successful),
        cleanup_ok=cleanup_ok,
    )
    if not cleanup_ok:
        print(
            "ERROR: the exact disposable benchmark prefix could not be purged; "
            "run the tool again after restoring R2 access.",
            file=sys.stderr,
        )
        return 2
    return 0 if len(successful) == len(results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="perform real disposable R2 uploads (required)",
    )
    parser.add_argument(
        "--sizes",
        type=_sizes,
        default=_sizes("64MiB"),
        help="comma-separated test sizes, for example 64MiB,348MB",
    )
    parser.add_argument(
        "--profiles",
        type=_profile_names,
        default=_profile_names("shipping,shipping-no-dest-check"),
        help="comma-separated profile names",
    )
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="physically write payload bytes so local pre-read cost is realistic",
    )
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--rclone", default=str(DEFAULT_RCLONE))
    parser.add_argument(
        "--session",
        default=str(SESSION_PATH),
        help="path to an authenticated add-on session.json (never printed)",
    )
    parser.add_argument("--list-profiles", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.list_profiles:
        for name, profile in PROFILES.items():
            memory_mib = (
                int(profile.chunk_size.rstrip("M")) * profile.concurrency
                if profile.chunk_size.endswith("M")
                else None
            )
            print(
                f"{name}: cutoff={profile.cutoff}, chunk={profile.chunk_size}, "
                f"concurrency={profile.concurrency}, multipart_buffer~={memory_mib}MiB"
            )
        return 0
    if not args.live:
        parser.error("--live is required; this prevents accidental R2 writes")
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")
    try:
        return run_benchmark(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
