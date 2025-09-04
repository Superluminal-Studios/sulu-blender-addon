# utils/worker_utils.py
from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
from typing import List, Dict
import os
import time
from pathlib import Path

# third-party
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# constants
# Windows process creation flags
DETACHED_PROCESS          = 0x00000008  # detached (no console)
CREATE_NEW_CONSOLE        = 0x00000010  # force a new console window
CREATE_NEW_PROCESS_GROUP  = 0x00000200  # allow Ctrl+C to target child

CLOUDFLARE_ACCOUNT_ID  = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN   = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Common flags we want on *every* rclone call that uses R2
COMMON_RCLONE_FLAGS: list[str] = [
    "--s3-provider", "Cloudflare",
    "--s3-env-auth",           # allow env creds if present
    "--s3-region", "auto",
    "--s3-no-check-bucket",
]


def clear_console():
    """
    Clears the console screen based on the operating system.
    """
    if os.name == 'nt':  # For Windows
        os.system('cls')
    else:  # For macOS and Linux
        os.system('clear')
       
        
# user-facing logging
def logger(msg: str) -> None:
    """
    Simple user-facing logger; prints a single message and flushes immediately.
    Intentionally accepts just one string (callers pass already-formatted text).
    """
    print(str(msg), flush=True)


def _log(msg: str) -> None:
    """Thin wrapper around print(..., flush=True); kept for backward-compat."""
    print(str(msg), flush=True)


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


def open_folder(path: str) -> None:
    """
    Best-effort attempt to open a folder in the OS file manager.
    Never raises; logs a friendly message on failure.
    """
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
                logger(f"ℹ️  To open the folder manually, browse to: {path}")
    except Exception as e:
        logger(f"⚠️  Couldn’t open folder automatically: {e}")


# terminal launching
def launch_in_terminal(cmd: List[str]) -> None:
    """
    Run *cmd* (a list of strings) in a brand-new terminal / console window.
    If that isn’t possible, execute the command synchronously as a last resort.

    Parameters
    ----------
    cmd : list[str]
        The command to execute, identical to what you would pass to Popen(cmd).
    """
    system = platform.system()

    # 0) WSL hint: if we’re in WSL, treat as Linux
    if "microsoft" in platform.release().lower():
        system = "Linux"

    # 1) Windows — prefer `start` to guarantee a visible console window.
    if system == "Windows":
        try:
            quoted = " ".join(shlex.quote(c) for c in cmd)
            # start "" <command> opens a new console window
            subprocess.Popen(f'start "" {quoted}', shell=True)
            return
        except Exception:
            pass
        try:
            # Fallback: create a new console programmatically
            subprocess.Popen(
                cmd,
                creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP
            )
            return
        except Exception:
            # Final fallback: run in current console (blocking)
            subprocess.call(cmd)
            return

    # 2) macOS — open Terminal.app, clear scrollback+screen, then run the worker
    if system == "Darwin":
        try:
            # Build the worker command as it would be typed in a shell
            worker = shlex.join(cmd)

            # ANSI prelude: clear scrollback (3J), move cursor home (H), clear screen (2J), then clear for good measure.
            # NOTE: do NOT escape backslashes globally; we need '\e' to survive to printf.
            #prelude = "printf '\\e[3J\\e[H\\e[2J'; clear; "
            #script  = prelude + worker
            script = worker

            # Escape only the double quotes for AppleScript string
            script_osas = script.replace('"', '\\"')

            # Activate Terminal, then run our script in a fresh window/tab
            subprocess.Popen([
                "osascript",
                "-e", 'tell application "Terminal" to activate',
                "-e", f'tell application "Terminal" to do script "{script_osas}"',
            ])
            return
        except Exception:
            # Final fallback: synchronous call in the current console
            subprocess.call(cmd)
            return

    # 3) Linux / BSD — try common emulators (in a reasonable order)
    if system in ("Linux", "FreeBSD"):
        quoted    = shlex.join(cmd)
        bash_wrap = ["bash", "-lc", quoted]  # preserves PATH, allows shell features

        for term, prefix in (
            # Mainstream defaults (GNOME / KDE / Xfce)
            ("gnome-terminal",      ["gnome-terminal", "--"]),
            ("konsole",             ["konsole", "-e"]),
            ("xfce4-terminal",      ["xfce4-terminal", "--command"]),

            # Modern / GPU-accelerated / tiling
            ("kitty",               ["kitty", "--hold"]),
            ("alacritty",           ["alacritty", "-e"]),
            ("wezterm",             ["wezterm", "start", "--"]),
            ("tilix",               ["tilix", "-e"]),
            ("terminator",          ["terminator", "-x"]),

            # Other DE-specific or traditional
            ("mate-terminal",       ["mate-terminal", "-e"]),
            ("lxterminal",          ["lxterminal", "-e"]),
            ("qterminal",           ["qterminal", "-e"]),
            ("deepin-terminal",     ["deepin-terminal", "-e"]),

            # Lightweight / legacy
            ("urxvt",               ["urxvt", "-hold", "-e"]),
            ("xterm",               ["xterm", "-e"]),
            ("st",                  ["st", "-e"]),

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
        "HEAD", "GET", "OPTIONS", "POST", "PUT", "PATCH", "DELETE",
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
def is_blend_saved(path: str | Path) -> None:
    """
    Block until a “*.blend” file is finished saving.

    Blender typically writes a sentinel `<file>.blend@` while saving.
    We wait for the sentinel to disappear *and* for the file size to
    remain stable for ~0.5s as an extra safety check (covers network drives).
    """
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
                    _log("✅  File is saved. Proceeding.")
                return
        else:
            # Still saving; print a one-time friendly note
            if not warned:
                _log("⏳  Waiting for Blender to finish saving the .blend…")
                _log("    If this takes a while, background sync apps (Dropbox/Drive) may be scanning the file.")
                warned = True

        time.sleep(0.25)


# tiny compatibility helpers
def _short(p: str) -> str:
    """Return just the basename unless the string already looks like an S3 path."""
    return p if str(p).startswith(":s3:") else Path(str(p)).name


#rclone base command
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
        "--s3-endpoint", endpoint,
        "--s3-access-key-id", access_key,
        "--s3-secret-access-key", secret_key,
    ]

    # Only include session token if provided; some providers omit it.
    if session_token:
        base.extend(["--s3-session-token", session_token])

    # Add our shared flags (provider, region, etc.)
    base.extend(COMMON_RCLONE_FLAGS)
    return base
