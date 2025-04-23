bl_info = {
    "name": "Superluminal Render Farm",
    "author": "Superluminal",
    "version": (1, 0),
    "blender": (4, 4, 0),
    "location": "Properties > Render > Superluminal",
    "description": "Submit render jobs to Superluminal Render Farm",
    "warning": "",
    "category": "Render",
}

import bpy

# -------------------------------------------------------------------
#  Internal Imports
# -------------------------------------------------------------------
from . import preferences
from . import properties
from . import submit_operator
from . import download_operator
from . import panels
from . import operators
# -------------------------------------------------------------------
#  Registration
# -------------------------------------------------------------------
def register():
    preferences.register()
    properties.register()
    submit_operator.register()
    download_operator.register()
    panels.register()
    operators.register()


def unregister():
    operators.unregister()
    panels.unregister()
    submit_operator.unregister()
    download_operator.unregister()
    properties.unregister()
    preferences.unregister()


if __name__ == "__main__":
    register()
