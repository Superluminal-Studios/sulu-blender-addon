from __future__ import annotations
import bpy

class SUPERLUMINAL_PT_NewPanel(bpy.types.Panel):
    bl_idname = "SUPERLUMINAL_PT_NewPanel"
    bl_label = "New Panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    bl_parent_id = "SUPERLUMINAL_PT_RenderPanel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        props = context.scene.superluminal_settings

        # Never do network calls here.
        layout.label(text="Hello from the new panel")

classes = (SUPERLUMINAL_PT_NewPanel,)

def register():
    for c in classes:
        bpy.utils.register_class(c)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
