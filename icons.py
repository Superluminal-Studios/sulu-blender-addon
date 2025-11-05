import bpy.utils.previews

icon_values = {
    "ERROR":    "RESTRICT_RENDER_ON",
    "FINISHED": "CHECKBOX_HLT",
    "PAUSED":   "PAUSE",
    "RUNNING":  "DISCLOSURE_TRI_RIGHT",
    "QUEUED":   "RECOVER_LAST"
}

# class CustomIcons:
#     icons = {}

#     @staticmethod
#     def status_icons():
#         return {
#         "queued":   CustomIcons.icons["main"]["QUEUED"].icon_id,
#         "running":  CustomIcons.icons["main"]["RUNNING"].icon_id,
#         "finished": CustomIcons.icons["main"]["FINISHED"].icon_id,
#         "error":    CustomIcons.icons["main"]["ERROR"].icon_id,
#         "paused":   CustomIcons.icons["main"]["PAUSED"].icon_id
#         }
    
#     def get_icons(icon):
#         return CustomIcons.icons["main"].get(icon)

#     @staticmethod
#     @persistent
#     def load_icons(dummy=None, context=None):
#         print("Loading icons...")
#         if "main" in CustomIcons.icons:
#             bpy.utils.previews.remove(CustomIcons.icons["main"])

#         CustomIcons.icons = {}
#         pcoll = bpy.utils.previews.new()
#         icons_dir = os.path.join(os.path.dirname(__file__), "icons")

#         pcoll.load("SULU", os.path.join(icons_dir, "logo.png"), 'IMAGE')
#         pcoll.load("ERROR",   os.path.join(icons_dir, "error.png"), 'IMAGE')
#         pcoll.load("FINISHED", os.path.join(icons_dir, "finished.png"), 'IMAGE')
#         pcoll.load("PAUSED", os.path.join(icons_dir, "paused.png"), 'IMAGE')
#         pcoll.load("RUNNING", os.path.join(icons_dir, "running.png"), 'IMAGE')
#         pcoll.load("QUEUED", os.path.join(icons_dir, "queued.png"), 'IMAGE')
#         CustomIcons.icons["main"] = pcoll
#         #update previews
#         return pcoll

#     @staticmethod
#     def unload_icons():
#         for pcoll in CustomIcons.icons.values():
#             bpy.utils.previews.remove(pcoll)
#         CustomIcons.icons.clear()