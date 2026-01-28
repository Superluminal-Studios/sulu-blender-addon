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
from typing import List, Optional, Tuple

# Try to use the add-on's bundled tqdm; fall back to a visible text progress if missing.
try:
    from ..tqdm import tqdm as _tqdm
except Exception:
    _tqdm = None


def _log_or_print(logger, msg: str) -> None:
    if logger:
        try:
            logger(str(msg))
            return
        except Exception:
            pass
    # Fallback - handle Unicode encoding errors on Windows console
    try:
        print(str(msg))
    except UnicodeEncodeError:
        print(str(msg).encode("ascii", errors="replace").decode("ascii"))


class _TextBar:
    """
    Minimal inline progress bar for when tqdm isn't available.
    Prints to stderr to avoid mixing with regular logs.
    """
    def __init__(self, total: int = 0, desc: str = "Transferred", **kwargs) -> None:
        self.n = 0
        self.desc = desc
        self._last_len = 0
        self.total = int(total) if total else 0  # triggers render

    def _fmt_bytes(self, n: int) -> str:
        return f"{n / (1024**2):.1f} MiB"

    def _render(self) -> None:
        if self.total > 0:
            pct = (self.n / max(self.total, 1)) * 100.0
            s = f"{self.desc}: {self._fmt_bytes(self.n)} / {self._fmt_bytes(self.total)} ({pct:5.1f}%)"
        else:
            s = f"{self.desc}: {self._fmt_bytes(self.n)}"
        pad = max(0, self._last_len - len(s))
        sys.stderr.write("\r" + s + " " * pad)
        sys.stderr.flush()
        self._last_len = len(s)

    def update(self, n: int) -> None:
        if n <= 0:
            return
        self.n += int(n)
        self._render()

    def refresh(self) -> None:
        self._render()

    @property
    def total(self) -> int:
        return self._total

    @total.setter
    def total(self, v: int) -> None:
        self._total = int(v) if v else 0
        self._render()

    def close(self) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()


def _progress_bar(total: int = 0, **kwargs):
    """
    Return a tqdm bar if available, otherwise a visible inline text bar.
    """
    if _tqdm is not None:
        try:
            return _tqdm(total=max(int(total or 0), 0), **kwargs)
        except Exception:
            pass
    return _TextBar(total=total, desc=kwargs.get("desc", "Transferred"))


_UNIT = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024 ** 2,
    "GiB": 1024 ** 3,
    "TiB": 1024 ** 4,
    "kB": 1000,
    "MB": 1000 ** 2,
    "GB": 1000 ** 3,
    "TB": 1000 ** 4,
}

# Map (normalized_os, normalized_arch) -> rclone's "os-arch" string
SUPPORTED_PLATFORMS = {
    ("windows", "386"):    "windows-386",
    ("windows", "amd64"):  "windows-amd64",
    ("windows", "arm64"):  "windows-arm64",

    ("osx",  "amd64"):  "osx-amd64",
    ("osx",  "arm64"):  "osx-arm64",

    ("linux",   "386"):    "linux-386",
    ("linux",   "amd64"):  "linux-amd64",
    ("linux",   "arm"):    "linux-arm",
    ("linux",   "armv6"):  "linux-arm-v6",
    ("linux",   "armv7"):  "linux-arm-v7",
    ("linux",   "arm64"):  "linux-arm64",
    ("linux",   "mips"):   "linux-mips",
    ("linux",   "mipsle"): "linux-mipsle",

    ("freebsd", "386"):    "freebsd-386",
    ("freebsd", "amd64"):  "freebsd-amd64",
    ("freebsd", "arm"):    "freebsd-arm",

    ("openbsd", "386"):    "openbsd-386",
    ("openbsd", "amd64"):  "openbsd-amd64",

    ("netbsd",  "386"):    "netbsd-386",
    ("netbsd",  "amd64"):  "netbsd-amd64",

    ("plan9",   "386"):    "plan9-386",
    ("plan9",   "amd64"):  "plan9-amd64",

    ("solaris", "amd64"):  "solaris-amd64",
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

def download_with_bar(url: str, dest: Path, logger=None) -> None:
    s = Session()
    retries = Retry(
        total=3,
        backoff_factor=0.4,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods={'POST', 'GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE', 'TRACE', 'CONNECT'},
    )
    s.mount('https://', HTTPAdapter(max_retries=retries))
    _log_or_print(logger, "⬇️  Downloading rclone…")
    resp = s.get(url, stream=True, timeout=600)
    resp.raise_for_status()

    total = int(resp.headers.get("Content-Length", 0))
    done = 0
    bar_cols = 40

    with dest.open("wb") as fp:
        for chunk in resp.iter_content(1024 * 64):
            if not chunk:
                continue
            fp.write(chunk)
            done += len(chunk)
            if total:
                filled = int(bar_cols * done / total)
                bar = "█" * filled + " " * (bar_cols - filled)
                percent = (done * 100) / total
                sys.stdout.write(f"\r    |{bar}| {percent:5.1f}% ")
                sys.stdout.flush()
    if total:
        print("")

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

    _log_or_print(logger, "📦  Extracting rclone…")
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

    _log_or_print(logger, "✅  rclone installed")
    return rclone_bin

def _bytes_from_stats(obj):
    s = obj.get("stats")
    if not s:
        return None
    cur = s.get("bytes")
    tot = s.get("totalBytes") or 0
    if cur is None:
        return None
    return int(cur), int(tot)


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
#  Error classification + UX cleanup
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
    Take a Go duration string like '-1h0m44.216s' and return a friendlier '1h 0m 44s' (absolute).
    If parsing fails, returns the original (absolute) string.
    """
    s = str(d or "").strip()
    if not s:
        return ""
    if s[0] in "+-":
        s = s[1:]
    # Common Go duration pieces: 1h, 2m, 44.2s, 500ms, etc.
    h = re.search(r"(\d+)h", s)
    m = re.search(r"(\d+)m", s)
    sec = re.search(r"(\d+(?:\.\d+)?)s", s)

    parts = []
    if h:
        parts.append(f"{int(h.group(1))}h")
    if m:
        parts.append(f"{int(m.group(1))}m")
    if sec:
        # Round seconds to nearest integer for UX
        try:
            parts.append(f"{int(round(float(sec.group(1))))}s")
        except Exception:
            parts.append(f"{sec.group(1)}s")

    if parts:
        return " ".join(parts)
    return s

def _extract_time_skew(tail_lines: List[str]) -> Optional[Tuple[str, str]]:
    """
    Look for rclone's helpful notice:
      'Time may be set wrong - time from "host" is -1h0m44s different from this computer'
    Returns (host, approx_delta) or None.
    """
    for ln in tail_lines:
        low = str(ln).lower()
        if "time may be set wrong" not in low:
            continue
        m = _TIME_SKEW_RE.search(str(ln))
        if not m:
            # Still a strong signal even if format changes
            return ("storage server", "")
        host = m.group("host").strip() or "storage server"
        delta = m.group("delta").strip()
        return (host, _format_go_duration_approx(delta))
    return None

def _pick_technical_line(tail_lines: List[str]) -> str:
    """
    Pick a single, useful technical line without spamming retries.
    Preference:
      1) "Failed to ..." summary line
      2) any line with StatusCode / Forbidden / AccessDenied
      3) last non-empty line
    """
    # 1) "Failed to ..."
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if not s:
            continue
        if "failed to" in s.lower():
            return s
    # 2) HTTP-ish / auth-ish
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if not s:
            continue
        low = s.lower()
        if "statuscode" in low or "forbidden" in low or "accessdenied" in low or "unauthorized" in low:
            return s
    # 3) last
    for ln in reversed(tail_lines):
        s = str(ln).strip()
        if s:
            return s
    return ""

def _classify_failure(verb: str, src: str, dst: str, exit_code: int, tail_lines: List[str]) -> Tuple[str, str]:
    """
    Returns (category, user_message).
    Message intentionally has NO leading emoji (callers already add them).
    """
    blob = "\n".join([str(x) for x in (tail_lines or [])]).strip()
    low = blob.lower()

    # ---- Clock skew / wrong system time ----
    # rclone emits a very explicit NOTICE for clock skew; prioritize it.
    skew = _extract_time_skew(tail_lines)
    if skew is not None:
        host, delta = skew
        delta_str = f" ({delta})" if delta else ""
        return (
            "clock_skew",
            "Storage authentication failed because your computer clock is out of sync with the storage service"
            f"{delta_str}.\n"
            "\n"
            "Fix:\n"
            "  • Turn on automatic time sync in your OS, then retry.\n"
            "    - Windows: Settings → Time & language → Date & time → “Set time automatically” → “Sync now”\n"
            "    - macOS: System Settings → General → Date & Time → “Set time and date automatically”\n"
            "    - Linux: enable NTP (often: `sudo timedatectl set-ntp true`)\n"
            "\n"
            f"Technical: time differs from {host}{delta_str}."
        )

    # Also catch other time-related strings (TLS / x509, skew errors, expired request)
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
            "Storage authentication failed and your system clock appears incorrect.\n"
            "\n"
            "Fix:\n"
            "  • Turn on automatic time sync in your OS, then retry.\n"
            "    - Windows: Settings → Time & language → Date & time → “Set time automatically” → “Sync now”\n"
            "    - macOS: System Settings → General → Date & Time → “Set time and date automatically”\n"
            "    - Linux: enable NTP (often: `sudo timedatectl set-ntp true`)\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or f'exit code {exit_code}'}"
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
            "Transfer failed because your computer ran out of disk space while writing files.\n"
            f"Free space (approx.): {free_str}\n"
            "\n"
            "Fix:\n"
            "  • Free up disk space (or choose a different destination folder)\n"
            "  • Then retry\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or 'disk full'}"
        )

    # ---- Network / connection errors (check BEFORE quota to avoid false positives) ----
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
            "Transfer failed due to a network connection issue.\n"
            "\n"
            "Fix:\n"
            "  • Check your internet connection\n"
            "  • If on WiFi, try moving closer to router or use ethernet\n"
            "  • Retry the upload — large files sometimes need multiple attempts\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or 'network error'}"
        )

    # ---- Remote quota / storage exhausted ----
    remote_space_markers = (
        "insufficient storage",
        "insufficientstorage",
        "quota exceeded",
        "storagequotaexceeded",
        "statuscode: 507",
        "statuscode:507",
        "notentitled",  # common R2-style entitlement/billing signal
    )
    if any(m in low for m in remote_space_markers):
        return (
            "remote_storage_full",
            "Transfer failed because the storage service reports insufficient storage / quota.\n"
            "\n"
            "Fix:\n"
            "  • Free space in your cloud storage / plan (or upgrade)\n"
            "  • Then retry\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or 'insufficient storage/quota'}"
        )

    # ---- Not found (useful for downloader) ----
    not_found_markers = ("directory not found", "no such key", "404", "not exist", "cannot find")
    if any(m in low for m in not_found_markers):
        return (
            "not_found",
            "Nothing to transfer yet (source path not found). This is often normal if outputs haven’t been produced yet.\n"
            f"Technical: {_pick_technical_line(tail_lines) or f'exit code {exit_code}'}"
        )

    # ---- Permissions / auth (403 etc) ----
    perm_markers = ("statuscode: 403", " forbidden", "accessdenied", "unauthorized", "invalidaccesskeyid", "signaturedoesnotmatch")
    if any(m in low for m in perm_markers):
        return (
            "forbidden",
            "Storage rejected the request (HTTP 403 Forbidden).\n"
            "\n"
            "Fix:\n"
            "  • Log out and back in (to refresh credentials), then retry\n"
            "  • Make sure your system time is correct\n"
            "\n"
            f"Technical: {_pick_technical_line(tail_lines) or '403 forbidden'}"
        )

    # ---- Default ----
    tech = _pick_technical_line(tail_lines)
    if tech:
        return ("unknown", f"rclone failed (exit code {exit_code}).\nTechnical: {tech}")
    return ("unknown", f"rclone failed (exit code {exit_code}).")

# ────────────────────────── main runner ──────────────────────────

def run_rclone(base, verb, src, dst, extra=None, logger=None, file_count=None):
    """
    Execute rclone safely with a friendly progress display.
    Raises RuntimeError on failure (message is user-friendly, no emoji).

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
    # Only do this if the args look like ["--files-from", "<path>"] etc.
    if "--files-from" in extra and _rclone_supports_flag(rclone_exe, "--files-from-raw"):
        upgraded = []
        i = 0
        while i < len(extra):
            if extra[i] == "--files-from":
                upgraded.append("--files-from-raw")
                # preserve next arg (path)
                if i + 1 < len(extra):
                    upgraded.append(extra[i + 1])
                    i += 2
                    continue
            upgraded.append(extra[i])
            i += 1
        extra = upgraded

    # Add local unicode normalization if supported and not already present.
    if _rclone_supports_flag(rclone_exe, "--local-unicode-normalization"):
        if "--local-unicode-normalization" not in extra and "--local-unicode-normalization" not in base:
            extra = ["--local-unicode-normalization"] + extra

    cmd = [base[0], verb, src, dst, *extra,
           "--stats=0.1s", "--use-json-log", "--stats-log-level", "NOTICE",
           *base[1:]]

    # Keep a small tail of non-stats output so failures are actionable.
    tail = deque(maxlen=120)

    def _remember_line(s: str) -> None:
        s = str(s or "").strip()
        if not s:
            return
        tail.append(s)

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        bar = None
        last = 0
        have_real_total = False

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
                    out = _bytes_from_stats(obj)
                    if out is not None:
                        cur, tot = out

                        # UX: don't create a bar for 0 bytes / unknown totals.
                        # This prevents the noisy "0.00/1.00" line on immediate failures.
                        if bar is None:
                            if tot and tot > 0:
                                bar = _progress_bar(
                                    total=tot,
                                    unit="B", unit_scale=True, unit_divisor=1024,
                                    desc="Transferred", file=sys.stderr,
                                )
                                have_real_total = True
                            elif cur > 0:
                                bar = _progress_bar(
                                    total=max(cur, 1),
                                    unit="B", unit_scale=True, unit_divisor=1024,
                                    desc="Transferred", file=sys.stderr,
                                )
                            else:
                                # Nothing moving yet; keep listening.
                                last = cur
                                continue

                        # Patch in real total when it appears
                        if bar is not None:
                            if not have_real_total and tot and tot > getattr(bar, "total", 0):
                                try:
                                    bar.total = tot
                                    bar.refresh()
                                except Exception:
                                    bar.total = tot
                                    bar.refresh()
                                have_real_total = True
                            elif cur > getattr(bar, "total", 0):
                                try:
                                    bar.total = cur
                                    bar.refresh()
                                except Exception:
                                    bar.total = cur
                                    bar.refresh()

                            delta = cur - last
                            if delta > 0:
                                bar.update(delta)
                            last = cur

                        continue

                    # Non-stats JSON: store NOTICE/WARN/ERROR lines for failure messages
                    level = str(obj.get("level", "") or "").lower()
                    msg = str(obj.get("msg", "") or "").strip()
                    if msg:
                        # Keep these; do not spam-print INFO.
                        if level in ("error", "fatal", "critical", "warning", "warn", "notice"):
                            _remember_line(f"{level}: {msg}")
                        else:
                            _remember_line(f"{level}: {msg}" if level else msg)
                    continue

                # Plain text line (sometimes appears even with --use-json-log)
                _remember_line(line)
                if logger is None:
                    # Only live-print plain text when no logger is present
                    print(line)

        code = proc.wait()

        if bar:
            try:
                bar.close()
            except Exception:
                pass

        if code:
            tail_lines = list(tail)

            category, user_msg = _classify_failure(
                verb=verb, src=src, dst=dst, exit_code=code, tail_lines=tail_lines
            )

            # For unknown errors, provide a tiny hint for support without dumping retries.
            if category == "unknown":
                # Write full tail to a temp log (no credentials), so users can attach it.
                try:
                    log_path = Path(tempfile.gettempdir()) / f"superluminal_rclone_{uuid.uuid4().hex[:8]}.log"
                    with log_path.open("w", encoding="utf-8", errors="replace") as fp:
                        fp.write("\n".join(tail_lines))
                    user_msg += f"\n\nDetails saved to: {log_path}"
                except Exception:
                    pass

            raise RuntimeError(user_msg)
