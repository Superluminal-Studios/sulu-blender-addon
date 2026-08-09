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

# Increment when a corrected package must force Blender to reload an earlier
# build carrying the same public version metadata.
_PACKAGE_LAYOUT_VERSION = 2

import atexit
import sys


def _purge_cached_submodules() -> bool:
    """Discard child modules left behind by Blender's root-only reload."""
    module_prefix = f"{__name__}."
    cached_module_names = [
        module_name
        for module_name in sys.modules
        if module_name.startswith(module_prefix)
    ]
    if not cached_module_names:
        return False

    # Add-on updates can leave the previous refresh loop alive. Stop its
    # shared state before removing the module references, and replace its
    # bound exit callback with the callback from the newly imported Storage.
    cached_storage_module = sys.modules.get(f"{module_prefix}storage")
    cached_storage = getattr(cached_storage_module, "Storage", None)
    if cached_storage is not None:
        cached_storage.enable_job_thread = False
        cached_save = getattr(cached_storage, "save", None)
        if callable(cached_save):
            atexit.unregister(cached_save)

    # ``from . import child`` consults attributes retained in the reloaded
    # root module before sys.modules, so clear those direct child references
    # as well as the module cache entries.
    cached_child_names = {
        module_name[len(module_prefix):].partition(".")[0]
        for module_name in cached_module_names
    }
    for child_name in cached_child_names:
        globals().pop(child_name, None)

    # Parents may hold references to their children, so remove the deepest
    # modules first. The root package must remain for importlib.reload().
    for module_name in sorted(
        cached_module_names,
        key=lambda name: name.count("."),
        reverse=True,
    ):
        sys.modules.pop(module_name, None)
    return True


if _purge_cached_submodules():
    _atexit_registered = False


import bpy

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
