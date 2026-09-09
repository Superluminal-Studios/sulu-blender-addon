try:
    from .environment import profile_for_environment
except ImportError:  # pragma: no cover - standalone developer utilities
    from environment import profile_for_environment


# Compatibility aliases for external developer utilities.  Runtime paths use
# the selected fixed environment profile instead of importing these constants.
_PRODUCTION_PROFILE = profile_for_environment("production")
POCKETBASE_URL = _PRODUCTION_PROFILE.api_url
FARM_IP = _PRODUCTION_PROFILE.farm_url


DEFAULT_ADDONS = {
    "io_anim_bvh",
    "bl_pkg",
    "copy_global_transform",
    "cycles",
    "io_scene_fbx",
    "io_scene_gltf2",
    "hydra_storm",
    "ui_translate",
    "node_wrangler",
    "pose_library",
    "rigify",
    "io_curve_svg",
    "io_mesh_uv_layout",
    "viewport_vr_preview",
    "sulu-addon",
    "sulu-blender-addon",
}
