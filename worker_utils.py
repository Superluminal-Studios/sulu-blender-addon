import platform
import shlex
import shutil
import subprocess

def launch_in_terminal(cmd):
    """
    Run *cmd* (list[str]) in a brand-new terminal / console and keep that
    window open when the command finishes.
    """

    system = platform.system()
    DETACHED_PROCESS = 0x00000008
    if system == "Windows":
        subprocess.Popen(
            [*cmd],
            close_fds=False,
            shell=True,
            creationflags=DETACHED_PROCESS,

        )
        return

    if system == "Darwin":
        quoted = shlex.join(cmd)
        wait = 'echo; read -p "Press ENTER to close..."'
        subprocess.Popen([
            "osascript", "-e",
            f'tell application "Terminal" to do script "{quoted}; {wait}"'
        ])
        return
    
    if system == "Linux":
        subprocess.Popen(
            [*cmd],
            close_fds=False,
            shell=True,
            creationflags=DETACHED_PROCESS,

        )
        return
    
    # quoted = shlex.join(cmd)
    # wait = 'echo; read -p "Press ENTER to close..."'
    # bash_wrap = ["bash", "-c", f"{quoted}; {wait}"]

    # for term, prefix in (
    #     ("konsole",            ["konsole", "-e"]),
    #     ("xterm",              ["xterm", "-e"]),
    #     ("xfce4-terminal",     ["xfce4-terminal", "--command"]),
    #     ("gnome-terminal",     ["gnome-terminal", "--"]),
    #     ("x-terminal-emulator",["x-terminal-emulator", "-e"]),

        
    # ):
    #     if shutil.which(term):
    #         subprocess.Popen([*prefix, *bash_wrap])
    #         return

    #subprocess.Popen(bash_wrap)