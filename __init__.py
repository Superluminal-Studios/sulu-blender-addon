bl_info = {
    "name": "Superluminal Render Farm",
    "author": "Superluminal",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "Properties > Render > Superluminal",
    "description": "Submit render jobs to Superluminal Render Farm",
    "warning": "",
    "category": "Render",
}

import bpy
import atexit

# -------------------------------------------------------------------
#  Internal Imports
# -------------------------------------------------------------------
from .storage import Storage
Storage.load()

from . import icons
icons.load_icons()

from . import constants
from . import properties            # <-- must register BEFORE preferences (WM props)
from . import preferences           # prefs UI reads WM props
from .transfers.submit import submit_operator
from .transfers.download import download_operator
from . import panels
from . import operators


def get_prefs():
    addon_name = __name__
    prefs_container = bpy.context.preferences.addons.get(addon_name)
    return prefs_container and prefs_container.preferences

# -------------------------------------------------------------------
#  Registration
# -------------------------------------------------------------------
def register():
    atexit.register(Storage.save)

    # Ensure WM props are registered before any UI that touches them
    properties.register()
    preferences.register()
    submit_operator.register()
    download_operator.register()
    panels.register()
    operators.register()

def unregister():
    operators.unregister()
    panels.unregister()
    download_operator.unregister()
    submit_operator.unregister()
    preferences.unregister()
    properties.unregister()
    icons.unload_icons()


if __name__ == "__main__":
    register()
