import subprocess

def launch_in_terminal(cmd):
    """
    Run *cmd* (list[str]) in a brand-new terminal / console and keep that
    window open when the command finishes.
    """
    DETACHED_PROCESS = 0x00000008

    subprocess.Popen(
        [*cmd],
        close_fds=True,
        shell=True,
        creationflags=DETACHED_PROCESS)
    return
    