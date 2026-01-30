import os
import re
import sys
import zipfile
from datetime import datetime

ADDON_NAME = "SuperluminalRender"


def get_arg_value(flag: str):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def sanitize_filename(part: str) -> str:
    # Keep safe chars for filenames
    return re.sub(r"[^0-9A-Za-z._-]+", "_", part).strip("_")


def version_tuple(tag: str) -> str:
    """
    Blender add-ons expect (major, minor, patch).
    We extract the first 3 integers from the tag string.
    """
    nums = re.findall(r"\d+", tag)
    nums = (nums + ["0", "0", "0"])[:3]
    return ", ".join(nums)


# --------------------------------------------------------------------
# Modes / args
# --------------------------------------------------------------------
experimental_mode = "--experimental" in sys.argv
output_override = get_arg_value("--output")

if experimental_mode:
    # source = current directory (where deploy.py lives)
    addon_directory = os.path.dirname(os.path.abspath(__file__))

    # Optional custom version label in experimental mode
    version = (
        get_arg_value("--version")
        or f"experimental-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    safe_version = sanitize_filename(version) or version

    if output_override:
        addon_path = output_override
    else:
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        filename = f"{ADDON_NAME}-{safe_version}.zip"
        addon_path = (
            os.path.join(downloads, filename)
            if os.path.isdir(downloads)
            else os.path.join(addon_directory, filename)
        )

else:
    version = get_arg_value("--version")
    if not version:
        raise SystemExit(
            "Release mode requires: python deploy.py --version <tag> [--output <path>]"
        )

    version = version.split("/")[-1] if "/" in version else version
    safe_version = sanitize_filename(version) or version

    addon_directory = f"/tmp/{ADDON_NAME}"

    # default output includes version
    addon_path = output_override or f"/tmp/{ADDON_NAME}-{safe_version}.zip"

init_path = os.path.join(addon_directory, "__init__.py")

# --------------------------------------------------------------------
# Excludes (exact-match logic, not substring)
# --------------------------------------------------------------------
EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".github",
    ".claude",
    "tests",
    "reports",
}

# Exclude these file *names* anywhere in the tree
EXCLUDE_BASENAMES = {
    ".gitignore",
    ".gitkeep",
    ".gitattributes",
    "README.md",
    "CLAUDE.md",
    "extensions_index.json",
    "manifest.py",
    "update_manifest.py",
    "blender_manifest.toml",
    "deploy.py",  # don't ship the packer itself
    "dev_config.json",
    "dev_config.example.json",
    "session.json",
}

RCLONE_BINARY_BASENAMES = {"rclone", "rclone.exe"}


def rel_parts(rel_norm: str):
    return [p for p in rel_norm.split("/") if p and p != "."]


def should_exclude(rel_norm: str) -> bool:
    """
    rel_norm is a forward-slash relative path inside the addon directory.
    """
    parts = rel_parts(rel_norm)
    base = parts[-1] if parts else rel_norm

    # Exclude whole directories by path segment name
    if any(seg in EXCLUDE_DIRS for seg in parts[:-1]):
        return True

    # Exclude by basename anywhere
    if base in EXCLUDE_BASENAMES:
        return True

    # Exclude downloaded rclone binaries only (keep rclone.py!)
    # This triggers if the file is inside any folder named "rclone"
    # and the file name is exactly "rclone" or "rclone.exe".
    if "rclone" in parts[:-1] and base in RCLONE_BINARY_BASENAMES:
        return True

    return False


# --------------------------------------------------------------------
# Build zip
# --------------------------------------------------------------------
archive_root = ADDON_NAME

if experimental_mode:
    # Experimental mode: do not modify files in place
    with zipfile.ZipFile(addon_path, "w", zipfile.ZIP_DEFLATED) as addon_archive:
        for root, dirs, files in os.walk(addon_directory):
            # filter excluded dirs at walk-time (exact matches)
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                file_path = os.path.join(root, file)

                # Skip output zip itself if it's inside the folder
                if os.path.abspath(file_path) == os.path.abspath(addon_path):
                    continue

                rel_path = os.path.relpath(file_path, addon_directory)
                rel_norm = rel_path.replace("\\", "/")

                if should_exclude(rel_norm):
                    continue

                archive_name = f"{archive_root}/{rel_norm}"
                addon_archive.write(file_path, archive_name)

    print(f"Experimental build created: {addon_path}")
    print(f"Version tag: {version}")

else:
    # Release mode: update __init__.py version tuple in /tmp staging folder
    with open(init_path, "r", encoding="utf-8") as f:
        init_content = f.read()

    new_tuple = f"({version_tuple(version)})"

    # Prefer replacing bl_info['version']: (x, y, z)
    updated, n = re.subn(
        r"([\"']version[\"']\s*:\s*)\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)",
        rf"\1{new_tuple}",
        init_content,
        count=1,
    )

    if n == 0:
        # fallback to older literal replacement if needed
        updated = init_content.replace("(1, 0, 0)", new_tuple).replace(
            "(1,0,0)", new_tuple
        )

    with open(init_path, "w", encoding="utf-8") as f:
        f.write(updated)

    with zipfile.ZipFile(addon_path, "w", zipfile.ZIP_DEFLATED) as addon_archive:
        for root, dirs, files in os.walk(addon_directory):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                file_path = os.path.join(root, file)

                if os.path.abspath(file_path) == os.path.abspath(addon_path):
                    continue

                rel_path = os.path.relpath(file_path, addon_directory)
                rel_norm = rel_path.replace("\\", "/")

                if should_exclude(rel_norm):
                    continue

                archive_name = f"{archive_root}/{rel_norm}"
                addon_archive.write(file_path, archive_name)

    print(f"Release build created: {addon_path}")
    print(f"Version tag: {version}")
