import platform
import shlex
import shutil
import subprocess
from typing import List

DETACHED_PROCESS = 0x00000008  # Only used on Windows


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
        quoted = shlex.join(cmd)

        # Plain Terminal.app: force a **new window**
        applescript_lines = [
            'tell application "Terminal"',
            'activate',
            f'do script "{quoted}" in (make new window)',
            'end tell',
        ]
        osa_cmd = ["osascript"]
        for line in applescript_lines:
            osa_cmd.extend(["-e", line])

        try:
            subprocess.Popen(osa_cmd)
        except Exception:
            subprocess.call(cmd)
        return

    # ---------------------------------------------------------------------- #
    # 3. Linux / BSD – try a series of terminal emulators in sensible order  #
    # ---------------------------------------------------------------------- #
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