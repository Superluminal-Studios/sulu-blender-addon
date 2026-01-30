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
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from requests import Session
import sys
import json
import re
import shutil
from collections import deque
from typing import List, Optional, Tuple, Any


# Unicode glyphs (no emoji)
_GLYPH_DOWN = "↓"
_GLYPH_OK = "✓"
_GLYPH_FAIL = "✕"


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
    return f"https://downloads.rclone.org/rclone-current-{suffix}.zip"


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
    s = Session()
    retries = Retry(
        total=3,
        backoff_factor=0.4,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods={
            "POST",
            "GET",
            "HEAD",
            "OPTIONS",
            "PUT",
            "DELETE",
            "TRACE",
            "CONNECT",
        },
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))

    _call_logger(logger, "info", f"{_GLYPH_DOWN} Preparing rclone")
    resp = s.get(url, stream=True, timeout=600)
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


def ensure_rclone(logger=None) -> Path:
    suf = get_platform_suffix()
    bin_name = "rclone.exe" if suf.startswith("windows") else "rclone"
    rclone_bin = get_rclone_platform_dir(suf) / bin_name

    if rclone_bin.exists():
        return rclone_bin

    rclone_bin.parent.mkdir(parents=True, exist_ok=True)

    tmp_zip = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"
    url = get_rclone_url()
    download_with_bar(url, tmp_zip, logger=logger)

    _call_logger(logger, "info", "Extracting rclone")
    with zipfile.ZipFile(tmp_zip) as zf:
        target_written = False
        for m in zf.infolist():
            if m.filename.lower().endswith(("rclone.exe", "rclone")) and not m.is_dir():
                m.filename = os.path.basename(m.filename)
                zf.extract(m, rclone_bin.parent)
                (rclone_bin.parent / m.filename).rename(rclone_bin)
                target_written = True
                break
    tmp_zip.unlink(missing_ok=True)

    if not target_written or not rclone_bin.exists():
        raise RuntimeError("Failed to extract rclone binary.")

    if not suf.startswith("windows"):
        try:
            rclone_bin.chmod(rclone_bin.stat().st_mode | 0o111)
        except Exception:
            pass

    _call_logger(logger, "info", f"{_GLYPH_OK} rclone ready")
    return rclone_bin


def _bytes_from_stats(obj):
    """Extract bytes transferred from rclone stats JSON."""
    s = obj.get("stats")
    if not s:
        return None
    cur = s.get("bytes")
    tot = s.get("totalBytes") or 0
    if cur is None:
        return None
    return int(cur), int(tot)


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
        "checking": _extract_names(s.get("checking")),
        "transferring": _extract_names(s.get("transferring")),
    }


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
#  Error classification + UX cleanup (unchanged logic, calmer text)
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


def _human_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "unknown"
    if n < 0:
        n = 0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n = n / 1024.0
    return f"{n:.1f} TiB"


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

        free_str = _human_bytes(free) if free is not None else "unknown"
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
    not_found_markers = (
        "directory not found",
        "no such key",
        "404",
        "not exist",
        "cannot find",
    )
    if any(m in low for m in not_found_markers):
        return (
            "not_found",
            f"Source not found. This can be normal if outputs haven't been produced yet.\n\n[{tech}]",
        )

    # ---- Permissions / auth (403 etc) ----
    perm_markers = (
        "statuscode: 403",
        " forbidden",
        "accessdenied",
        "unauthorized",
        "invalidaccesskeyid",
        "signaturedoesnotmatch",
    )
    if any(m in low for m in perm_markers):
        return (
            "forbidden",
            f"Access denied. Log out and back in to refresh credentials, then retry.\n\n[{tech}]",
        )

    return ("unknown", f"Transfer failed. Retry, or contact support if this persists.\n\n[{tech}]")


# ────────────────────────── main runner ──────────────────────────


def run_rclone(base, verb, src, dst, extra=None, logger=None, file_count=None, total_bytes=None):
    """
    Execute rclone safely with a friendly progress display.
    Raises RuntimeError on failure (message is user-friendly, no emoji).

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
    progress_current_file = ""

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
            sys.stderr.write(f"  Preparing transfer ({_human_bytes(progress_total)})\r")
            sys.stderr.flush()

    def _fmt_bytes(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        if n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.1f} MB"
        return f"{n / (1024 * 1024 * 1024):.2f} GB"

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

    def _progress_render_simple() -> None:
        nonlocal progress_last_len
        # Build status suffix
        status_suffix = ""
        if progress_status == "checking" and progress_current_file:
            status_suffix = f"  Verifying: {_shorten_filename(progress_current_file, 25)}"
        elif progress_status == "checking":
            status_suffix = f"  Verifying ({progress_checks} checked)"
        elif progress_transfers > 0 and progress_checks > progress_transfers:
            # More checks than transfers = some files skipped
            skipped = progress_checks - progress_transfers
            status_suffix = f"  ({skipped} unchanged)"

        if progress_total > 0:
            pct = (progress_cur / max(progress_total, 1)) * 100.0
            bar_w = 24
            filled = int(bar_w * progress_cur / max(progress_total, 1))
            bar = "█" * filled + "░" * (bar_w - filled)
            line = f"  {bar} {pct:5.1f}%  {_fmt_bytes(progress_cur)} / {_fmt_bytes(progress_total)}{status_suffix}"
        else:
            line = f"  Transferred: {_fmt_bytes(progress_cur)}{status_suffix}"
        pad = max(0, progress_last_len - len(line))
        sys.stderr.write("\r" + line + " " * pad)
        sys.stderr.flush()
        progress_last_len = len(line)

    def _progress_update_ext(stats: dict) -> None:
        nonlocal progress_cur, progress_total, progress_checks, progress_transfers
        nonlocal progress_status, progress_current_file

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

        if not progress_started:
            return

        if has_rich_progress_ext:
            logger.transfer_progress_ext(
                progress_cur,
                progress_total,
                status=progress_status,
                current_file=progress_current_file,
                checks=progress_checks,
                transfers=progress_transfers,
            )
        elif has_rich_progress:
            logger.transfer_progress(progress_cur, progress_total)
        else:
            _progress_render_simple()

    def _progress_update(cur: int, tot: Optional[int] = None) -> None:
        nonlocal progress_cur, progress_total
        progress_cur = cur
        if tot and tot > 0:
            progress_total = max(progress_total, tot)
        if not progress_started:
            return
        if has_rich_progress:
            logger.transfer_progress(progress_cur, progress_total)
        else:
            _progress_render_simple()

    def _progress_stop() -> None:
        nonlocal progress_started
        if progress_started:
            if not has_rich_progress:
                sys.stderr.write("\n")
                sys.stderr.flush()
            progress_started = False

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        last_bytes = 0

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
                                last_bytes = cur
                                continue

                        _progress_update_ext(stats_detail)
                        last_bytes = cur
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

            raise RuntimeError(user_msg)
