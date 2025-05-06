from __future__ import annotations


import json
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import bpy  

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
    
    quoted = shlex.join(cmd)
    wait = 'echo; read -p "Press ENTER to close..."'
    bash_wrap = ["bash", "-c", f"{quoted}; {wait}"]

    for term, prefix in (
        ("konsole",            ["konsole", "-e"]),
        ("xterm",              ["xterm", "-e"]),
        ("xfce4-terminal",     ["xfce4-terminal", "--command"]),
        ("gnome-terminal",     ["gnome-terminal", "--"]),
        ("x-terminal-emulator",["x-terminal-emulator", "-e"]),
    ):
        if shutil.which(term):
            subprocess.Popen([*prefix, *bash_wrap])
            return

    subprocess.Popen(bash_wrap)



class SUPERLUMINAL_OT_DownloadJob(bpy.types.Operator):
    """Download frames from the selected job
       by spawning an external worker process.
    """

    bl_idname = "superluminal.download_job"
    bl_label = "Download Job Frames"

    def execute(self, context):  
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__package__].preferences
        job_id = None
        
        handoff = {
            "download_path": "/tmp/download_test/",
            "selected_project_id": prefs.project_list,
            "job_id": None,
            "pocketbase_url": prefs.pocketbase_url,
            "user_token": prefs.user_token,
        }


        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_download_{job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        worker = Path(__file__).with_name("download_worker.py")
        launch_in_terminal([sys.executable, "-u", str(worker), str(tmp_json)])

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}



classes = (SUPERLUMINAL_OT_DownloadJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
