"""
Back‑up all enabled add‑ons + every extension package (enabled or not),
but **skip anything whose name matches SKIP_FILTERS**.

• One <module>.zip per package, containing the package’s top‑level folder
  (or the original .zip copied as‑is if it hasn’t been un‑zipped yet).
• Everything goes into a new temp directory, loggered at the end.
• Set DEBUG_OPEN_EXPLORER = True to open that folder automatically.

Run inside Blender (Scripting workspace) or with:
    blender --python this_script.py
"""

import bpy, sys, os, zipfile, tempfile, shutil, platform, subprocess, fnmatch

def logger(msg: str) -> None:
    """logger a message to the console
    (and flush it immediately)."""
    print(msg, flush=True)


# --------------------------------------------------------------------
# USER SETTINGS
# --------------------------------------------------------------------
DEBUG_OPEN_EXPLORER = True

# Any glob patterns that should be skipped (module name, dir name, or zip name)
SKIP_FILTERS = [
    ".blender_ext",
    "bl_ext.blender_org.camera_shakify",
    "bl_pkg",
    "cycles",
    "io_anim_bvh",
    "io_curve_svg",
    "io_mesh_uv_layout",
    "io_scene_gltf2",
    "pose_library",
    "sulu-blender-addon",
]

# --------------------------------------------------------------------
# HELPERS
# --------------------------------------------------------------------
def wants_skip(name: str) -> bool:
    """Return True if 'name' matches any glob in SKIP_FILTERS."""
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SKIP_FILTERS)

def zip_dir(src_dir: str, dest_zip: str) -> None:
    root_parent = os.path.dirname(src_dir)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(src_dir):
            if "__pycache__" in root:
                continue
            for fn in files:
                if fn.endswith((".pyc", ".pyo")):
                    continue
                fp = os.path.join(root, fn)
                zf.write(fp, os.path.relpath(fp, root_parent))

def zip_single_file(py_file: str, module: str, dest_zip: str) -> None:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(py_file, os.path.join(module, os.path.basename(py_file)))



# --------------------------------------------------------------------
# PREP
# --------------------------------------------------------------------


# --------------------------------------------------------------------
# 1) ENABLED ADD‑ONS / EXTENSIONS  (bpy.context.preferences.addons)
# --------------------------------------------------------------------

def bundle_addons(temp_path):
    packed_modules = []
    logger(f"\n🔹 Addon temp directory: {temp_path}\n")

    for mod_name in bpy.context.preferences.addons.keys():
        if wants_skip(mod_name):
            logger(f"⏩  Skipped (filter)  {mod_name}")
            continue

        mod = sys.modules.get(mod_name)
        fpath = getattr(mod, "__file__", None)
        if not fpath:
            logger(f"⚠️  {mod_name} has no __file__ → skipped")
            continue

        try:
            if fpath.endswith("__init__.py"):            # package
                pdir = os.path.dirname(fpath)
                zip_dir(pdir, os.path.join(temp_path, f"{mod_name}.zip"))
                packed_modules.append(mod_name)
            else:                                        # single‑file
                zip_single_file(fpath, mod_name,
                                os.path.join(temp_path, f"{mod_name}.zip"))
                packed_modules.append(os.path.basename(fpath))
            logger(f"✅  Zipped add‑on / extension  {mod_name}")
        except Exception as err:
            logger(f"❌  Failed on {mod_name}: {err}")

    # --------------------------------------------------------------------
    # 2) EVERY PACKAGE IN EACH EXTENSION REPO DIRECTORY
    #    (covers disabled extensions & ones not yet enabled)
    # --------------------------------------------------------------------
    ext_prefs = getattr(bpy.context.preferences, "extensions", None)
    if ext_prefs:
        for repo in ext_prefs.repos:
            repo_dir = getattr(repo, "directory", "")
            if not repo_dir or not os.path.isdir(repo_dir):
                # typical when the repo hasn’t synced yet
                continue
            for entry in os.listdir(repo_dir):
                entry_base = os.path.splitext(entry)[0]   # strip .zip if present
                if wants_skip(entry_base):
                    logger(f"⏩  Skipped (filter)  {entry_base}")
                    continue

                entry_path = os.path.join(repo_dir, entry)
                out_path = os.path.join(temp_path, f"{entry_base}.zip")
                try:
                    if os.path.isdir(entry_path):
                        zip_dir(entry_path, out_path)
                    elif entry_path.lower().endswith(".zip"):
                        shutil.copy2(entry_path, out_path)
                    else:
                        continue
                    logger(f"✅  Backed up repo package {entry_base}")
                except Exception as err:
                    logger(f"❌  Failed on repo package {entry_base}: {err}")
    else:
        logger("ℹ️  No extension system detected (pre‑4.2 build).")

    logger(f"\n🎉  Addon packing complete. All archives are in:\n{temp_path}\n")
    return packed_modules

