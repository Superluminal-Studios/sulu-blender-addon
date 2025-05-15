from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
from typing import List, Dict
import os

# ─── stdlib ──────────────────────────────────────────────────────
import time
from pathlib import Path

# third-party
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ╭────────────────────  constants  ───────────────────────────╮
DETACHED_PROCESS = 0x00000008  # Only used on Windows
CLOUDFLARE_ACCOUNT_ID = "f09fa628d989ddd93cbe3bf7f7935591"
CLOUDFLARE_R2_DOMAIN = f"{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
COMMON_RCLONE_FLAGS: list[str] = [
    "--s3-provider", "Cloudflare",
    "--s3-env-auth",
    "--s3-region", "auto",
    "--s3-no-check-bucket",
]


def logger(msg: str) -> None:
    """logger a message to the console
    (and flush it immediately)."""
    print(msg, flush=True)


def open_folder(path: str) -> None:
    try:
        if platform.system() == "Windows":
            os.startfile(path)                       # noqa
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        logger(f"⚠️  Couldn’t open folder automatically: {e}")


def launch_in_terminal(cmd: List[str]) -> None:
    """
    Run *cmd* (a list of strings) in a brand-new terminal / console window.
    If that proves impossible, just execute the command in-process as the
    simplest last-ditch fallback.

    Parameters
    ----------
    cmd : list[str]
        The command to execute, identical to what you would pass to
        ``subprocess.Popen(cmd)``.
    """
    system = platform.system()

    # ---------------------------------------------------------------------- #
    # 1. Windows – use the user's default console host in a detached window  #
    # ---------------------------------------------------------------------- #
    if system == "Windows":
        try:
            subprocess.Popen(
                cmd,
                shell=True,
                close_fds=False,
                creationflags=DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        except Exception:
            # final fallback: synchronous call in the current console
            subprocess.call(cmd)
        return


    # ---------------------------------------------------------------------- #
    # 2. macOS – Terminal.app (or iTerm2 if you prefer)                      #
    # ---------------------------------------------------------------------- #
    if system == "Darwin":
        try:
            quoted = shlex.join(cmd)
            osa_line = f'tell app "Terminal" to do script "{quoted}"'
            subprocess.Popen(["osascript", "-e", osa_line])
            
        except Exception:
            # final fallback: synchronous call in the current console
            subprocess.call(cmd)
        return


    # ---------------------------------------------------------------------- #
    # 3. Linux / BSD – try a series of terminal emulators in sensible order  #
    # ---------------------------------------------------------------------- #
    if system in ("Linux", "FreeBSD"):
        quoted    = shlex.join(cmd)
        bash_wrap = ["bash", "-c", quoted]

        for term, prefix in (
            # 3.1 Mainstream defaults (GNOME / KDE / Xfce)
            ("gnome-terminal",     ["gnome-terminal", "--"]),
            ("konsole",            ["konsole", "-e"]),
            ("xfce4-terminal",     ["xfce4-terminal", "--command"]),

            # 3.2 Modern GPU / tiling / power-user favourites
            ("kitty",              ["kitty", "--hold"]),
            ("alacritty",          ["alacritty", "-e"]),
            ("wezterm",            ["wezterm", "start", "--"]),
            ("tilix",              ["tilix", "-e"]),
            ("terminator",         ["terminator", "-x"]),

            # 3.3 Other DE-specific or traditional emulators
            ("mate-terminal",      ["mate-terminal", "-e"]),
            ("lxterminal",         ["lxterminal", "-e"]),
            ("qterminal",          ["qterminal", "-e"]),
            ("deepin-terminal",    ["deepin-terminal", "-e"]),

            # 3.4 Lightweight / legacy tools
            ("urxvt",              ["urxvt", "-hold", "-e"]),
            ("xterm",              ["xterm", "-e"]),
            ("st",                 ["st", "-e"]),

            # 3.5 Debian/Ubuntu alternatives wrapper
            ("x-terminal-emulator",["x-terminal-emulator", "-e"]),
        ):
            if shutil.which(term):
                try:
                    subprocess.Popen([*prefix, *bash_wrap])
                except Exception:
                    continue  # try the next emulator
                else:
                    return

    # ---------------------------------------------------------------------- #
    # 4. Absolute last resort – synchronous execution in the current shell   #
    # ---------------------------------------------------------------------- #
    subprocess.call(cmd)


# ╭───────────────────  logging  ──────────────────────────────╮
def _log(msg: str) -> None:  # noqa: D401
    """Thin wrapper around ``print(..., flush=True)`` so callers can monkey-patch if needed."""
    print(msg, flush=True)


# ╭───────────────────  retrying  ─────────────────────────────╮
def requests_retry_session(
    *,
    retries: int = 5,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (500, 502, 503, 504, 522, 524),
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
    Return a :class:`requests.Session` pre-configured to retry automatically.

    The default settings favour reliability on flaky networks while remaining conservative
    enough not to hammer the server.
    """
    session = session or requests.Session()

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        allowed_methods=allowed_methods,
        status_forcelist=status_forcelist,
        backoff_factor=backoff_factor,
        raise_on_status=False,              # don’t raise until retries are exhausted
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# ╭───────────────────  helpers  ──────────────────────────────╮
def is_blend_saved(path: str | Path) -> None:
    """
    Block until the “*.blend” file isn’t still open (Blender writes ``<file>.blend@`` while saving).

    Displays a user-friendly message and gentle spinner-ish wait loop.
    """
    path = str(path)
    saving = True
    warned = False

    while saving:
        if not os.path.exists(path + "@"):
            saving = False
        else:
            if not warned:
                _log("⚠️  Warning: The primary blend is still being saved.\n")
                _log(
                    "This may be caused by Dropbox, Google Drive, OneDrive, "
                    "or similar software accessing the file."
                )
                warned = True
            time.sleep(0.25)
    if warned:
        _log("✅  File is saved. Proceeding with submission.")


def _short(p: str) -> str:
    """Return just the basename unless the string already looks like an S3 path."""
    return p if p.startswith(":s3:") else Path(p).name


def _build_base(
    rclone_bin: Path,
    endpoint: str,
    s3: Dict[str, str],
) -> List[str]:
    """Construct the base *rclone* CLI invocation shared by all commands."""
    return [
        str(rclone_bin),
        "--s3-endpoint",
        endpoint,
        "--s3-access-key-id",
        s3["access_key_id"],
        "--s3-secret-access-key",
        s3["secret_access_key"],
        "--s3-session-token",
        s3["session_token"],
        "--s3-region",
        "auto",
        *COMMON_RCLONE_FLAGS,
    ]