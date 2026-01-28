#!/usr/bin/env python
"""
Diagnostic script to test cloud file (Google Drive, OneDrive, etc.) behavior.

Traces dependencies from a blend file and tests various methods to detect
and hydrate cloud-mounted placeholder files.

Usage:
    python scripts/test_cloud_files.py [--hydrate]

Options:
    --hydrate    Attempt to hydrate cloud placeholders using Windows APIs

Reads test_blend_path from dev_config.json.
"""
from __future__ import annotations

import json
import os
import sys
import ctypes
from pathlib import Path

# Add parent to path for imports
SCRIPT_DIR = Path(__file__).parent
ADDON_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ADDON_DIR))

from blender_asset_tracer import trace


def load_config() -> dict:
    """Load dev_config.json."""
    config_path = ADDON_DIR / "dev_config.json"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        print("Copy dev_config.example.json to dev_config.json and fill in paths")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def get_file_attributes_win32(path: str) -> dict:
    """Get Windows file attributes for cloud file detection."""
    result = {
        "exists_stat": False,
        "exists_path": False,
        "is_offline": False,
        "is_recall_on_open": False,
        "is_recall_on_data_access": False,
        "is_pinned": False,
        "is_unpinned": False,
        "raw_attrs": None,
    }

    if sys.platform != "win32":
        return result

    # Windows file attribute constants
    FILE_ATTRIBUTE_OFFLINE = 0x1000
    FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
    FILE_ATTRIBUTE_PINNED = 0x00080000
    FILE_ATTRIBUTE_UNPINNED = 0x00100000

    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF:  # INVALID_FILE_ATTRIBUTES
            return result

        result["raw_attrs"] = hex(attrs)
        result["exists_stat"] = True
        result["is_offline"] = bool(attrs & FILE_ATTRIBUTE_OFFLINE)
        result["is_recall_on_open"] = bool(attrs & FILE_ATTRIBUTE_RECALL_ON_OPEN)
        result["is_recall_on_data_access"] = bool(attrs & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
        result["is_pinned"] = bool(attrs & FILE_ATTRIBUTE_PINNED)
        result["is_unpinned"] = bool(attrs & FILE_ATTRIBUTE_UNPINNED)
    except Exception as e:
        result["error"] = str(e)

    try:
        result["exists_path"] = Path(path).exists()
    except Exception:
        pass

    return result


def test_file_access(path: Path) -> dict:
    """Test various ways to access a file."""
    result = {
        "path": str(path),
        "exists": None,
        "is_file": None,
        "is_dir": None,
        "stat_size": None,
        "open_1byte": None,
        "open_4kb": None,
        "open_full": None,
        "win_attrs": None,
    }

    # Test exists()
    try:
        result["exists"] = path.exists()
    except Exception as e:
        result["exists"] = f"ERROR: {e}"

    # Test is_file()
    try:
        result["is_file"] = path.is_file()
    except Exception as e:
        result["is_file"] = f"ERROR: {e}"

    # Test is_dir()
    try:
        result["is_dir"] = path.is_dir()
    except Exception as e:
        result["is_dir"] = f"ERROR: {e}"

    # Test stat()
    try:
        st = path.stat()
        result["stat_size"] = st.st_size
    except Exception as e:
        result["stat_size"] = f"ERROR: {e}"

    # Test open + read 1 byte
    try:
        with path.open("rb") as f:
            data = f.read(1)
            result["open_1byte"] = f"OK ({len(data)} bytes)"
    except Exception as e:
        result["open_1byte"] = f"ERROR: {type(e).__name__}: {e}"

    # Test open + read 4KB
    try:
        with path.open("rb") as f:
            data = f.read(4096)
            result["open_4kb"] = f"OK ({len(data)} bytes)"
    except Exception as e:
        result["open_4kb"] = f"ERROR: {type(e).__name__}: {e}"

    # Test open + read full file
    try:
        with path.open("rb") as f:
            total = 0
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
            result["open_full"] = f"OK ({total} bytes)"
    except Exception as e:
        result["open_full"] = f"ERROR: {type(e).__name__}: {e}"

    # Windows-specific attributes
    if sys.platform == "win32":
        result["win_attrs"] = get_file_attributes_win32(str(path))

    return result


def main():
    # Parse args
    do_hydrate = "--hydrate" in sys.argv

    print("=" * 70)
    print("Cloud File Diagnostic Tool")
    print("=" * 70)
    if do_hydrate:
        print("Mode: HYDRATION ENABLED - will attempt to download cloud placeholders")
    else:
        print("Mode: Detection only (use --hydrate to attempt downloads)")

    # Import cloud_files module
    from utils import cloud_files

    config = load_config()
    blend_path = config.get("test_blend_path")

    if not blend_path:
        print("ERROR: test_blend_path not set in dev_config.json")
        sys.exit(1)

    blend_path = Path(blend_path)
    print(f"\nBlend file: {blend_path}")
    print(f"Drive: {blend_path.drive}")

    # Test the blend file itself
    print("\n" + "-" * 70)
    print("Testing blend file access:")
    print("-" * 70)
    blend_result = test_file_access(blend_path)
    for key, value in blend_result.items():
        if key == "win_attrs" and value:
            print(f"  {key}:")
            for k, v in value.items():
                print(f"    {k}: {v}")
        else:
            print(f"  {key}: {value}")

    # Trace dependencies
    print("\n" + "-" * 70)
    print("Tracing dependencies with BAT...")
    print("-" * 70)

    deps = []
    try:
        for usage in trace.deps(blend_path):
            deps.append(usage.abspath)
    except Exception as e:
        print(f"ERROR tracing: {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"Found {len(deps)} dependencies")

    # Test each dependency
    print("\n" + "-" * 70)
    print("Testing dependency file access:")
    print("-" * 70)

    stats = {"ok": 0, "missing": 0, "error": 0, "cloud_placeholder": 0, "hydrated": 0}

    for i, dep_path in enumerate(deps[:20], 1):  # Limit to first 20 for brevity
        print(f"\n[{i}/{len(deps)}] {dep_path.name}")
        print(f"  Path: {dep_path}")

        # Check if it's a cloud placeholder
        is_cloud_placeholder = cloud_files.is_cloud_placeholder(str(dep_path))
        if is_cloud_placeholder:
            stats["cloud_placeholder"] += 1
            print(f"  Cloud placeholder: YES")

        # Test with cloud_files module
        if do_hydrate:
            print(f"  Attempting hydration...")
            ok, err = cloud_files.read_file_with_hydration(
                str(dep_path),
                hydrate=True,
                timeout_seconds=30,
            )
            if ok:
                stats["ok"] += 1
                if is_cloud_placeholder:
                    stats["hydrated"] += 1
                    print(f"  Result: HYDRATED successfully!")
                else:
                    print(f"  Result: OK")
            elif err == "File not found":
                stats["missing"] += 1
                print(f"  Result: MISSING (file not found)")
            else:
                stats["error"] += 1
                print(f"  Result: ERROR - {err}")
        else:
            # Just do basic detection without hydration
            result = test_file_access(dep_path)

            if result["exists"] is True and "OK" in str(result.get("open_1byte", "")):
                stats["ok"] += 1
                status = "OK"
            elif result["exists"] is False or "FileNotFoundError" in str(result.get("open_1byte", "")):
                stats["missing"] += 1
                status = "MISSING"
            else:
                stats["error"] += 1
                status = "ERROR"

            print(f"  Status: {status}")
            print(f"  exists(): {result['exists']}")
            print(f"  open(1b): {result['open_1byte']}")

    if len(deps) > 20:
        print(f"\n... and {len(deps) - 20} more files")

    # Summary
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)
    print(f"  Total dependencies: {len(deps)}")
    print(f"  OK: {stats['ok']}")
    print(f"  Missing: {stats['missing']}")
    print(f"  Errors: {stats['error']}")
    print(f"  Cloud placeholders detected: {stats['cloud_placeholder']}")
    if do_hydrate:
        print(f"  Successfully hydrated: {stats['hydrated']}")


if __name__ == "__main__":
    main()
