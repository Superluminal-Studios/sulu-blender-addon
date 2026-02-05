"""Build a release zip for the Superluminal Blender add-on."""

import argparse
import os
import re
import shutil
import tempfile
import zipfile

ADDON_NAME = "SuperluminalRender"

EXCLUDE = {
    # directories
    "__pycache__", ".git", ".github", ".claude", "tests", "reports", "releases", "rclone",
    # files
    ".gitignore", ".gitkeep", ".gitattributes",
    "README.md", "CLAUDE.md",
    "extensions_index.json", "manifest.py", "update_manifest.py", "blender_manifest.toml",
    "deploy.py", "test_deploy.ps1",
    "dev_config.json", "dev_config.example.json",
    "session.json",
    "rclone.exe",
    "nul",
}


def version_tuple(tag: str) -> str:
    """'v1.2.3-beta' -> '1, 2, 3'"""
    nums = re.findall(r"\d+", tag)
    nums = (nums + ["0", "0", "0"])[:3]
    return ", ".join(nums)


def main():
    parser = argparse.ArgumentParser(description="Build release zip")
    parser.add_argument("--version", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    tmpdir = tempfile.gettempdir()
    if args.output is None:
        args.output = (
            os.path.join(tmpdir, f"{ADDON_NAME}.zip")
            if args.version
            else os.path.join(os.path.expanduser("~"), "Downloads", f"{ADDON_NAME}.zip")
        )

    src = os.path.dirname(os.path.abspath(__file__))
    stage = os.path.join(tmpdir, ADDON_NAME)

    # Stage: copy source tree, skipping excluded names
    if os.path.exists(stage):
        shutil.rmtree(stage)
    shutil.copytree(src, stage, ignore=shutil.ignore_patterns(*EXCLUDE))

    # Patch version in staged __init__.py
    if args.version:
        init_path = os.path.join(stage, "__init__.py")
        with open(init_path, "r", encoding="utf-8") as f:
            text = f.read()
        new_tuple = f"({version_tuple(args.version)})"
        text, n = re.subn(
            r"([\"']version[\"']\s*:\s*)\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)",
            rf"\1{new_tuple}",
            text,
            count=1,
        )
        if n == 0:
            raise SystemExit("Could not find version tuple in __init__.py")
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(text)

    # Zip
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(stage):
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.join(ADDON_NAME, os.path.relpath(full, stage))
                zf.write(full, arc.replace("\\", "/"))

    label = f"version {args.version}" if args.version else "dev build"
    print(f"Created {args.output}  ({label})")


if __name__ == "__main__":
    main()
