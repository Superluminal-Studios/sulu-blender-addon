import bpy

# -------------------------------------------------------------------
#  Global storage for dynamic project list
# -------------------------------------------------------------------
g_project_items = [("NONE", "No projects", "No projects")]


def get_project_list_items(self, context):
    """Callback for the EnumProperty to display dynamic project items."""
    global g_project_items
    return g_project_items


class SuperluminalAddonPreferences(bpy.types.AddonPreferences):
    # IMPORTANT: This must match the folder/addon name for lookups
    bl_idname = __package__

    pocketbase_url: bpy.props.StringProperty(
        name="PocketBase URL",
        description="Base URL for PocketBase",
        default="https://api.superlumin.al",
    )

    username: bpy.props.StringProperty(
        name="Username",
        description="PocketBase username",
        default="",
    )

    password: bpy.props.StringProperty(
        name="Password",
        description="PocketBase password",
        default="",
        subtype="PASSWORD",
    )

    user_token: bpy.props.StringProperty(
        name="User Token",
        description="Authenticated token stored after successful login",
        default="",
    )

    project_list: bpy.props.EnumProperty(
        name="Project",
        description="List of projects from PocketBase",
        items=get_project_list_items,
        default=0,  # index-based default
    )

    def draw(self, context):
        layout = self.layout
        # layout.prop(self, "pocketbase_url")
        layout.prop(self, "username")
        layout.prop(self, "password")

        row = layout.row()
        row.operator("superluminal.login", text="Log In")

        layout.separator()

        row = layout.row()
        row.operator("superluminal.fetch_projects", text="Fetch Projects")

        layout.prop(self, "project_list")


def register():
    bpy.utils.register_class(SuperluminalAddonPreferences)


def unregister():
    bpy.utils.unregister_class(SuperluminalAddonPreferences)
