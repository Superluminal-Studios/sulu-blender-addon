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
from .utils.request_utils import (
    register_job_refresh_infrastructure,
    unregister_job_refresh_infrastructure,
)


# atexit handlers persist across addon reloads; register only once per process.
if "_atexit_registered" not in globals():
    _atexit_registered = False


def register():
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(Storage.save)
        _atexit_registered = True
    icons.register()
    properties.register()
    preferences.register()
    submit_operator.register()
    download_operator.register()
    panels.register()
    operators.register()
    register_job_refresh_infrastructure()
    

def unregister():
    unregister_job_refresh_infrastructure()
    operators.unregister()
    panels.unregister()
    download_operator.unregister()
    submit_operator.unregister()
    preferences.unregister()
    properties.unregister()
    icons.unregister()
