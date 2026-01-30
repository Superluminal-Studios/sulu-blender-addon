import sys
import zipfile
import os
import re
from datetime import datetime

ADDON_NAME = "SuperluminalRender"


def get_arg_value(flag: str):
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return None


def sanitize_filename(part: str) -> str:
    # Keep common safe chars; replace everything else with "_"
    return re.sub(r"[^0-9A-Za-z._-]+", "_", part).strip("_")


def version_tuple(tag: str) -> str:
    """
    Blender add-ons expect a 3-int tuple (major, minor, patch).
    Extract the first three integers from the tag string.
    Examples:
      "1.2.3" -> "1, 2, 3"
      "v1.2.3" -> "1, 2, 3"
      "1.2.3-alpha.1" -> "1, 2, 3"
    """
    nums = re.findall(r"\d+", tag)
    nums = (nums + ["0", "0", "0"])[:3]
    return ", ".join(nums)


def should_exclude(rel_path: str) -> bool:
    """
    Exclude dev/build artifacts and rclone binaries. Keep all source .py files.
    """
    rel = rel_path.replace("\\", "/")
    parts = rel.split("/")
    filename = parts[-1]
    parent_dirs = parts[:-1]

    # --- Excluded directories (applies to all files) ---
    EXCLUDE_DIRS = {
        "__pycache__",
        ".git",
        ".github",
        ".claude",
        "tests",
        "reports",
        "rclone",  # Downloaded rclone binaries live here
    }
    if any(d in EXCLUDE_DIRS for d in parent_dirs):
        return True

    # --- Excluded files by exact name ---
    EXCLUDE_FILES = {
        # VCS
        ".gitignore",
        ".gitkeep",
        ".gitattributes",
        # Docs
        "README.md",
        "CLAUDE.md",
        # Manifest/extension stuff
        "extensions_index.json",
        "manifest.py",
        "update_manifest.py",
        "blender_manifest.toml",
        # Build/deploy scripts
        "deploy.py",
        "test_deploy.ps1",
        # Dev files
        "dev_config.json",
        "dev_config.example.json",
        # Session data
        "session.json",
        # rclone binaries (in case they're not in rclone/ dir)
        "rclone",
        "rclone.exe",
    }
    if filename in EXCLUDE_FILES:
        return True

    return False


# Experimental mode: quick export for testers
# Usage:
#   python deploy.py --experimental [--version <string>] [--output path/to/output.zip]
experimental_mode = "--experimental" in sys.argv
output_override = get_arg_value("--output")

if experimental_mode:
    # Use current directory as source
    addon_directory = os.path.dirname(os.path.abspath(__file__))

    # Optional custom version label in experimental mode; otherwise timestamped
    version = (
        get_arg_value("--version")
        or f"experimental-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    safe_version = sanitize_filename(version) or version

    # Output path
    if output_override:
        addon_path = output_override
    else:
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        filename = f"{ADDON_NAME}-{safe_version}.zip"
        if os.path.isdir(downloads):
            addon_path = os.path.join(downloads, filename)
        else:
            addon_path = os.path.join(addon_directory, filename)

else:
    # Release mode
    version = get_arg_value("--version")
    if not version:
        raise SystemExit(
            "Release mode requires: python deploy.py --version <tag> [--output <path>]"
        )

    version = version.split("/")[-1] if "/" in version else version
    safe_version = sanitize_filename(version) or version

    addon_directory = f"/tmp/{ADDON_NAME}"

    # Default: /tmp/SuperLuminalRender-<version>.zip (unless overridden)
    if output_override:
        addon_path = output_override
    else:
        addon_path = f"/tmp/{ADDON_NAME}-{safe_version}.zip"

init_path = os.path.join(addon_directory, "__init__.py")

if experimental_mode:
    # Experimental mode: don't modify files in place, just zip current working tree
    archive_root = ADDON_NAME

    with zipfile.ZipFile(addon_path, "w", zipfile.ZIP_DEFLATED) as addon_archive:
        for root, dirs, files in os.walk(addon_directory):
            # Prune obvious excluded dirs early (but NOT rclone; handled by should_exclude + allowlist)
            dirs[:] = [
                d
                for d in dirs
                if d
                not in {"__pycache__", ".git", ".github", ".claude", "tests", "reports"}
            ]

            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, addon_directory)

                if should_exclude(rel_path):
                    continue

                # Skip output zip itself if created inside source dir
                if os.path.abspath(file_path) == os.path.abspath(addon_path):
                    continue

                archive_name = os.path.join(archive_root, rel_path).replace("\\", "/")
                addon_archive.write(file_path, archive_name)

    print(f"Experimental build created: {addon_path}")
    print(f"Version tag: {version}")

else:
    # Release mode: modify __init__.py in /tmp staging folder
    with open(init_path, "r", encoding="utf-8") as f:
        init_content = f.read()

    new_tuple = f"({version_tuple(version)})"

    # Prefer a targeted replacement of the 'version' key in bl_info
    updated, n = re.subn(
        r"([\"']version[\"']\s*:\s*)\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)",
        rf"\1{new_tuple}",
        init_content,
        count=1,
    )

    if n == 0:
        # Fallback to previous behavior if pattern wasn't found
        updated = init_content.replace("(1, 0, 0)", new_tuple).replace(
            "(1,0,0)", new_tuple
        )

    with open(init_path, "w", encoding="utf-8") as f:
        f.write(updated)

    with zipfile.ZipFile(addon_path, "w", zipfile.ZIP_DEFLATED) as addon_archive:
        for root, dirs, files in os.walk(addon_directory):
            dirs[:] = [
                d
                for d in dirs
                if d
                not in {"__pycache__", ".git", ".github", ".claude", "tests", "reports", "rclone"}
            ]

            for file in files:
                file_path = os.path.join(root, file)

                rel_path_from_addon = os.path.relpath(file_path, addon_directory)
                if should_exclude(rel_path_from_addon):
                    continue

                # Safety: don't include the output zip if it lives under addon_directory
                if os.path.abspath(file_path) == os.path.abspath(addon_path):
                    continue

                # Archive path: SuperluminalRender/<relative_path>
                archive_name = os.path.join(ADDON_NAME, rel_path_from_addon).replace("\\", "/")
                addon_archive.write(file_path, archive_name)

    print(f"Release build created: {addon_path}")
    print(f"Version tag: {version}")
