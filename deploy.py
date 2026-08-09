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
    "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", ".git", ".github", ".claude", "tests", "reports", "releases", "rclone",
    "docs", "scripts",
    # Independently packaged Blender extensions must never be nested inside
    # the legacy SuperluminalRender add-on release.
    "extensions",
    # files
    ".gitignore", ".gitkeep", ".gitattributes", ".DS_Store",
    "README.md", "AGENTS.md", "CLAUDE.md", "pytest.ini",
    "deploy.py",
    "dev_config.json", "dev_config.example.json",
    "session.json", "session.json.tmp",
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

    # Patch version and provenance in the staged release artifact. Source
    # checkouts remain explicitly marked as development builds.
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

        build_info_path = os.path.join(stage, "build_info.py")
        with open(build_info_path, "r", encoding="utf-8") as f:
            build_info = f.read()
        build_info, n = re.subn(
            r'(^BUILD_CHANNEL\s*=\s*)["\'][^"\']+["\']',
            r'\1"release"',
            build_info,
            count=1,
            flags=re.MULTILINE,
        )
        if n == 0:
            raise SystemExit("Could not mark staged build as a release")
        with open(build_info_path, "w", encoding="utf-8") as f:
            f.write(build_info)

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
