"""Pure helper functions used by submit worker runtime and tests."""

from __future__ import annotations

import re
from typing import Callable, Optional

_WIN_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]?$")
RISKY_CHARS = set("()'\"` &|;$!#")


def rclone_bytes(result) -> int:
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("bytes_transferred", 0)
    return int(result)


def rclone_stats(result):
    if isinstance(result, dict):
        return result
    return None


def is_empty_upload(result, expected_file_count: int) -> bool:
    if expected_file_count <= 0:
        return False
    if result is None:
        return True
    if isinstance(result, dict):
        if not result.get("stats_received", True):
            return True
        return result.get("transfers", 0) == 0
    return False


def get_rclone_tail(result) -> list:
    if isinstance(result, dict):
        return result.get("tail_lines", [])
    return []


def log_upload_result(
    result,
    *,
    expected_bytes: int = 0,
    label: str = "",
    debug_enabled_fn: Callable[[], bool],
    format_size_fn: Callable[[int], str],
    log_fn: Callable[[str], None],
) -> None:
    if not debug_enabled_fn():
        return
    if result is None:
        log_fn(f"  {label}result: no stats (rclone returned None)")
        return
    if not isinstance(result, dict):
        log_fn(f"  {label}result: {result}")
        return

    actual = result.get("bytes_transferred", 0)
    checks = result.get("checks", 0)
    transfers = result.get("transfers", 0)
    errors = result.get("errors", 0)
    received = result.get("stats_received", True)

    parts = []
    if not received:
        parts.append("stats_received=False")
    parts.append(f"transferred={format_size_fn(actual)}")
    if expected_bytes > 0:
        parts.append(f"expected={format_size_fn(expected_bytes)}")
    parts.append(f"checks={checks}")
    parts.append(f"transfers={transfers}")
    if errors:
        parts.append(f"errors={errors}")

    log_fn(f"  {label}{', '.join(parts)}")

    cmd = result.get("command")
    if cmd:
        log_fn(f"  {label}cmd: {cmd}")


def check_rclone_errors(
    result,
    *,
    label: str = "",
    debug_enabled_fn: Callable[[], bool],
    log_fn: Callable[[str], None],
) -> None:
    if not debug_enabled_fn():
        return
    if not isinstance(result, dict):
        return
    errors = result.get("errors", 0) or 0
    if errors > 0:
        log_fn(
            f"  WARNING ({label}): rclone reported {errors} error(s) "
            "despite exit code 0 — some files may not have uploaded"
        )


def is_filesystem_root(path: str) -> bool:
    p = str(path).replace("\\", "/").rstrip("/")
    if not p:
        return True
    if _WIN_DRIVE_ROOT_RE.match(p):
        return True
    if p == "":
        return True
    if re.match(r"^/Volumes/[^/]+$", p):
        return True
    if re.match(r"^/mnt/[^/]+$", p):
        return True
    if re.match(r"^/media/[^/]+/[^/]+$", p):
        return True
    return False


def check_risky_path_chars(path_str: str) -> Optional[str]:
    found = set(c for c in path_str if c in RISKY_CHARS)
    if found:
        chars = " ".join(repr(c) for c in sorted(found))
        return (
            f"Path contains special characters ({chars}) that may cause "
            f"issues on the render farm: {path_str}"
        )
    return None


def split_manifest_by_first_dir(rel_manifest):
    groups = {}
    for rel in rel_manifest:
        slash_pos = rel.find("/")
        if slash_pos > 0:
            first_dir = rel[:slash_pos]
            remainder = rel[slash_pos + 1 :]
        else:
            first_dir = ""
            remainder = rel
        groups.setdefault(first_dir, []).append(remainder)
    return groups
