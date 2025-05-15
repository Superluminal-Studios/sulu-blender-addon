import bpy, os, zipfile, addon_utils
from pathlib import Path
from .constants import DEFAULT_ADDONS

def bundle_addons(zip_path, addons_to_send=None):
    """
    Pack enabled add-ons listed in *addons_to_send* (and **not** in DEFAULT_ADDONS)
    into individual <addon>.zip files under *zip_path*.

    Returns the list of add-ons actually packed.
    """
    # Fall back to the runtime list from the UI
    if addons_to_send is None:
        from .panels import addons_to_send as _ui_list  # noqa: F401  (relative import)
        addons_to_send = list(_ui_list)

    wanted = {name.strip() for name in addons_to_send if name.strip()}

    zip_path = Path(zip_path)
    zip_path.mkdir(parents=True, exist_ok=True)

    enabled_modules = [
        mod
        for mod in addon_utils.modules()
        if (
            addon_utils.check(mod.__name__)[1]          # enabled in Preferences
            and mod.__name__ not in DEFAULT_ADDONS      # not black-listed
            and mod.__name__ in wanted                  # user selected
        )
    ]

    enabled_addons = []

    for mod in enabled_modules:
        addon_name        = mod.__name__               # e.g. "node_wrangler"
        addon_folder_name = addon_name.split(".")[-1]  # folder inside the ZIP
        enabled_addons.append(addon_folder_name)

        addon_root_path = Path(mod.__file__).parent
        addon_zip_file  = zip_path / f"{addon_folder_name}.zip"

        print(f"Adding {addon_root_path} to {addon_zip_file}")

        with zipfile.ZipFile(
            addon_zip_file, "w", zipfile.ZIP_DEFLATED, compresslevel=1
        ) as zipf:
            for root, _, files in os.walk(addon_root_path):
                rel_root = Path(root).relative_to(addon_root_path)
                for file in files:
                    src = Path(root) / file
                    dst = Path(addon_folder_name) / rel_root / file
                    zipf.write(src, dst)

    return enabled_addons
