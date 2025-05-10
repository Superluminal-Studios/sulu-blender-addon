import bpy, os, zipfile, addon_utils
from pathlib import Path

DEFAULT_ADDONS = [
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
]


def bundle_addons(zip_path):
    zip_path = Path(zip_path)
    zip_path.mkdir(parents=True, exist_ok=True)

    enabled_modules = [
        mod
        for mod in addon_utils.modules()
        if addon_utils.check(mod.__name__)[1] and mod.__name__ not in DEFAULT_ADDONS
    ]

    enabled_addons = []

    for mod in enabled_modules:
        addon_name = mod.__name__
        addon_enable_name = addon_name.split(".")[-1]
        enabled_addons.append(addon_enable_name)

        addon_root_path = Path(mod.__file__).parent
        addon_zip_file = zip_path / f"{addon_enable_name}.zip"

        with zipfile.ZipFile(addon_zip_file, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zipf:
            for root, _, files in os.walk(addon_root_path):
                rel_root = Path(root).relative_to(addon_root_path)  # path inside the add-on
                for file in files:
                    file_path = Path(root) / file
                    # Inside the ZIP:  addon_name / <rel_root> / file
                    archive_path = Path(addon_enable_name) / rel_root / file
                    zipf.write(file_path, archive_path)

    return enabled_addons
