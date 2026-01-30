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
    Decide exclusion based on *exact* path segments / filenames
    (prevents substring accidents like excluding 'rclone.py').
    """
    rel = rel_path.replace("\\", "/")
    parts = rel.split("/")
    filename = parts[-1]

    # --- Allowlist ---
    # rclone.py is needed; never exclude it even if other rclone assets are excluded
    if filename == "rclone.py":
        return False

    # --- Excluded directories (exact directory name match) ---
    # Note: We do NOT prune 'rclone' here so we can still include rclone.py if it's inside.
    EXCLUDE_DIR_NAMES = {
        "__pycache__",
        ".git",
        ".github",
        ".claude",
        "tests",
        "reports",
    }

    # If any parent directory is excluded -> exclude
    if any(p in EXCLUDE_DIR_NAMES for p in parts[:-1]):
        return True

    # Exclude everything under a directory named exactly "rclone" (downloaded binaries),
    # BUT rclone.py was already allowlisted above.
    if "rclone" in parts[:-1]:
        return True

    # --- Excluded filenames (exact filename match) ---
    EXCLUDE_FILE_NAMES = {
        # VCS / housekeeping
        ".gitignore",
        ".gitkeep",
        ".gitattributes",
        # Docs
        "README.md",
        "CLAUDE.md",
        # Extension/manifest files
        "extensions_index.json",
        "manifest.py",
        "update_manifest.py",
        "blender_manifest.toml",
        # Build/deploy
        "deploy.py",
        # Dev files
        "dev_config.json",
        "dev_config.example.json",
        # Reports / session data
        "session.json",
    }

    if filename in EXCLUDE_FILE_NAMES:
        return True

    # If there's a downloaded binary named exactly "rclone" (no .py), exclude it explicitly
    if filename in {"rclone", "rclone.exe"}:
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
            # Optional prune (rclone not pruned so rclone.py can pass allowlist if needed)
            dirs[:] = [
                d
                for d in dirs
                if d
                not in {"__pycache__", ".git", ".github", ".claude", "tests", "reports"}
            ]

            for file in files:
                file_path = os.path.join(root, file)

                rel_path_from_addon = os.path.relpath(file_path, addon_directory)
                if should_exclude(rel_path_from_addon):
                    continue

                # Safety: don't include the output zip if it lives under addon_directory
                if os.path.abspath(file_path) == os.path.abspath(addon_path):
                    continue

                # Keep the archive root as SuperLuminalRender/ by zipping relative to /tmp
                addon_archive.write(file_path, os.path.relpath(file_path, "/tmp/"))

    print(f"Release build created: {addon_path}")
    print(f"Version tag: {version}")
