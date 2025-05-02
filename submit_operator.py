from __future__ import annotations

# ─────────────────────────  Standard library  ──────────────────────────
import json
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List
from .check_file_outputs import gather_render_outputs
import bpy  # type: ignore


# ╭─────────────────────  launch_in_terminal  ─────────────────────╮
def launch_in_terminal(cmd):
    """
    Run *cmd* (list[str]) in a brand-new terminal / console window and
    keep that window open until the user presses ENTER.
    """
    sysstr = platform.system()
    quoted = shlex.join(cmd)

    # ─── Windows ──────────────────────────────────────────────
    if sysstr == "Windows":
        #
        # MAKE A STRING – shell=True expects a string, not a list.
        #
        # /k  → keep the console open
        # & pause → show the usual "Press any key to continue…"
        #
        cmdline = f'cmd /k {quoted} & echo. & pause'
        subprocess.Popen(
            cmdline,
            shell=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        return

    # Message used on macOS + Linux
    wait_snippet = 'echo; read -p "Press ENTER to close..."'

    # ─── macOS ────────────────────────────────────────────────
    if sysstr == "Darwin":
        bash_wrap = f"{quoted}; {wait_snippet}"
        subprocess.Popen([
            "osascript", "-e",
            f'tell application "Terminal" to do script "{bash_wrap}"'
        ])
        return

    # ─── Linux / BSD ─────────────────────────────────────────
    bash_wrap = ["bash", "-c", f"{quoted}; {wait_snippet}"]

    for term, prefix in (
        ("konsole",          ["konsole", "-e"]),
        ("xterm",            ["xterm", "-e"]),
        ("xfce4-terminal",   ["xfce4-terminal", "--command"]),
        ("gnome-terminal",   ["gnome-terminal", "--"]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e"]),
    ):
        if shutil.which(term):
            subprocess.Popen([*prefix, *bash_wrap])
            return

    # Fallback: detached background (window will still close after ENTER)
    subprocess.Popen(bash_wrap)


# ───────────────  Blender operator  ────────────────
class SUPERLUMINAL_OT_SubmitJob(bpy.types.Operator):
    """Submit the current .blend file to the Superluminal Render Farm
       by spawning an external worker process.
    """

    bl_idname = "superluminal.submit_job"
    bl_label = "Submit Job to Superluminal (external)"

    def execute(self, context):  # noqa: C901
        scene = context.scene
        props = scene.superluminal_settings
        prefs = context.preferences.addons[__package__].preferences

        if not bpy.data.filepath:
            self.report({"ERROR"}, "Please save your .blend file first.")
            return {"CANCELLED"}
        
        outputs = gather_render_outputs(scene)["outputs"]
        layers = outputs[0]["layers"]
        print(layers)
        

        # Gather parameters that ONLY Blender knows
        job_id = uuid.uuid4()
        handoff: Dict[str, object] = {
            "addon_dir": str(Path(__file__).resolve().parent),
            "job_id": str(job_id),
            "blend_path": bpy.data.filepath,
            "use_project_upload": bool(props.use_upload_project),
            "project_path": str(Path(bpy.path.abspath(props.project_path)).resolve()),
            "job_name": (
                Path(bpy.data.filepath).stem
                if props.use_file_name
                else props.job_name
            ),
            "render_passes": layers,
            "render_format": (
                scene.render.image_settings.file_format
                if props.use_scene_render_format
                else props.render_format
            ),
            "start_frame": (
                scene.frame_start if props.use_scene_frame_range else props.frame_start
            ),
            "end_frame": (
                scene.frame_end if props.use_scene_frame_range else props.frame_end
            ),
            "render_engine": scene.render.engine.upper(),
            "blender_version": props.blender_version,
            # PocketBase / auth
            "pocketbase_url": prefs.pocketbase_url,
            "user_token": prefs.user_token,
            "selected_project_id": prefs.project_list,
        }

        tmp_json = Path(tempfile.gettempdir()) / f"superluminal_{job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        worker = Path(__file__).with_name("submit_worker.py")
        launch_in_terminal([sys.executable, "-u", str(worker), str(tmp_json)])

        self.report({"INFO"}, "Submission started in external window.")
        return {"FINISHED"}


# ───────────────  Blender hooks  ────────────────
classes = (SUPERLUMINAL_OT_SubmitJob,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
