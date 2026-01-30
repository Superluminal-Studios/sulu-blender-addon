# utils/worker_utils.py
"""
worker_utils.py — Shared utilities for Sulu worker processes.

Contains:
- Console/terminal helpers (clear, launch terminal, open folder)
- Text formatting (pluralization, size formatting, path shortening)
- Unicode/environment detection
- Path utilities (drive detection, S3 key cleaning, path comparison)
- File probing (readability checks, cloud storage detection)
- HTTP session factory with retry logic
- rclone command building
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# third-party
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# constants
# Windows process creation flags
DETACHED_PROCESS = 0x00000008  # detached (no console)
CREATE_NEW_CONSOLE = 0x00000010  # force a new console window
CREATE_NEW_PROCESS_GROUP = 0x00000200  # allow Ctrl+C to target child

CLOUDFLARE_ACCOUNT_ID = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Common flags we want on *every* rclone call that uses R2
COMMON_RCLONE_FLAGS: list[str] = [
    "--s3-provider",
    "Cloudflare",
    "--s3-env-auth",  # allow env creds if present
    "--s3-region",
    "auto",
    "--s3-no-check-bucket",
]


def clear_console():
    """
    Clears the console screen based on the operating system.
    """
    if os.name == "nt":  # For Windows
        os.system("cls")
    else:  # For macOS and Linux
        os.system("clear")


# user-facing logging
def logger(msg: str) -> None:
    """
    Simple user-facing logger; prints a single message and flushes immediately.
    Intentionally accepts just one string (callers pass already-formatted text).
    Handles Unicode encoding errors on Windows console gracefully.
    """
    try:
        print(str(msg), flush=True)
    except UnicodeEncodeError:
        # Fall back to ASCII-safe output on Windows console
        print(str(msg).encode("ascii", errors="replace").decode("ascii"), flush=True)


def _log(msg: str) -> None:
    """Thin wrapper around print(..., flush=True); kept for backward-compat."""
    try:
        print(str(msg), flush=True)
    except UnicodeEncodeError:
        print(str(msg).encode("ascii", errors="replace").decode("ascii"), flush=True)


# small UX helpers
def shorten_path(path: str) -> str:
    """
    Return a version of `path` no longer than 64 characters,
    inserting “...” in the middle if it’s longer. Preserves both ends.
    """
    max_len = 64
    dots = "..."
    path = str(path)
    if len(path) <= max_len:
        return path
    keep = max_len - len(dots)
    left = keep // 2
    right = keep - left
    return f"{path[:left]}{dots}{path[-right:]}"


def open_folder(path: str, logger_instance=None) -> None:
    """
    Best-effort attempt to open a folder in the OS file manager.
    Never raises; logs a friendly message on failure.

    Args:
        path: The folder path to open.
        logger_instance: Optional SubmitLogger instance for styled output.
    """
    def _log_info(msg: str) -> None:
        if logger_instance and hasattr(logger_instance, "info"):
            logger_instance.info(msg)
        else:
            logger(msg)

    def _log_warning(msg: str) -> None:
        if logger_instance and hasattr(logger_instance, "warning"):
            logger_instance.warning(msg)
        else:
            logger(msg)

    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            # xdg-open is the cross-desktop standard; fallback to printing
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", path])
            else:
                _log_info(f"To open the folder manually, browse to: {path}")
    except Exception as e:
        _log_warning(f"Couldn't open folder automatically: {e}")


def _win_quote(arg: str) -> str:
    """Minimal cmd.exe-safe quoting with double quotes."""
    if not arg:
        return '""'
    if any(ch in arg for ch in " \t&()[]{}^=;!+,`~|<>"):
        return '"' + arg.replace('"', '""') + '"'
    return arg


def launch_in_terminal(cmd: List[str]) -> None:
    system = platform.system()

    # WSL hint: treat as Linux
    if "microsoft" in platform.release().lower():
        system = "Linux"

    if system == "Windows":
        # 1) Best: create a brand-new console directly (no shell)
        try:
            subprocess.Popen(
                cmd, creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP
            )
            return
        except Exception:
            pass

        # 2) Fallback: use cmd.exe start with correct quoting
        try:
            quoted = " ".join(_win_quote(c) for c in cmd)
            subprocess.Popen(f'cmd.exe /c start "" {quoted}', shell=True)
            return
        except Exception:
            pass

        # 3) Last resort: run in current console (blocking)
        subprocess.call(cmd)
        return

    # macOS
    if system == "Darwin":
        try:
            worker = " ".join(shlex.quote(c) for c in cmd)  # POSIX shell here is fine
            script_osas = worker.replace('"', '\\"')
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    'tell application "Terminal" to activate',
                    "-e",
                    f'tell application "Terminal" to do script "{script_osas}"',
                ]
            )
            return
        except Exception:
            subprocess.call(cmd)
            return

    # 3) Linux / BSD — try common emulators (in a reasonable order)
    if system in ("Linux", "FreeBSD"):
        quoted = shlex.join(cmd)
        bash_wrap = ["bash", "-lc", quoted]  # preserves PATH, allows shell features

        for term, prefix in (
            # Mainstream defaults (GNOME / KDE / Xfce)
            ("gnome-terminal", ["gnome-terminal", "--"]),
            ("konsole", ["konsole", "-e"]),
            ("xfce4-terminal", ["xfce4-terminal", "--command"]),
            # Modern / GPU-accelerated / tiling
            ("kitty", ["kitty", "--hold"]),
            ("alacritty", ["alacritty", "-e"]),
            ("wezterm", ["wezterm", "start", "--"]),
            ("tilix", ["tilix", "-e"]),
            ("terminator", ["terminator", "-x"]),
            # Other DE-specific or traditional
            ("mate-terminal", ["mate-terminal", "-e"]),
            ("lxterminal", ["lxterminal", "-e"]),
            ("qterminal", ["qterminal", "-e"]),
            ("deepin-terminal", ["deepin-terminal", "-e"]),
            # Lightweight / legacy
            ("urxvt", ["urxvt", "-hold", "-e"]),
            ("xterm", ["xterm", "-e"]),
            ("st", ["st", "-e"]),
            # Debian/Ubuntu alternatives wrapper
            ("x-terminal-emulator", ["x-terminal-emulator", "-e"]),
        ):
            if shutil.which(term):
                try:
                    subprocess.Popen([*prefix, *bash_wrap])
                    return
                except Exception:
                    continue  # try the next emulator

    # 4) Absolute last resort — synchronous execution in the current shell
    subprocess.call(cmd)


# robust HTTP sessions
def requests_retry_session(
    *,
    retries: int = 5,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504, 522, 524),
    allowed_methods: tuple[str, ...] = (
        "HEAD",
        "GET",
        "OPTIONS",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ),
    session: requests.Session | None = None,
) -> requests.Session:
    """
    Return a requests.Session pre-configured to retry automatically.

    Defaults favor reliability on flaky networks, with jitter via
    exponential backoff. This does *not* raise until retries are exhausted.
    """
    session = session or requests.Session()

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        allowed_methods=frozenset(allowed_methods),
        status_forcelist=status_forcelist,
        backoff_factor=backoff_factor,
        raise_on_status=False,
        respect_retry_after_header=True,
    )

    # Slightly larger pools reduce connection churn during uploads/downloads.
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=32)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# save/flush detection
def is_blend_saved(path: str | Path, logger_instance=None) -> None:
    """
    Block until a "*.blend" file is finished saving.

    Blender typically writes a sentinel `<file>.blend@` while saving.
    We wait for the sentinel to disappear *and* for the file size to
    remain stable for ~0.5s as an extra safety check (covers network drives).

    Args:
        path: The .blend file path to check.
        logger_instance: Optional SubmitLogger instance for styled output.
    """
    def _log_info(msg: str) -> None:
        if logger_instance and hasattr(logger_instance, "info"):
            logger_instance.info(msg)
        else:
            _log(msg)

    def _log_success(msg: str) -> None:
        if logger_instance and hasattr(logger_instance, "success"):
            logger_instance.success(msg)
        else:
            _log(msg)

    path = str(path)
    warned = False

    # Track size stability to avoid racing network/Drive syncs
    last_size = -1
    stable_ticks = 0  # 2 ticks of 0.25s ≈ 0.5s stable

    while True:
        sentinel_exists = os.path.exists(path + "@")
        file_exists = os.path.exists(path)
        size = os.path.getsize(path) if file_exists else -1

        if not sentinel_exists and file_exists:
            if size == last_size:
                stable_ticks += 1
            else:
                stable_ticks = 0
            last_size = size

            if stable_ticks >= 2:  # ~0.5s of stability
                if warned:
                    _log_success("File saved. Proceeding.")
                return
        else:
            # Still saving; print a one-time friendly note
            if not warned:
                _log_info("Waiting for Blender to finish saving")
                _log_info("If this takes a while, background sync apps (Dropbox, Google Drive) may be scanning the file.")
                warned = True

        time.sleep(0.25)


# tiny compatibility helpers
def _short(p: str) -> str:
    """Return just the basename unless the string already looks like an S3 path."""
    return p if str(p).startswith(":s3:") else Path(str(p)).name


# rclone base command
def _build_base(
    rclone_bin: Path,
    endpoint: str,
    s3: Dict[str, str],
) -> List[str]:
    """
    Construct the base rclone CLI invocation shared by all commands.

    Returns a list where element 0 is the rclone binary, and element 1..N are
    *global flags*. Our run_rclone() implementation appends these *after* the
    verb to match existing workers’ expectations.
    """
    # Validate and lift credentials with friendly errors
    try:
        access_key = s3["access_key_id"]
        secret_key = s3["secret_access_key"]
    except KeyError as exc:
        raise ValueError(f"Missing S3 credential: {exc}") from exc

    session_token = s3.get("session_token") or ""

    base: list[str] = [
        str(rclone_bin),
        "--s3-endpoint",
        endpoint,
        "--s3-access-key-id",
        access_key,
        "--s3-secret-access-key",
        secret_key,
    ]

    # Only include session token if provided; some providers omit it.
    if session_token:
        base.extend(["--s3-session-token", session_token])

    # Add our shared flags (provider, region, etc.)
    base.extend(COMMON_RCLONE_FLAGS)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Text formatting utilities
# ─────────────────────────────────────────────────────────────────────────────


def plural_word(word: str) -> str:
    """
    Best-effort English pluralization for common cases.

    Handles irregular forms used in this project (dependency -> dependencies).
    For special cases, pass an explicit plural to count() instead.
    """
    w = str(word or "")
    lw = w.lower()

    # Common irregulars in this project
    if lw == "dependency":
        return "dependencies"
    if lw == "directory":
        return "directories"

    # Standard heuristics
    if lw.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    if lw.endswith("y") and len(lw) >= 2 and lw[-2] not in "aeiou":
        return w[:-1] + "ies"
    return w + "s"


def count(n: int, singular: str, plural: Optional[str] = None) -> str:
    """
    Return '1 thing' / '2 things' with correct pluralization.

    Avoids awkward '(s)' constructions for cleaner copy.
    """
    try:
        n_int = int(n)
    except Exception:
        n_int = 0
    if n_int == 1:
        return f"{n_int} {singular}"
    return f"{n_int} {plural or plural_word(singular)}"


def format_size(size_bytes: int) -> str:
    """
    Format bytes as human readable string.

    Uses decimal units for file/transfer size:
      1 KB = 1000 B, 1 MB = 1000 KB, 1 GB = 1000 MB
    """
    try:
        size_bytes = int(size_bytes)
    except Exception:
        return "unknown"
    if size_bytes < 1000:
        return f"{size_bytes} B"
    if size_bytes < 1000 * 1000:
        return f"{size_bytes / 1000:.1f} KB"
    if size_bytes < 1000 * 1000 * 1000:
        return f"{size_bytes / (1000 * 1000):.1f} MB"
    return f"{size_bytes / (1000 * 1000 * 1000):.2f} GB"


def normalize_nfc(s: str) -> str:
    """Normalize string to NFC form (matches BAT's archive path normalization)."""
    return unicodedata.normalize("NFC", str(s))


# ─────────────────────────────────────────────────────────────────────────────
# Environment / terminal detection
# ─────────────────────────────────────────────────────────────────────────────


def debug_enabled() -> bool:
    """Check if SULU_DEBUG environment variable is set."""
    return os.environ.get("SULU_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def is_interactive() -> bool:
    """Check if we're running in an interactive terminal."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def supports_unicode() -> bool:
    """Best-effort check whether Unicode output is safe in this terminal."""
    try:
        encoding = sys.stdout.encoding or ""
        if "utf" in encoding.lower():
            return True
    except Exception:
        pass

    if "utf" in os.environ.get("PYTHONIOENCODING", "").lower():
        return True

    if sys.platform == "win32":
        # Windows Terminal / VS Code terminal
        if os.environ.get("WT_SESSION"):
            return True
        if os.environ.get("TERM_PROGRAM", "").lower() in ("vscode",):
            return True
        return False

    return True


# Cached result for performance
_UNICODE_SUPPORTED = supports_unicode()
ELLIPSIS = "…" if _UNICODE_SUPPORTED else "..."


def safe_input(prompt: str, default: str = "", log_fn: Optional[Callable[[str], None]] = None) -> str:
    """
    Safe input wrapper that handles non-interactive (automated) mode.

    When stdin is not a TTY (e.g., in automated tests or piped input),
    returns the default value instead of blocking on input().
    """
    if is_interactive():
        return input(prompt)
    # Non-interactive mode: log and return default
    if log_fn:
        log_fn(f"[auto] {prompt.strip()} -> {repr(default)}")
    return default


# ─────────────────────────────────────────────────────────────────────────────
# Path utilities (OS-agnostic drive detection + S3 key cleaning)
# ─────────────────────────────────────────────────────────────────────────────

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]+")
_IS_MAC = sys.platform == "darwin"


def is_win_drive_path(p: str) -> bool:
    """Check if path looks like a Windows drive path (e.g., C:\\...)."""
    return bool(_WIN_DRIVE_RE.match(str(p)))


def norm_abs_for_detection(path: str) -> str:
    """Normalize a path for comparison but keep Windows-looking/UNC paths intact on POSIX."""
    p = str(path).replace("\\", "/")
    if is_win_drive_path(p) or p.startswith("//") or p.startswith("\\\\"):
        return p
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/")


def get_drive(path: str) -> str:
    """
    Return a drive token representing the path's root device for cross-drive checks.

    Returns:
    - Windows letters: "C:", "D:", ...
    - UNC: "UNC"
    - macOS volumes: "/Volumes/NAME"
    - Linux removable/media: "/media/USER/NAME" or "/mnt/NAME"
    - Otherwise POSIX root "/"
    """
    p = str(path).replace("\\", "/")
    if is_win_drive_path(p):
        return (p[:2]).upper()  # "C:"
    if p.startswith("//") or p.startswith("\\\\"):
        return "UNC"
    if os.name == "nt":
        return os.path.splitdrive(p)[0].upper()

    # macOS volumes
    if p.startswith("/Volumes/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return "/Volumes/" + parts[2]
        return "/Volumes"

    # Linux common mounts
    if p.startswith("/media/"):
        parts = p.split("/")
        if len(parts) >= 4:
            return f"/media/{parts[2]}/{parts[3]}"
        return "/media"

    if p.startswith("/mnt/"):
        parts = p.split("/")
        if len(parts) >= 3:
            return f"/mnt/{parts[2]}"
        return "/mnt"

    # Fallback: POSIX root
    return "/"


def relpath_safe(child: str, base: str) -> str:
    """Safe relpath with POSIX separators. Caller must ensure same 'drive'."""
    return os.path.relpath(child, start=base).replace("\\", "/")


def s3key_clean(key: str) -> str:
    """
    Ensure S3 keys / manifest lines are clean and relative.

    - Collapse duplicate slashes
    - Strip any leading slash
    - Normalize '.' and '..'
    """
    k = str(key).replace("\\", "/")
    k = re.sub(r"/+", "/", k)  # collapse duplicate slashes
    k = k.lstrip("/")  # forbid leading slash
    k = os.path.normpath(k).replace("\\", "/")
    if k == ".":
        return ""  # do not allow '.' as a key
    return k


def samepath(a: str, b: str) -> bool:
    """Case-insensitive, normalized equality check suitable for Windows/POSIX."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def looks_like_cloud_storage_path(p: str) -> bool:
    """Check if path appears to be in a cloud-synced folder."""
    s = str(p or "").replace("\\", "/")
    return (
        "/Library/CloudStorage/" in s
        or "/Dropbox" in s
        or "/OneDrive" in s
        or "/iCloud" in s
        or "/Mobile Documents/" in s
    )


# ─────────────────────────────────────────────────────────────────────────────
# File probing utilities
# ─────────────────────────────────────────────────────────────────────────────


def mac_permission_help(path: str, err: str) -> str:
    """Generate macOS-specific help text for permission errors."""
    lines = [
        "macOS blocked access to a dependency needed for submission.",
        "",
        "Fix:",
        "  - System Settings -> Privacy & Security -> Full Disk Access",
        "  - Enable the app running this submission (Terminal/iTerm if you see this console; otherwise Blender).",
    ]
    if looks_like_cloud_storage_path(path):
        lines += [
            "",
            "Cloud storage note:",
            "  - This dependency is in a cloud-synced folder.",
            "  - Make sure the file is downloaded and available offline, then submit again.",
        ]
    lines += ["", f"Technical: {err}"]
    return "\n".join(lines)


def probe_readable_file(
    p: str, *, hydrate: bool = False, cloud_files_module=None
) -> Tuple[bool, Optional[str]]:
    """
    Check if a file exists and can be read.

    Returns (ok, error_message):
    - ok=True: file exists and can be opened for reading
    - ok=False: missing or not readable (permission / offline placeholder / etc.)

    If hydrate=True, reads the entire file to force cloud-mounted drives (OneDrive,
    Google Drive, iCloud, etc.) to fully download "dehydrated" placeholder files.
    This ensures files are actually available before rclone tries to upload them.
    """
    path = str(p)

    # Check for directory first
    try:
        if os.path.isdir(path):
            return (False, "is a directory")
    except Exception:
        pass

    # Windows cloud placeholder handling (optional module)
    if cloud_files_module is not None:
        return cloud_files_module.read_file_with_hydration(
            path,
            hydrate=hydrate,
            timeout_seconds=30,
        )

    # Fallback: direct file access
    try:
        with open(path, "rb") as f:
            if hydrate:
                chunk_size = 1024 * 1024  # 1 MiB
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
            else:
                f.read(1)
        return (True, None)
    except FileNotFoundError:
        return (False, "not found")
    except PermissionError as exc:
        return (False, f"PermissionError: {exc}")
    except OSError as exc:
        return (False, f"OSError: {exc}")
    except Exception as exc:
        return (False, f"{type(exc).__name__}: {exc}")


def should_moveto_local_file(local_path: str, original_blend_path: str) -> bool:
    """
    Return True only when it's safe to let rclone delete the local file after upload.

    We treat `moveto` as dangerous and only allow it when:
      - local_path is NOT the same as the user's original .blend path
      - local_path is located under the OS temp directory

    Otherwise use `copyto` (never deletes).
    """
    lp = str(local_path or "").strip()
    op = str(original_blend_path or "").strip()
    if not lp:
        return False

    # Never move the user's actual blend file.
    try:
        if op and samepath(lp, op):
            return False
    except Exception:
        return False

    # Only allow move when file is under temp dir.
    try:
        lp_abs = os.path.abspath(lp)
        tmp_abs = os.path.abspath(tempfile.gettempdir())
        common = os.path.commonpath([lp_abs, tmp_abs])
        if samepath(common, tmp_abs):
            return True
    except Exception:
        return False

    return False
