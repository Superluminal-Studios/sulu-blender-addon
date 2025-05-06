import subprocess
import platform
import os
DETACHED_PROCESS = 0x00000008

def launch_in_terminal(cmd):
    """
    Run *cmd* (list[str]) in a brand-new terminal / console and keep that
    window open when the command finishes.
    """
    if platform.system() == "Windows":
        subprocess.Popen(
            [*cmd],
            close_fds=True,
            shell=True,
            creationflags=DETACHED_PROCESS)
        return
        
    elif platform.system() == "Linux":
        subprocess.Popen(
            ["/bin/bash", "-c", *cmd],
            close_fds=True,
            shell=True,
            start_new_session=True)
        return