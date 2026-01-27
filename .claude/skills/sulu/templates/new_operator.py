from __future__ import annotations
import bpy

class SUPERLUMINAL_OT_NewThing(bpy.types.Operator):
    """One-line description shown in Blender UI tooltips."""
    bl_idname = "superluminal.new_thing"
    bl_label = "New Thing"

    # Example: props
    # name: bpy.props.StringProperty(name="Name", default="")

    @classmethod
    def poll(cls, context):
        # Keep this fast; no network or heavy scans.
        return True

    def execute(self, context):
        try:
            # Do quick Blender-side work only.
            # For heavy tasks, write a handoff JSON and spawn a worker process.
            self.report({"INFO"}, "Did the thing.")
            return {"FINISHED"}
        except Exception as exc:
            # Prefer your centralized reporter:
            from ..utils.logging import report_exception
            return report_exception(self, exc, "NewThing failed")

classes = (SUPERLUMINAL_OT_NewThing,)

def register():
    for c in classes:
        bpy.utils.register_class(c)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
