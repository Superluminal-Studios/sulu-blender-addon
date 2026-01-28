import sys, zipfile, os
from datetime import datetime

# Experimental mode: quick export for testers
# Usage: python deploy.py --experimental [--output path/to/output.zip]
experimental_mode = "--experimental" in sys.argv

if experimental_mode:
    # Use current directory as source
    addon_directory = os.path.dirname(os.path.abspath(__file__))
    addon_name = "SuperLuminalRender"

    # Check for custom output path
    if "--output" in sys.argv:
        addon_path = sys.argv[sys.argv.index("--output") + 1]
    else:
        # Default to Downloads folder or current directory
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        if os.path.isdir(downloads):
            addon_path = os.path.join(downloads, f"{addon_name}_experimental.zip")
        else:
            addon_path = os.path.join(addon_directory, f"{addon_name}_experimental.zip")

    version = f"experimental-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
else:
    # Release mode (original behavior)
    version = sys.argv[sys.argv.index("--version") + 1]
    version = version.split("/")[-1] if "/" in version else version
    addon_directory = "/tmp/SuperLuminalRender"
    addon_path = f"{addon_directory}.zip"

init_path = os.path.join(addon_directory, "__init__.py")

exclude_files_addon = [
    # Version control
    "__pycache__",
    ".git",
    ".github",
    ".gitignore",
    ".gitattributes",
    # Documentation
    "README.md",
    "CLAUDE.md",
    # Extension/manifest files
    "extensions_index.json",
    "manifest.py",
    "update_manifest.py",
    "blender_manifest.toml",
    # Build/deploy
    "deploy.py",
    # Tests (entire directory)
    "tests/",
    "tests",
    # Dev files
    "dev_config.json",
    "dev_config.example.json",
    # Reports
    "reports/",
    "reports",
    # Session data (should never be included!)
    "session.json",
    # Claude Code skills
    ".claude/",
    ".claude",
    # Downloaded rclone binaries
    "rclone/",
    "rclone",
]

if experimental_mode:
    # Experimental mode: don't modify files in place, write modified __init__.py directly to zip
    with open(init_path, "r") as f:
        init_content = f.read()

    # Archive root folder name
    archive_root = "SuperLuminalRender"

    with zipfile.ZipFile(addon_path, "w", zipfile.ZIP_DEFLATED) as addon_archive:
        for root, dirs, files in os.walk(addon_directory):
            # Skip excluded directories early
            dirs[:] = [d for d in dirs if not any(excl in d or d == excl.rstrip('/') for excl in exclude_files_addon)]

            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, addon_directory)

                # Skip excluded files
                if any(excluded in rel_path or excluded in file_path for excluded in exclude_files_addon):
                    continue

                # Skip the output zip itself if it's in the same directory
                if os.path.abspath(file_path) == os.path.abspath(addon_path):
                    continue

                archive_name = os.path.join(archive_root, rel_path).replace("\\", "/")

                # For __init__.py at root, we could inject version info (optional)
                # For now, just include files as-is since version tuple doesn't matter for testing
                addon_archive.write(file_path, archive_name)

    print(f"Experimental build created: {addon_path}")
    print(f"Version tag: {version}")

else:
    # Release mode: original behavior (modifies files in /tmp)
    with open(init_path, "r") as f:
        init_content = f.read()
        init_content = init_content.replace("(1, 0, 0)", f"({ version.replace('.', ', ') })")

    with open(init_path, "w") as f:
        f.write(init_content)

    with zipfile.ZipFile(addon_path, "w") as addon_archive:
        for root, dirs, files in os.walk(addon_directory):
            for file in files:
                file_path = os.path.join(root, file)
                if any(excluded_file in file_path for excluded_file in exclude_files_addon):
                    continue
                else:
                    addon_archive.write(file_path, os.path.relpath(file_path, '/tmp/'))

#import toml, json, hashlib
#extension_index = os.path.join(addon_directory, "extensions_index.json")
#blender_manifest = os.path.join(addon_directory, "blender_manifest.toml")
#extension_path = f"{addon_directory}_Extension.zip"

# exclude_files_extension = ["__pycache__",
#                  ".git",
#                  ".github",
#                  ".gitignore",
#                  ".gitattributes",
#                  ".github",
#                  "README.md",
#                  "extensions_index.json",
#                  "manifest.py",                 
#                  "update_manifest.py"]

# with open(blender_manifest, "r") as f:
#     manifest = toml.loads(f.read())

# with open(blender_manifest, "w") as f:
#     manifest['version'] = version
#     f.write(toml.dumps(manifest))

# with zipfile.ZipFile(extension_path, "w") as extension_archive:
#     for root, dirs, files in os.walk(addon_directory):
#         for file in files:
#             file_path = os.path.join(root, file)
#             if any(excluded_file in file_path for excluded_file in exclude_files_extension):
#                 continue
#             else:
#                 extension_archive.write(file_path, os.path.relpath(file_path, '/tmp/'))

# with open(extension_path, "rb") as f:
#     archive_content = f.read()

# with open(extension_index, "r") as f:
#     index = json.loads(f.read())

# with open(extension_index, "w") as f:
#     index['data'][0]['version'] = version
#     index['data'][0]['archive_url'] = f"https://github.com/Superluminal-Studios/sulu-blender-addon/releases/download/{version}/SuperLuminalRender.zip"
#     index['data'][0]['archive_size'] = len(archive_content)
#     index['data'][0]['archive_hash'] = f"sha256:{hashlib.sha256(archive_content).hexdigest()}"
#     f.write(json.dumps(index, indent=4))




