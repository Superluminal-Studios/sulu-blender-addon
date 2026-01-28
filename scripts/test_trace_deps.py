#!/usr/bin/env python
"""Test the updated trace with file expansion."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ADDON_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ADDON_DIR))

# Import BAT directly
from blender_asset_tracer import trace
from utils import cloud_files


def load_config() -> dict:
    config_path = ADDON_DIR / "dev_config.json"
    with open(config_path) as f:
        return json.load(f)


def main():
    config = load_config()
    blend_path = Path(config.get("test_blend_path"))

    print(f"Testing trace with file expansion on: {blend_path}")
    print()

    deps = []
    missing = set()
    ok = set()
    patterns = []

    for usage in trace.deps(blend_path):
        abs_path = usage.abspath
        path_name = abs_path.name

        # Check if this is a pattern
        if "<UDIM>" in path_name or "*" in path_name:
            patterns.append(abs_path)

        # Use usage.files() to expand sequences
        expanded = []
        try:
            expanded = list(usage.files())
        except Exception as e:
            print(f"  Error expanding {path_name}: {e}")

        if not expanded:
            # Pattern/file not found
            deps.append(abs_path)
            missing.add(abs_path)
        else:
            for file_path in expanded:
                deps.append(file_path)
                # Try to read the file
                can_read, err = cloud_files.read_file_with_hydration(
                    str(file_path),
                    hydrate=True,
                    timeout_seconds=30,
                )
                if can_read:
                    ok.add(file_path)
                else:
                    missing.add(file_path)

    print(f"Raw usages (blocks): {len(list(trace.deps(blend_path)))}")
    print(f"Total dependencies (after expansion): {len(deps)}")
    print(f"OK files: {len(ok)}")
    print(f"Missing files: {len(missing)}")
    print(f"UDIM/glob patterns in raw trace: {len(patterns)}")
    print()

    if patterns:
        print("Patterns found in trace (should be expanded by usage.files()):")
        for p in patterns[:10]:
            print(f"  {p.name}")
        print()

    # Check what patterns expanded to
    missing_patterns = [m for m in missing if "<UDIM>" in m.name or "*" in m.name]
    print(f"Unexpanded patterns in missing (should be 0 if expansion worked): {len(missing_patterns)}")
    if missing_patterns:
        for p in missing_patterns[:5]:
            print(f"  {p.name}")
    print()

    # Show sample OK files
    if ok:
        print("Sample OK files:")
        for f in list(ok)[:10]:
            print(f"  [OK] {f.name}")
    print()

    # Show sample missing (non-pattern) files
    missing_real = [m for m in missing if "<UDIM>" not in m.name and "*" not in m.name]
    if missing_real:
        print(f"Sample missing (non-pattern) files ({len(missing_real)} total):")
        for m in missing_real[:10]:
            print(f"  [MISS] {m.name}")
            print(f"         {m}")


if __name__ == "__main__":
    main()
