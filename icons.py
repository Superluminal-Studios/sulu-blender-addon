# icons.py  (new helper, but you can inline this in __init__)
import os, bpy, bpy.utils.previews

preview_collections = {}          # global cache

def load_icons():
    pcoll = bpy.utils.previews.new()
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")

    pcoll.load("SULU", os.path.join(icons_dir, "logo.png"), 'IMAGE')

    pcoll.load("ERROR",   os.path.join(icons_dir, "error.png"),   'IMAGE')
    pcoll.load("FINISHED", os.path.join(icons_dir, "finished.png"), 'IMAGE')
    pcoll.load("PAUSED", os.path.join(icons_dir, "paused.png"), 'IMAGE')
    pcoll.load("RUNNING", os.path.join(icons_dir, "running.png"), 'IMAGE')
    pcoll.load("QUEUED", os.path.join(icons_dir, "queued.png"), 'IMAGE')

    preview_collections["main"] = pcoll
    return pcoll

def unload_icons():
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()
