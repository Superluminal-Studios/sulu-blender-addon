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

from .storage import Storage
Storage.load()

from . import constants
from . import icons
from . import properties
from . import preferences
from .transfers.submit import submit_operator
from .transfers.download import download_operator
from . import panels
from . import operators
from .utils.request_utils import stop_live_job_updates


def get_prefs():
    addon_name = __name__
    prefs_container = bpy.context.preferences.addons.get(addon_name)
    return prefs_container and prefs_container.preferences

def register():
    atexit.register(Storage.save)
    icons.register()
    properties.register()
    preferences.register()
    submit_operator.register()
    download_operator.register()
    panels.register()
    operators.register()
    

def unregister():
    stop_live_job_updates()
    operators.unregister()
    panels.unregister()
    download_operator.unregister()
    submit_operator.unregister()
    preferences.unregister()
    properties.unregister()
    icons.unregister()


if __name__ == "__main__":

    register()
