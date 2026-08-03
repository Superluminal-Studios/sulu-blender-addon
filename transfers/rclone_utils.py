"""
rclone.py — rclone bootstrap + runner with streaming progress.

Design goal: integrate cleanly with Sulu Submitter's scrolling transcript UI.
- Uses Rich Progress when available (prefers logger.console if provided)
- No emoji; Unicode symbols only. Falls back to plain text if needed.
- Keeps tail logs for actionable error classification without spamming.

Public API (used by submit_worker):
- ensure_rclone(logger=None) -> Path
- run_rclone(base, verb, src, dst, extra=None, logger=None, file_count=None)
"""

import platform
from pathlib import Path
import tempfile
import uuid
import zipfile
import os
import subprocess
import sys
import json
import re
import shutil
import time
import hashlib
from collections import deque
from typing import List, Optional, Tuple, Any

from ..utils.worker_utils import format_size, requests_retry_session

# Unicode glyphs (no emoji)
_GLYPH_DOWN = "↓"
_GLYPH_OK = "✓"
_GLYPH_FAIL = "✕"

NOT_FOUND_MARKERS = (
    "directory not found",
    "no such key",
    "404",
    "not exist",
    "cannot find",
)

AUTH_MARKERS = (
    "statuscode: 403",
    " forbidden",
    "accessdenied",
    "unauthorized",
    "invalidaccesskeyid",
    "signaturedoesnotmatch",
    "access denied",
)


class RcloneError(RuntimeError):
    """A transfer failure with the category determined from rclone output."""

    def __init__(self, message: str, category: str = "unknown") -> None:
        super().__init__(message)
        self.category = category


def _call_logger(logger: Any, method: str, msg: str) -> None:
    """Call logger.info/warning/error/log if present, else treat logger as callable, else print."""
    if logger is None:
        try:
            print(str(msg))
        except UnicodeEncodeError:
            print(str(msg).encode("ascii", errors="replace").decode("ascii"))
        return

    fn = getattr(logger, method, None)
    if callable(fn):
        try:
            fn(str(msg))
            return
        except Exception:
            pass

    if callable(logger):
        try:
            logger(str(msg))
            return
        except Exception:
            pass

    # Fallback
    try:
        print(str(msg))
    except UnicodeEncodeError:
        print(str(msg).encode("ascii", errors="replace").decode("ascii"))


_UNIT = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
    "TiB": 1024**4,
    "kB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
}

# Map (normalized_os, normalized_arch) -> rclone's "os-arch" string
SUPPORTED_PLATFORMS = {
    ("windows", "386"): "windows-386",
    ("windows", "amd64"): "windows-amd64",
    ("windows", "arm64"): "windows-arm64",
    ("osx", "amd64"): "osx-amd64",
    ("osx", "arm64"): "osx-arm64",
    ("linux", "386"): "linux-386",
    ("linux", "amd64"): "linux-amd64",
    ("linux", "arm"): "linux-arm",
    ("linux", "armv6"): "linux-arm-v6",
    ("linux", "armv7"): "linux-arm-v7",
    ("linux", "arm64"): "linux-arm64",
    ("linux", "mips"): "linux-mips",
    ("linux", "mipsle"): "linux-mipsle",
    ("freebsd", "386"): "freebsd-386",
    ("freebsd", "amd64"): "freebsd-amd64",
    ("freebsd", "arm"): "freebsd-arm",
    ("openbsd", "386"): "openbsd-386",
    ("openbsd", "amd64"): "openbsd-amd64",
    ("netbsd", "386"): "netbsd-386",
    ("netbsd", "amd64"): "netbsd-amd64",
    ("plan9", "386"): "plan9-386",
    ("plan9", "amd64"): "plan9-amd64",
    ("solaris", "amd64"): "solaris-amd64",
}

# Keep downloads reproducible and security fixes deterministic.  v1.75.0
# includes fixes for S3 redirects that could otherwise forward credentials to
# an untrusted host.  These are the official ZIP digests published in
# https://downloads.rclone.org/v1.75.0/SHA256SUMS.
RCLONE_VERSION = "1.75.0"
RCLONE_MIN_VERSION = (1, 75, 0)
RCLONE_SHA256_BY_SUFFIX = {
    "windows-386": "dee1882a2a4277e42bd8b572b8e0e6676a491e3ec0e238ea16dc0e0e619cdc84",
    "windows-amd64": "203581f0a7baeae873f2347483a798c79e2eaf5c384a4e9d866aa374f1c89ac0",
    "windows-arm64": "bcf628fa6bb3b6ae9fdf105d04acafb40ec77841f686dc6dd7d126dde04c5f6a",
    "osx-amd64": "19edbb8e5e73096eb66e92a42abbc5c34bfa8981ea3986a53872c7eef85a22f4",
    "osx-arm64": "35e8f2a666ce789b29111db0dd843ddabc0d59c6b609d07bcaae5d1a07cba6f8",
    "linux-386": "0cd6d0a18cf50004851e23f97dbcad5ebd16047590a704daebfbfe402425aefe",
    "linux-amd64": "aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa",
    "linux-arm": "17f3f07cfa17e065f0c3329149ba702bbaafdb87e7f00230830488d5391362f2",
    "linux-arm-v6": "4507fa57e8a9031c09be15e3c506f293522c95d488485db2174ae0444f9dd7c8",
    "linux-arm-v7": "8fcfdd4121348b79b485b40c52dc22f3d26ee167ec78105e15f5dbe2246eee97",
    "linux-arm64": "d0ad88ba4c8e285b7c9efa591e0ab643280a91741e13c27f3a9c0957ccfa5203",
    "linux-mips": "954cd1d8fd54cdc82b246b6cc8a439b820180545fe48d3587ae2a4e5b67d8f31",
    "linux-mipsle": "ebfa68a9c5d5a1d971811b6d946a4cd1d63ccfbc60b625bd6bc0cc4ac4e81967",
    "freebsd-386": "f55db6da010fa3aacd8373d7af06c8074f801ca642d8967b4d78323e558f2288",
    "freebsd-amd64": "c4b440b01ad46782e213758f2d3c10b15990bc71def5c9657d206992c74a7ecc",
    "freebsd-arm": "0b01cf0cc4144110230bef541a87f279220e8d0a8b75437ace44970462cec7fe",
    "openbsd-386": "517a68144e6ce2185be2b0ca72627db9f4da54d31b920cce35b3d23dd21560d8",
    "openbsd-amd64": "6ab36915cfa6f48ca17de294c67e18a6e84e22fceaa637633c261e6684ed6e4a",
    "netbsd-386": "4c78453d7c3af9242e7d1b95b1bfcac3d2b6fff81d4da2e383cbfd21a90195a8",
    "netbsd-amd64": "2b0dc941a279aa9ff6c58c580aba51a4fa1528d31859ff1f651aed41f0d45351",
    "plan9-386": "c80691e1273559c57778e86d8a98e63827c4b212db7a06a3d58274aa540bf4a1",
    "plan9-amd64": "adfbd843175e8d9e4beeddbdf89341d2986288d20dad08778c90a7256547e1ad",
    "solaris-amd64": "06375436e50bac7169c4eb30d9bf54917ec390bab8903c3782add0f3df55084c",
}


# -------------------------------------------------------------------
#  Rclone Download Helpers
# -------------------------------------------------------------------


def get_addon_directory() -> Path:
    return Path(__file__).resolve().parent


def rclone_install_directory() -> Path:
    return get_addon_directory() / "rclone"


def normalize_os(os_name: str) -> str:
    os_name = os_name.lower()
    if os_name.startswith("win"):
        return "windows"
    if os_name.startswith("linux"):
        return "linux"
    if os_name.startswith("darwin"):
        return "osx"
    return os_name


def normalize_arch(arch_name: str) -> str:
    arch_name = arch_name.lower()
    if arch_name in ("x86_64", "amd64"):
        return "amd64"
    if arch_name in ("i386", "i686", "x86", "386"):
        return "386"
    if arch_name in ("aarch64", "arm64"):
        return "arm64"
    return arch_name


def get_platform_suffix() -> str:
    sys_name = normalize_os(platform.system())
    arch_name = normalize_arch(platform.machine())
    key = (sys_name, arch_name)
    if key not in SUPPORTED_PLATFORMS:
        raise OSError(
            f"Unsupported OS/Arch combination: {sys_name}/{arch_name}. "
            "Extend SUPPORTED_PLATFORMS for additional coverage."
        )
    return SUPPORTED_PLATFORMS[key]


def get_rclone_url() -> str:
    suffix = get_platform_suffix()
    return (
        f"https://downloads.rclone.org/v{RCLONE_VERSION}/"
        f"rclone-v{RCLONE_VERSION}-{suffix}.zip"
    )


def get_rclone_platform_dir(suffix: str) -> Path:
    return rclone_install_directory() / suffix


def _plain_download_bar(total: int, done: int, width: int = 32) -> str:
    if total <= 0:
        return ""
    filled = int(width * done / max(total, 1))
    return "█" * filled + " " * (width - filled)


def download_with_bar(url: str, dest: Path, logger=None) -> None:
    """
    Download a file with a simple inline progress bar.
    """
    session = requests_retry_session()

    _call_logger(logger, "info", f"{_GLYPH_DOWN} Preparing rclone")
    resp = session.get(url, stream=True, timeout=600)
    resp.raise_for_status()

    total = int(resp.headers.get("Content-Length", 0)) or 0
    done = 0

    with dest.open("wb") as fp:
        for chunk in resp.iter_content(1024 * 64):
            if not chunk:
                continue
            fp.write(chunk)
            done += len(chunk)
            if total:
                bar = _plain_download_bar(total, done)
                pct = (done * 100) / max(total, 1)
                sys.stderr.write(f"\r  {bar} {pct:5.1f}% ")
                sys.stderr.flush()
    if total:
        sys.stderr.write("\n")
        sys.stderr.flush()


_RCLONE_VERSION_RE = re.compile(
    r"(?im)^rclone\s+v(\d+)\.(\d+)\.(\d+)(?=\D|$)"
)


def _installed_rclone_version(rclone_bin: Path) -> Optional[Tuple[int, int, int]]:
    """Return the installed numeric rclone version, or None if it is unusable."""
    try:
        result = subprocess.run(
            [str(rclone_bin), "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    match = _RCLONE_VERSION_RE.search(result.stdout or "")
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_rclone_archive(archive: Path, suffix: str) -> None:
    expected = RCLONE_SHA256_BY_SUFFIX.get(suffix)
    if expected is None:
        raise RuntimeError(f"No trusted rclone checksum for platform {suffix}.")
    if _sha256_file(archive) != expected:
        raise RuntimeError(
            "Downloaded rclone archive failed SHA-256 verification; "
            "the existing binary was not changed."
        )


def _extract_rclone_binary(archive: Path, destination: Path, bin_name: str) -> None:
    """Copy the one expected binary out of the verified archive."""
    with zipfile.ZipFile(archive) as zf:
        members = [
            member
            for member in zf.infolist()
            if not member.is_dir()
            and member.filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
            == bin_name.lower()
        ]
        if len(members) != 1:
            raise RuntimeError(
                "Verified rclone archive did not contain exactly one rclone binary."
            )

        with zf.open(members[0], "r") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())


def ensure_rclone(logger=None) -> Path:
    suf = get_platform_suffix()
    bin_name = "rclone.exe" if suf.startswith("windows") else "rclone"
    rclone_bin = get_rclone_platform_dir(suf) / bin_name

    if rclone_bin.exists():
        installed_version = _installed_rclone_version(rclone_bin)
        if installed_version is not None and installed_version >= RCLONE_MIN_VERSION:
            return rclone_bin
        if installed_version is None:
            reason = "unusable or has an unknown version"
        else:
            reason = ".".join(str(part) for part in installed_version)
        _call_logger(
            logger,
            "info",
            f"Updating rclone ({reason}) to v{RCLONE_VERSION}",
        )

    rclone_bin.parent.mkdir(parents=True, exist_ok=True)
    url = get_rclone_url()

    # Extract beside the destination so os.replace() is a same-filesystem,
    # atomic operation.  Any failure leaves an older installation untouched.
    with tempfile.TemporaryDirectory(
        prefix=".rclone-install-", dir=str(rclone_bin.parent)
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        tmp_zip = temp_dir / f"rclone-v{RCLONE_VERSION}-{suf}.zip"
        tmp_bin = temp_dir / bin_name

        download_with_bar(url, tmp_zip, logger=logger)
        _verify_rclone_archive(tmp_zip, suf)

        _call_logger(logger, "info", "Extracting rclone")
        _extract_rclone_binary(tmp_zip, tmp_bin, bin_name)

        if not suf.startswith("windows"):
            tmp_bin.chmod(tmp_bin.stat().st_mode | 0o111)

        extracted_version = _installed_rclone_version(tmp_bin)
        if extracted_version != RCLONE_MIN_VERSION:
            raise RuntimeError(
                "Verified rclone archive produced an unexpected binary version; "
                "the existing binary was not changed."
            )

        os.replace(tmp_bin, rclone_bin)

    _call_logger(logger, "info", f"{_GLYPH_OK} rclone v{RCLONE_VERSION} ready")
    return rclone_bin


def _extract_stats_detail(obj):
    """
    Extract detailed stats from rclone JSON for progress display.

    Returns dict with:
        bytes: current bytes transferred
        totalBytes: total bytes to transfer
        checks: number of files checked
        transfers: number of files transferred
        checking: list of filenames currently being checked
        transferring: list of filenames currently being transferred
    """
    s = obj.get("stats")
    if not s:
        return None

    def _extract_names(items):
        """Extract filenames from rclone list (handles both str and dict formats)."""
        if not items:
            return []
        result = []
        for item in items:
            if isinstance(item, str):
                if item:
                    result.append(item)
            elif isinstance(item, dict):
                name = item.get("name", "")
                if name:
                    result.append(name)
        return result

    return {
        "bytes": int(s.get("bytes", 0) or 0),
        "totalBytes": int(s.get("totalBytes", 0) or 0),
        "checks": int(s.get("checks", 0) or 0),
        "transfers": int(s.get("transfers", 0) or 0),
        "errors": int(s.get("errors", 0) or 0),
        "elapsedTime": float(s.get("elapsedTime", 0) or 0),
        "checking": _extract_names(s.get("checking")),
        "transferring": _extract_names(s.get("transferring")),
    }


def _progress_while_process_is_running(
    current: int,
    total: int,
    status: str = "",
) -> Tuple[int, str]:
    """Keep an in-flight transfer below 100% until rclone exits successfully.

    The S3 backend counts a multipart chunk once it has been buffered by the
    AWS SDK, not once the remote has committed it.  In particular, a large
    ``--s3-chunk-size`` can therefore make the byte counter reach the total
    while rclone is still uploading parts or completing the multipart upload.
    Hold back one tenth of a percent while the process is alive so 100% remains
    a truthful terminal state.
    """
    current = max(0, int(current or 0))
    total = max(0, int(total or 0))
    if total > 0:
        holdback = max(1, (total + 999) // 1000)
        maximum_in_flight = max(0, total - holdback)
        display_current = min(current, maximum_in_flight)
        if current >= total:
            return display_current, "finalizing"
        return display_current, status
    return current, status


# -------------------------------------------------------------------
#  Small rclone feature detection (cached)
# -------------------------------------------------------------------

_RCLONE_FLAG_CACHE = {}  # (exe_path, flag) -> bool
_RCLONE_HELPFLAGS_CACHE = {}  # exe_path -> text


def _rclone_supports_flag(rclone_exe: str, flag: str) -> bool:
    key = (str(rclone_exe), flag)
    if key in _RCLONE_FLAG_CACHE:
        return _RCLONE_FLAG_CACHE[key]

    exe = str(rclone_exe)
    text = _RCLONE_HELPFLAGS_CACHE.get(exe)
    if text is None:
        try:
            p = subprocess.run(
                [exe, "help", "flags"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            text = p.stdout or ""
        except Exception:
            text = ""
        _RCLONE_HELPFLAGS_CACHE[exe] = text

    ok = flag in text
    _RCLONE_FLAG_CACHE[key] = ok
    return ok


# -------------------------------------------------------------------
# Error classification and user-facing messages
# -------------------------------------------------------------------

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_TIME_SKEW_RE = re.compile(
    r'time from\s+"(?P<host>[^"]+)"\s+is\s+(?P<delta>[+-]?[0-9a-zA-Z\.\-]+)\s+different from this computer',
    re.IGNORECASE,
)


def _looks_like_windows_path(p: str) -> bool:
    s = str(p or "").strip()
    if not s:
        return False
    s2 = s.replace("\\", "/")
    return bool(_WIN_DRIVE_RE.match(s2)) or s2.startswith("//") or s2.startswith("\\\\")


def _looks_like_rclone_remote(p: str) -> bool:
    s = str(p or "").strip()
    if not s:
        return False
    s2 = s.replace("\\", "/")
    if _looks_like_windows_path(s2):
        return False
    if s2.startswith(":"):
        return True
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*:", s2))


def _free_space_bytes_for_path(p: str) -> Optional[int]:
    try:
        if _looks_like_rclone_remote(p):
            return None
        path = str(p or "")
        if not path:
            return None
        candidate = path
        if not os.path.exists(candidate):
            candidate = os.path.dirname(candidate) or os.getcwd()
        usage = shutil.disk_usage(candidate)
        return int(usage.free)
    except Exception:
        return None


def _format_go_duration_approx(d: str) -> str:
    """
    Take a Go duration string like '-1h0m44.216s' and return '1h 0m 44s' (absolute).
    If parsing fails, returns the original (absolute) string.
    """
    s = str(d or "").strip()
    if not s:
        return ""
    if s[0] in "+-":
        s = s[1:]
    h = re.search(r"(\d+)h", s)
    m = re.search(r"(\d+)m", s)
    sec = re.search(r"(\d+(?:\.\d+)?)s", s)

    parts = []
    if h:
        parts.append(f"{int(h.group(1))}h")
    if m:
        parts.append(f"{int(m.group(1))}m")
    if sec:
        try:
            parts.append(f"{int(round(float(sec.group(1))))}s")
        except Exception:
            parts.append(f"{sec.group(1)}s")

    if parts:
        return " ".join(parts)
    return s


def _extract_time_skew(tail_lines: List[str]) -> Optional[Tuple[str, str]]:
    """
    Look for rclone's notice:
      'Time may be set wrong - time from "host" is -1h0m44s different from this computer'
    Returns (host, approx_delta) or None.
    """
    for ln in tail_lines:
        low = str(ln).lower()
        if "time may be set wrong" not in low:
            continue
        m = _TIME_SKEW_RE.search(str(ln))
        if not m:
            return ("storage server", "")
        host = m.group("host").strip() or "storage server"
        delta = m.group("delta").strip()
        return (host, _format_go_duration_approx(delta))
    return None


def _pick_technical_line(tail_lines: List[str]) -> str:
    """
    Pick a single, useful technical line without dumping retries.
    Preference:
      1) 'Failed to ...'
      2) auth-ish lines
      3) last non-empty line
    """
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if not s:
            continue
        if "failed to" in s.lower():
            return s
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if not s:
            continue
        low = s.lower()
        if (
            "statuscode" in low
            or "forbidden" in low
            or "accessdenied" in low
            or "unauthorized" in low
        ):
            return s
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if s:
            return s
    return ""


_SENSITIVE_FLAGS = frozenset({
    "--s3-access-key-id",
    "--s3-secret-access-key",
    "--s3-session-token",
})


def _redact_cmd(cmd: list) -> str:
    """Return a shell-style string with credential values masked."""
    parts = []
    skip_next = False
    for i, tok in enumerate(cmd):
        if skip_next:
            parts.append("***")
            skip_next = False
            continue
        if tok in _SENSITIVE_FLAGS and i + 1 < len(cmd):
            parts.append(tok)
            skip_next = True
            continue
        parts.append(tok)
    return " ".join(parts)


def _classify_failure(
    verb: str, src: str, dst: str, exit_code: int, tail_lines: List[str]
) -> Tuple[str, str]:
    """
    Returns (category, user_message).
    Message intentionally has NO leading emoji.
    """
    blob = "\n".join([str(x) for x in (tail_lines or [])]).strip()
    low = blob.lower()

    tech = _pick_technical_line(tail_lines) or f"exit code {exit_code}"

    # ---- Clock skew / wrong system time ----
    skew = _extract_time_skew(tail_lines)
    if skew is not None:
        host, delta = skew
        return (
            "clock_skew",
            f"System clock is {delta or 'significantly'} out of sync. "
            f"Sync your clock in date and time settings, then retry.\n\n[{tech}]",
        )

    clock_markers = (
        "requesttimetooskewed",
        "difference between the request time",
        "requestexpired",
        "expiredrequest",
        "signature has expired",
        "signature expired",
        "x509: certificate has expired or is not yet valid",
        "certificate has expired or is not yet valid",
        "not yet valid",
        "tls: failed to verify certificate",
    )
    if any(m in low for m in clock_markers):
        return (
            "clock_skew",
            "System clock appears incorrect. "
            f"Sync your clock in date and time settings, then retry.\n\n[{tech}]",
        )

    # ---- Local disk full ----
    local_space_markers = (
        "no space left on device",
        "there is not enough space on the disk",
        "enospc",
        "disk full",
    )
    if any(m in low for m in local_space_markers):
        free = None
        if not _looks_like_rclone_remote(dst):
            free = _free_space_bytes_for_path(dst)
        if free is None and not _looks_like_rclone_remote(src):
            free = _free_space_bytes_for_path(src)
        if free is None:
            free = _free_space_bytes_for_path(tempfile.gettempdir())

        free_str = format_size(free) if free is not None else "unknown"
        return (
            "local_disk_full",
            f"Disk full ({free_str} available). "
            f"Free up space or choose a different destination.\n\n[{tech}]",
        )

    # ---- Network / connection errors ----
    network_markers = (
        "broken pipe",
        "use of closed network connection",
        "connection reset",
        "connection refused",
        "connection timed out",
        "no route to host",
        "network is unreachable",
        "i/o timeout",
        "context deadline exceeded",
        "tls handshake timeout",
        "eof",
    )
    if any(m in low for m in network_markers):
        return (
            "network_error",
            f"Connection failed. Check your internet connection and retry.\n\n[{tech}]",
        )

    # ---- Remote storage service error ----
    remote_space_markers = (
        "insufficient storage",
        "insufficientstorage",
        "quota exceeded",
        "storagequotaexceeded",
        "statuscode: 507",
        "statuscode:507",
        "notentitled",
    )
    if any(m in low for m in remote_space_markers):
        return (
            "remote_storage_error",
            f"Storage service rejected the request. Retry, or contact support if this persists.\n\n[{tech}]",
        )

    # ---- Not found ----
    if any(m in low for m in NOT_FOUND_MARKERS):
        return (
            "not_found",
            f"Source not found. This can be normal if outputs haven't been produced yet.\n\n[{tech}]",
        )

    # ---- Permissions / auth (403 etc) ----
    if any(m in low for m in AUTH_MARKERS):
        return (
            "forbidden",
            f"Access denied. Log out and back in to refresh credentials, then retry.\n\n[{tech}]",
        )

    return ("unknown", f"Transfer failed. Retry, or contact support if this persists.\n\n[{tech}]")


# Main runner


def run_rclone(base, verb, src, dst, extra=None, logger=None, file_count=None, total_bytes=None):
    """
    Execute rclone safely with a friendly progress display.
    Raises RuntimeError on failure (message is user-friendly, no emoji).

    Returns:
        dict: Transfer stats dict with keys: bytes_transferred, total_bytes,
            checks, transfers, errors, elapsed_time, process_elapsed_time,
            reported_bytes_complete_time, finalization_time, stats_received,
            and tail_lines.
            When rclone emits no stats (e.g. very fast operation or silent failure),
            stats_received is False and numeric fields are 0.

    Args:
        base: Base rclone command list (exe + global flags)
        verb: rclone verb (copy, move, copyto, moveto, etc.)
        src: Source path
        dst: Destination path
        extra: Extra rclone flags
        logger: Logger instance with transfer_progress() method for rich progress
        file_count: (unused) Number of files being transferred
        total_bytes: Pre-calculated total bytes for multi-file transfers.
                     When provided, enables percentage progress bar from the start.

    Reliability patches:
    - Automatically add --local-unicode-normalization when supported
    - Automatically upgrade --files-from -> --files-from-raw when supported
    """
    extra = list(extra or [])
    src = str(src).replace("\\", "/")
    dst = str(dst).replace("\\", "/")
    is_remote_upload = (
        _looks_like_rclone_remote(dst)
        and not _looks_like_rclone_remote(src)
    )

    if not isinstance(base, (list, tuple)) or not base:
        raise RuntimeError("Invalid rclone base command.")

    rclone_exe = str(base[0])

    # Auto-upgrade files list flag to avoid comment/whitespace parsing issues.
    if "--files-from" in extra and _rclone_supports_flag(rclone_exe, "--files-from-raw"):
        upgraded = []
        i = 0
        while i < len(extra):
            if extra[i] == "--files-from":
                upgraded.append("--files-from-raw")
                if i + 1 < len(extra):
                    upgraded.append(extra[i + 1])
                    i += 2
                    continue
            upgraded.append(extra[i])
            i += 1
        extra = upgraded

    # Add local unicode normalization if supported and not already present.
    if _rclone_supports_flag(rclone_exe, "--local-unicode-normalization"):
        if (
            "--local-unicode-normalization" not in extra
            and "--local-unicode-normalization" not in base
        ):
            extra = ["--local-unicode-normalization"] + extra

    cmd = [
        base[0],
        verb,
        src,
        dst,
        *extra,
        "--stats=0.1s",
        "--use-json-log",
        "--stats-log-level",
        "NOTICE",
        *base[1:],
    ]

    # Keep a small tail of non-stats output so failures are actionable.
    tail = deque(maxlen=160)

    def _remember_line(s: str) -> None:
        s = str(s or "").strip()
        if not s:
            return
        tail.append(s)

    # Progress bar - uses logger's transfer_progress if available, else simple text
    progress_started = False
    progress_total = int(total_bytes) if total_bytes and total_bytes > 0 else 0
    progress_cur = 0
    progress_last_len = 0
    progress_checks = 0
    progress_transfers = 0
    progress_status = ""  # "checking", "transferring", or ""
    _stats_received = False  # True once at least one rclone stats line is processed
    _last_stats_detail = None  # Last full stats dict for final return
    progress_current_file = ""
    reported_bytes_complete_at = None

    # Check if logger has transfer_progress method (rich UI)
    has_rich_progress = (
        logger is not None
        and hasattr(logger, "transfer_progress")
        and callable(getattr(logger, "transfer_progress", None))
    )

    # Check if logger has extended transfer_progress_ext method
    has_rich_progress_ext = (
        logger is not None
        and hasattr(logger, "transfer_progress_ext")
        and callable(getattr(logger, "transfer_progress_ext", None))
    )

    # If we have a pre-calculated total, start progress immediately
    if progress_total > 0:
        progress_started = True
        if has_rich_progress_ext:
            logger.transfer_progress_ext(0, progress_total, status="preparing")
        elif has_rich_progress:
            logger.transfer_progress(0, progress_total)
        else:
            sys.stderr.write(f"  Preparing transfer ({format_size(progress_total)})\r")
            sys.stderr.flush()

    def _shorten_filename(name: str, max_len: int = 30) -> str:
        if len(name) <= max_len:
            return name
        return name[:max_len - 3] + "..."

    def _progress_start(total: Optional[int] = None) -> None:
        nonlocal progress_started, progress_total
        progress_started = True
        progress_total = int(total) if total and total > 0 else 0
        if has_rich_progress_ext:
            logger.transfer_progress_ext(0, progress_total, status="starting")
        elif has_rich_progress:
            logger.transfer_progress(0, progress_total)
        else:
            _progress_render_simple()

    def _progress_render_simple(
        display_cur: Optional[int] = None,
        display_status: Optional[str] = None,
    ) -> None:
        nonlocal progress_last_len
        render_cur = progress_cur if display_cur is None else display_cur
        render_status = progress_status if display_status is None else display_status
        # Build status suffix
        status_suffix = ""
        if render_status == "finalizing":
            status_suffix = "  Finalizing upload"
        elif render_status == "checking" and progress_current_file:
            status_suffix = f"  Verifying: {_shorten_filename(progress_current_file, 25)}"
        elif render_status == "checking":
            status_suffix = f"  Verifying ({progress_checks} checked)"
        elif progress_transfers > 0 and progress_checks > progress_transfers:
            # More checks than transfers = some files skipped
            skipped = progress_checks - progress_transfers
            status_suffix = f"  ({skipped} unchanged)"

        if progress_total > 0:
            pct = (render_cur / max(progress_total, 1)) * 100.0
            bar_w = 24
            filled = int(bar_w * render_cur / max(progress_total, 1))
            bar = "█" * filled + "░" * (bar_w - filled)
            line = f"  {bar} {pct:5.1f}%  {format_size(render_cur)} / {format_size(progress_total)}{status_suffix}"
        else:
            line = f"  Transferred: {format_size(render_cur)}{status_suffix}"
        pad = max(0, progress_last_len - len(line))
        sys.stderr.write("\r" + line + " " * pad)
        sys.stderr.flush()
        progress_last_len = len(line)

    def _progress_update_ext(stats: dict) -> None:
        nonlocal progress_cur, progress_total, progress_checks, progress_transfers
        nonlocal progress_status, progress_current_file, _stats_received, _last_stats_detail
        nonlocal reported_bytes_complete_at

        _stats_received = True
        _last_stats_detail = stats
        progress_cur = stats.get("bytes", 0)
        tot = stats.get("totalBytes", 0)
        if tot and tot > 0:
            progress_total = max(progress_total, tot)

        progress_checks = stats.get("checks", 0)
        progress_transfers = stats.get("transfers", 0)

        # Determine current activity
        checking = stats.get("checking", [])
        transferring = stats.get("transferring", [])

        if transferring:
            progress_status = "transferring"
            progress_current_file = transferring[0] if transferring else ""
        elif checking:
            progress_status = "checking"
            progress_current_file = checking[0] if checking else ""
        else:
            progress_status = ""
            progress_current_file = ""

        if (
            is_remote_upload
            and reported_bytes_complete_at is None
            and progress_total > 0
            and progress_cur >= progress_total
        ):
            reported_bytes_complete_at = time.perf_counter()

        if not progress_started:
            return

        if is_remote_upload:
            display_cur, display_status = _progress_while_process_is_running(
                progress_cur,
                progress_total,
                progress_status,
            )
        else:
            display_cur, display_status = progress_cur, progress_status

        if has_rich_progress_ext:
            logger.transfer_progress_ext(
                display_cur,
                progress_total,
                status=display_status,
                current_file=progress_current_file,
                checks=progress_checks,
                transfers=progress_transfers,
            )
        elif has_rich_progress:
            logger.transfer_progress(display_cur, progress_total)
        else:
            _progress_render_simple(display_cur, display_status)

    def _progress_stop() -> None:
        nonlocal progress_started
        if progress_started:
            if not has_rich_progress:
                sys.stderr.write("\n")
                sys.stderr.flush()
            progress_started = False

    process_started_at = time.perf_counter()
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        for raw in proc.stdout:
            fragments = raw.rstrip("\n").split("\r")
            for frag in fragments:
                line = frag.strip()
                if not line:
                    continue

                obj = None
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    obj = None

                if obj is not None and isinstance(obj, dict):
                    # Try extended stats extraction first
                    stats_detail = _extract_stats_detail(obj)
                    if stats_detail is not None:
                        cur = stats_detail["bytes"]
                        tot = stats_detail["totalBytes"]

                        if not progress_started:
                            # Start progress when we have data or activity
                            has_activity = (
                                (tot and tot > 0) or
                                cur > 0 or
                                stats_detail["checks"] > 0 or
                                stats_detail["checking"] or
                                stats_detail["transferring"]
                            )
                            if has_activity:
                                _progress_start(total=tot if tot > 0 else None)
                            else:
                                continue

                        _progress_update_ext(stats_detail)
                        continue

                    # Non-stats JSON: store NOTICE/WARN/ERROR lines for failure messages
                    level = str(obj.get("level", "") or "").lower()
                    msg = str(obj.get("msg", "") or "").strip()
                    if msg:
                        if level in ("error", "fatal", "critical", "warning", "warn", "notice"):
                            _remember_line(f"{level}: {msg}")
                        else:
                            _remember_line(f"{level}: {msg}" if level else msg)
                    continue

                # Plain text line (sometimes appears even with --use-json-log)
                _remember_line(line)
                if logger is None:
                    print(line)

        code = proc.wait()
        process_finished_at = time.perf_counter()

        # Only render the terminal 100% state once process success confirms that
        # remote finalization and rclone's post-upload checks have completed.
        if (
            code == 0
            and is_remote_upload
            and progress_started
            and progress_total > 0
        ):
            if has_rich_progress_ext:
                logger.transfer_progress_ext(
                    progress_total,
                    progress_total,
                    status="complete",
                    current_file="",
                    checks=progress_checks,
                    transfers=progress_transfers,
                )
            elif has_rich_progress:
                logger.transfer_progress(progress_total, progress_total)
            else:
                _progress_render_simple(progress_total, "complete")

        _progress_stop()

        if code:
            tail_lines = list(tail)

            category, user_msg = _classify_failure(
                verb=verb, src=src, dst=dst, exit_code=code, tail_lines=tail_lines
            )

            if category == "unknown":
                # Write full tail to a temp log so users can attach it.
                try:
                    log_path = (
                        Path(tempfile.gettempdir())
                        / f"superluminal_rclone_{uuid.uuid4().hex[:8]}.log"
                    )
                    with log_path.open("w", encoding="utf-8", errors="replace") as fp:
                        fp.write("\n".join(tail_lines))
                    user_msg += f"\n\nDetails saved to: {log_path}"
                except Exception:
                    pass

            raise RcloneError(user_msg, category)

        tail_lines = list(tail)
        redacted_cmd = _redact_cmd(cmd)
        process_elapsed_time = max(0.0, process_finished_at - process_started_at)
        reported_bytes_complete_time = None
        finalization_time = None
        if reported_bytes_complete_at is not None:
            reported_bytes_complete_time = max(
                0.0,
                reported_bytes_complete_at - process_started_at,
            )
            finalization_time = max(
                0.0,
                process_finished_at - reported_bytes_complete_at,
            )

        if not _stats_received:
            return {
                "bytes_transferred": 0,
                "total_bytes": 0,
                "checks": 0,
                "transfers": 0,
                "errors": 0,
                "elapsed_time": 0,
                "process_elapsed_time": process_elapsed_time,
                "reported_bytes_complete_time": reported_bytes_complete_time,
                "finalization_time": finalization_time,
                "stats_received": False,
                "tail_lines": tail_lines,
                "command": redacted_cmd,
            }
        return {
            "bytes_transferred": progress_cur,
            "total_bytes": progress_total,
            "checks": _last_stats_detail.get("checks", 0) if _last_stats_detail else 0,
            "transfers": _last_stats_detail.get("transfers", 0) if _last_stats_detail else 0,
            "errors": _last_stats_detail.get("errors", 0) if _last_stats_detail else 0,
            "elapsed_time": _last_stats_detail.get("elapsedTime", 0) if _last_stats_detail else 0,
            "process_elapsed_time": process_elapsed_time,
            "reported_bytes_complete_time": reported_bytes_complete_time,
            "finalization_time": finalization_time,
            "stats_received": True,
            "tail_lines": tail_lines,
            "command": redacted_cmd,
        }
