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
import sys
import os

# -------------------------------------------------------------------
#  Adjust PYTHONPATH to include vendored dependencies
# -------------------------------------------------------------------
addon_dir = os.path.dirname(__file__)
vendor_dir = os.path.join(addon_dir, "vendor", "site-packages")
if vendor_dir not in sys.path:
    sys.path.append(vendor_dir)

# -------------------------------------------------------------------
#  Internal Imports
# -------------------------------------------------------------------
from . import preferences
from . import properties
from . import submit_job
from . import panels
from . import operators
# -------------------------------------------------------------------
#  Registration
# -------------------------------------------------------------------
def register():
    preferences.register()
    properties.register()
    submit_job.register()
    panels.register()
    operators.register()


def unregister():
    operators.unregister()
    panels.unregister()
    submit_job.unregister()
    properties.unregister()
    preferences.unregister()


if __name__ == "__main__":
    register()
