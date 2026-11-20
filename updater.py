"""Render-panel update notification and explicit save/restart confirmation."""

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import bpy
import requests

from .build_info import BUILD_CHANNEL, BUILD_ENVIRONMENT
from .storage import Storage
from . import update_install


state = {"phase": "idle", "message": "", "release": None}
_events = queue.SimpleQueue()
_enabled = False
_next_check = 0.0
_helper = None
_quit_deadline = 0.0
_completed_attempt = None


def _version():
    return tuple(sys.modules[__package__].bl_info["version"])


def _status_path():
    return Path(bpy.utils.user_resource("CONFIG", path="sulu-updates", create=True)) / "status.json"


def _background(operation, success):
    events = _events
    def run():
        try:
            with requests.Session() as session:
                session.headers.update({"User-Agent": "Sulu-Blender-Addon/updater", "Accept": "application/vnd.github+json"})
                value = operation(session)
            events.put((success, value))
        except Exception as error:
            events.put(("error", str(error)))
    threading.Thread(target=run, name="sulu-addon-update", daemon=True).start()


def check_for_update():
    global _next_check
    current = _version()
    state.update(phase="checking", message="Checking for updates…")
    _next_check = time.monotonic() + 6 * 60 * 60
    _background(lambda session: update_install.latest_release(session, current), "checked")


def _tick():
    global _helper, _completed_attempt
    if not _enabled:
        return None
    if _completed_attempt is not None:
        attempt = _completed_attempt
        _completed_attempt = None
        # Only clean the sibling directory created for this installed update.
        addon = Path(__file__).resolve().parent
        if (attempt.parent.resolve() != addon.parent or attempt.is_symlink()
                or not attempt.name.startswith(".sulu-update-")):
            state.update(phase="error", message="Update completed, but the cleanup directory is invalid")
        else:
            def cleanup(_session):
                shutil.rmtree(attempt)
            _background(cleanup, "cleaned")
    while not _events.empty():
        event, value = _events.get_nowait()
        if event == "checked":
            state.update(phase="available" if value else "current", release=value, message="")
        elif event == "prepared":
            state.update(phase="ready", stage=value, message="Update downloaded and verified")
        elif event == "error":
            state.update(phase="error", message=value)
    if state["phase"] == "restarting":
        ready = Path(state["attempt"], "ready.json")
        if _helper.poll() is not None:
            state.update(phase="error", message="Installer stopped. Blender remains open; see the update log.")
        elif ready.exists():
            state["phase"] = "quitting"
            result = bpy.ops.wm.quit_blender("EXEC_DEFAULT")
            if "FINISHED" not in result:
                _helper.terminate()
                state.update(phase="error", message="Blender did not close; update cancelled")
        elif time.monotonic() > _quit_deadline:
            _helper.terminate()
            state.update(phase="error", message="Installer did not become ready; Blender remains open")
    if BUILD_CHANNEL == "release" and state["phase"] in {"idle", "current", "available"} and time.monotonic() >= _next_check:
        check_for_update()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()
    return 1.0


def draw_notice(layout):
    phase = state["phase"]
    if phase in {"idle", "current"}:
        return
    box = layout.box()
    if phase == "available":
        release = ".".join(map(str, state["release"]["version"]))
        box.label(text=f"Add-on update available: {release}", icon="INFO")
        box.label(text=f"Installed: {'.'.join(map(str, _version()))}")
        box.operator("superluminal.download_update", text="Update add-on", icon="IMPORT")
    elif phase == "ready":
        box.label(text=state["message"], icon="CHECKMARK")
        box.operator("superluminal.restart_update", text="Restart Blender to update", icon="FILE_REFRESH")
    elif phase == "error":
        box.alert = True
        box.label(text="Add-on update needs attention", icon="ERROR")
        box.label(text=state["message"])
        box.operator("superluminal.check_update", text="Check again", icon="FILE_REFRESH")
    else:
        box.label(text=state["message"] or "Restarting Blender…", icon="TIME")


class SUPERLUMINAL_OT_CheckUpdate(bpy.types.Operator):
    bl_idname = "superluminal.check_update"
    bl_label = "Check for add-on updates"

    def execute(self, context):
        if state["phase"] in {"downloading", "restarting", "quitting"}:
            return {"CANCELLED"}
        check_for_update()
        return {"FINISHED"}


class SUPERLUMINAL_OT_DownloadUpdate(bpy.types.Operator):
    bl_idname = "superluminal.download_update"
    bl_label = "Download add-on update"
    bl_description = "Download and verify the latest release; Blender stays open until you confirm a restart"

    def execute(self, context):
        if state["phase"] != "available":
            return {"CANCELLED"}
        addon = Path(__file__).resolve().parent
        if addon.name != "SuperluminalRender":
            self.report({"ERROR"}, "Automatic updates require an installed SuperluminalRender release")
            return {"CANCELLED"}
        try:
            attempt = tempfile.mkdtemp(prefix=".sulu-update-", dir=addon.parent)
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        release = dict(state["release"])
        blender_version = tuple(bpy.app.version)
        state.update(phase="downloading", message="Downloading and verifying update…", attempt=attempt)
        _background(lambda session: update_install.prepare_release(
            session, release, attempt, blender_version, BUILD_ENVIRONMENT), "prepared")
        return {"FINISHED"}


class SUPERLUMINAL_OT_RestartUpdate(bpy.types.Operator):
    bl_idname = "superluminal.restart_update"
    bl_label = "Update and restart Blender"
    bl_description = "Close Blender, install the verified update and reopen the same blend file"

    save_choice: bpy.props.EnumProperty(
        name="Before restarting", items=[
            ("SAVE", "Save changes", "Save this blend file before restarting"),
            ("DISCARD", "Discard unsaved changes", "Reopen the last saved file; unsaved changes will be lost"),
        ], default="SAVE")
    filepath: bpy.props.StringProperty(name="Save file", subtype="FILE_PATH")

    def invoke(self, context, event):
        if state["phase"] != "ready":
            return {"CANCELLED"}
        self.save_choice = "SAVE"
        self.filepath = bpy.data.filepath
        return context.window_manager.invoke_props_dialog(self, width=480, confirm_text="Update and restart")

    def draw(self, context):
        layout = self.layout
        layout.label(text="Blender must close to install this update.", icon="INFO")
        layout.label(text="It will reopen with the same blend file.")
        layout.label(text="Finish local renders and transfers before continuing.")
        layout.prop(self, "save_choice", expand=True)
        if self.save_choice == "SAVE" and not bpy.data.filepath:
            layout.prop(self, "filepath")
        if self.save_choice == "DISCARD":
            warning = layout.row()
            warning.alert = True
            warning.label(text="Unsaved changes will be lost.", icon="ERROR")
        layout.label(text="Cancel keeps Blender open.")

    def execute(self, context):
        global _helper, _quit_deadline
        if state["phase"] != "ready":
            return {"CANCELLED"}
        if bpy.app.is_job_running("RENDER"):
            self.report({"ERROR"}, "Finish or cancel the local render before updating")
            return {"CANCELLED"}
        try:
            blend_file = bpy.data.filepath
            if self.save_choice == "SAVE":
                target = blend_file or bpy.path.abspath(self.filepath)
                if not target or not Path(target).is_absolute() or Path(target).suffix.lower() != ".blend":
                    raise ValueError("Choose an absolute .blend file path before saving")
                if not blend_file and Path(target).exists():
                    raise ValueError("That file exists. Save As in Blender first to confirm overwriting it")
                if "FINISHED" not in bpy.ops.wm.save_as_mainfile(filepath=target):
                    raise RuntimeError("Saving failed; Blender will remain open")
                blend_file = bpy.data.filepath
            Storage.save()
            if blend_file and not Path(blend_file).is_file():
                raise ValueError("The current blend file is missing; save it before updating")
            if "FINISHED" not in bpy.ops.wm.save_userpref():
                raise RuntimeError("Could not save Blender preferences")
            attempt = Path(state["attempt"])
            helper = attempt / "update_install.py"
            shutil.copyfile(Path(update_install.__file__), helper)
            plan = dict(addon=str(Path(__file__).resolve().parent), attempt=str(attempt),
                        stage=state["stage"], blender=bpy.app.binary_path,
                        blend_file=blend_file, parent_pid=os.getpid(),
                        version=state["release"]["version"], status=str(_status_path()))
            plan_path = attempt / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            (attempt / "ready.json").unlink(missing_ok=True)
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            with (attempt / "update.log").open("w", encoding="utf-8") as log:
                _helper = subprocess.Popen([sys.executable, "-I", str(helper), str(plan_path)],
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
            _quit_deadline = time.monotonic() + 15
            state.update(phase="restarting", message="Preparing to restart Blender…")
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


_classes = (SUPERLUMINAL_OT_CheckUpdate, SUPERLUMINAL_OT_DownloadUpdate, SUPERLUMINAL_OT_RestartUpdate)


def register():
    global _enabled, _events, _next_check, _completed_attempt
    _enabled = True
    _events = queue.SimpleQueue()
    _next_check = 0.0
    for cls in _classes:
        bpy.utils.register_class(cls)
    status_path = _status_path()
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status["state"] == "installed":
            if tuple(status["version"]) != _version():
                state.update(phase="error", message="Installed update version does not match; restore the previous add-on from the update folder")
            else:
                update_install.write_status(status_path, state="complete", version=list(_version()),
                                            message="Update completed", attempt=status["attempt"])
                _completed_attempt = Path(status["attempt"])
        elif status["state"] == "error":
            state.update(phase="error", message=status["message"])
    bpy.app.timers.register(_tick, first_interval=2.0, persistent=True)


def unregister():
    global _enabled
    _enabled = False
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
