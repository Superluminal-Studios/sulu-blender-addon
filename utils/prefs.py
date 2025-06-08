import bpy
import importlib
from pathlib import Path
def get_prefs():
    addon_root = __package__.partition('.')[0]
    container  = bpy.context.preferences.addons.get(addon_root)
    return container and container.preferences

def get_addon_dir():
    root_mod_name = __package__.partition('.')[0]          # "sulu-addon"
    root_mod      = importlib.import_module(root_mod_name) # already loaded
    addon_dir = Path(root_mod.__file__).resolve().parent
    return addon_dir