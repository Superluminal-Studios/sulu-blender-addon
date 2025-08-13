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
from typing import List

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
    # Fallback
    print(str(msg))


class _TextBar:
    """
    Minimal inline progress bar for when tqdm isn't available.
    Prints to stderr to avoid mixing with regular logs.
    """
    def __init__(self, total: int = 0, desc: str = "Transferred", **kwargs) -> None:
        self.total = int(total) if total else 0
        self.n = 0
        self.desc = desc
        self._last_len = 0

    def _fmt_bytes(self, n: int) -> str:
        # Human-readable bytes (MiB)
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
            # Keep tqdm output on stderr to match prior behavior
            return _tqdm(total=max(int(total or 0), 0), **kwargs)
        except Exception:
            pass
    # Fallback: visible text bar
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

    ("osx",  "amd64"):  "osx-amd64",   # macOS Intel
    ("osx",  "arm64"):  "osx-arm64",   # macOS Apple Silicon

    ("linux",   "386"):    "linux-386",
    ("linux",   "amd64"):  "linux-amd64",
    ("linux",   "arm"):    "linux-arm",      # often ARMv5
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
    """Return the directory where this module resides."""
    return Path(__file__).resolve().parent

def rclone_install_directory() -> Path:
    """
    Return the path to the main 'rclone' subfolder in our add-on directory,
    where rclone subfolders will be stored.
    """
    return get_addon_directory() / "rclone"

def normalize_os(os_name: str) -> str:
    """Normalize OS name to match our SUPPORTED_PLATFORMS keys."""
    os_name = os_name.lower()
    if os_name.startswith("win"):
        return "windows"
    if os_name.startswith("linux"):
        return "linux"
    if os_name.startswith("darwin"):
        return "osx"
    return os_name

def normalize_arch(arch_name: str) -> str:
    """Normalize CPU arch to match SUPPORTED_PLATFORMS keys."""
    arch_name = arch_name.lower()
    # Common synonyms
    if arch_name in ("x86_64", "amd64"):
        return "amd64"
    if arch_name in ("i386", "i686", "x86", "386"):
        return "386"
    if arch_name in ("aarch64", "arm64"):
        return "arm64"
    return arch_name

def get_platform_suffix() -> str:
    """
    Return the 'os-arch' string rclone uses (e.g. 'windows-amd64').
    Raises OSError if the current platform is unsupported.
    """
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
    """
    Return the URL for the current rclone version for this platform.
    """
    suffix = get_platform_suffix()
    return f"https://downloads.rclone.org/rclone-current-{suffix}.zip"

def get_rclone_platform_dir(suffix: str) -> Path:
    """
    Return the subdirectory under rclone_install_directory() for this platform,
    e.g. rclone/<suffix>/ .
    """
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
                # Always show inline progress for this binary download
                sys.stdout.write(f"\r    |{bar}| {percent:5.1f}% ")
                sys.stdout.flush()
    if total:
        print("")  # newline after progress

def ensure_rclone(logger=None) -> Path:
    _log_or_print(logger, "🔍  Checking for rclone…")
    suf = get_platform_suffix()
    bin_name = "rclone.exe" if suf.startswith("windows") else "rclone"
    rclone_bin = get_rclone_platform_dir(suf) / bin_name

    if rclone_bin.exists():
        _log_or_print(logger, "✅  rclone ready")
        return rclone_bin

    # Prepare dirs
    rclone_bin.parent.mkdir(parents=True, exist_ok=True)

    tmp_zip = Path(tempfile.gettempdir()) / f"rclone_{uuid.uuid4()}.zip"
    url = get_rclone_url()
    download_with_bar(url, tmp_zip, logger=logger)

    _log_or_print(logger, "📦  Extracting rclone…")
    with zipfile.ZipFile(tmp_zip) as zf:
        # Many zips nest the binary under a top-level folder; flatten it.
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
            # Best-effort; if chmod fails, we let subprocess raise a clearer error later.
            pass

    _log_or_print(logger, "✅  rclone installed")
    return rclone_bin

def _bytes_from_stats(obj):
    """
    Extract (current_bytes, total_bytes) from rclone --use-json-log stats objects.
    Returns None if no stats are present yet.
    """
    s = obj.get("stats")
    if not s:
        return None
    cur = s.get("bytes")
    tot = s.get("totalBytes") or 0
    if cur is None:
        return None
    return int(cur), int(tot)

# ────────────────────────── main runner ──────────────────────────

def run_rclone(base, verb, src, dst, extra=None, logger=None, file_count=None):
    """
    Execute rclone safely with a friendly progress display.
    - base: list like [rclone_bin, *global_flags]
    - verb: 'copy', 'move', 'moveto', ...
    - src / dst: paths/remotes
    - extra: list of additional rclone flags (e.g. ['--files-from', '/tmp/list.txt'])
    - logger: optional callable(str) for logs
    Raises RuntimeError on failure.
    """
    extra = list(extra or [])
    # Ensure POSIX-style slashes for remote keys
    src = str(src).replace("\\", "/")
    dst = str(dst).replace("\\", "/")

    if not isinstance(base, (list, tuple)) or not base:
        raise RuntimeError("Invalid rclone base command.")

    # IMPORTANT: keep the original ordering your workers expect:
    # command + args + stats flags + *base[1:] (global flags/creds).
    cmd = [base[0], verb, src, dst, *extra,
           "--stats=0.1s", "--use-json-log", "--stats-log-level", "NOTICE",
           *base[1:]]

    _log_or_print(logger, f"{verb.capitalize():9} {src} → {dst}")

    # Stream JSON logs for a smooth progress bar
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
    ) as proc:
        bar = None
        last = 0
        have_real_total = False

        for raw in proc.stdout:
            # rclone mixes \r updates; split them out
            fragments = raw.rstrip("\n").split("\r")
            for frag in fragments:
                line = frag.strip()
                if not line:
                    continue

                # Prefer JSON; hide non-JSON unless no logger (to avoid double logs)
                obj = None
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    obj = None

                if obj is not None:
                    out = _bytes_from_stats(obj)
                    if out is None:
                        # Could inspect 'msg'/'level' for warnings/errors if desired.
                        continue

                    cur, tot = out

                    if bar is None:
                        # Build a visible progress bar (tqdm or text fallback)
                        bar = _progress_bar(
                            total=max(cur, 1),      # dummy until we know the real total
                            unit="B", unit_scale=True, unit_divisor=1024,
                            desc="Transferred", file=sys.stderr,
                        )

                    # Patch in real total when it appears
                    if not have_real_total and tot and tot > getattr(bar, "total", 0):
                        try:
                            bar.total = tot
                            bar.refresh()
                        except Exception:
                            # _TextBar also supports setting total
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

                    # Advance delta
                    delta = cur - last
                    if delta > 0:
                        bar.update(delta)
                        last = cur
                    continue

                # Non-JSON lines: only print if we don't have a logger
                if logger is None:
                    print(line)

        code = proc.wait()
        if bar:
            try:
                bar.close()
            except Exception:
                pass

        if code:
            _log_or_print(logger, f"❌  rclone exited with code {code}")
            raise RuntimeError(f"rclone failed with exit code {code}")
