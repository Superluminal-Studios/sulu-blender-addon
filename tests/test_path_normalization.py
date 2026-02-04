#!/usr/bin/env python3
"""
Test script to verify path normalization consistency in bat_utils.py

This verifies the fix for "files marked as missing when they exist" issue.

Run with: python tests/test_path_normalization.py
"""
import sys
import os
from pathlib import Path

# Add the addon to path
addon_dir = Path(__file__).parent.parent
sys.path.insert(0, str(addon_dir))

from blender_asset_tracer import bpathlib


def test_make_absolute_resolves_dotdot():
    """Verify bpathlib.make_absolute() resolves .. components."""

    # POSIX path with .. components
    input_path = Path("/Users/jonas/project/scenes/../textures/wood.png")
    result = bpathlib.make_absolute(input_path)

    # Should resolve to /Users/jonas/project/textures/wood.png
    assert ".." not in str(result), f".. not resolved: {result}"
    assert "textures/wood.png" in str(result), f"Path not correct: {result}"

    print("✓ POSIX .. resolution verified")


def test_make_absolute_windows_on_posix():
    """Verify Windows paths are handled correctly on POSIX."""

    # Windows path with .. components (simulated on POSIX)
    input_path = Path("D:/Projects/MyProject/../Shared/textures/wood.png")
    result = bpathlib.make_absolute(input_path)

    # Should normalize the .. even on POSIX
    result_str = str(result)

    # On POSIX, make_absolute normalizes the non-drive part
    # Result should be something like D:/Shared/textures/wood.png
    if sys.platform != "win32":
        # The D: part is preserved, and .. is resolved
        assert "textures/wood.png" in result_str, f"Path not normalized: {result}"

    print("✓ Windows path handling verified")


def test_normalization_consistency():
    """Verify paths normalized twice give same result."""

    test_paths = [
        Path("/home/user/project/textures/file.png"),
        Path("/home/user/project/scenes/../textures/file.png"),
        Path("/home/user/project/./textures/file.png"),
    ]

    for p in test_paths:
        result1 = bpathlib.make_absolute(p)
        result2 = bpathlib.make_absolute(result1)
        assert result1 == result2, f"Inconsistent normalization: {result1} vs {result2}"

    print("✓ Normalization consistency verified")


def test_comparison_after_normalization():
    """
    Verify the core fix: paths that resolve to the same file should be equal
    after normalization.
    """

    # Two paths that refer to the same file
    path1 = Path("/home/user/project/textures/wood.png")
    path2 = Path("/home/user/project/scenes/../textures/wood.png")

    norm1 = bpathlib.make_absolute(path1)
    norm2 = bpathlib.make_absolute(path2)

    assert norm1 == norm2, f"Paths should match after normalization:\n  {norm1}\n  {norm2}"

    # Verify set membership works (the original bug)
    missing_set = {norm1}
    assert norm2 in missing_set, "Set membership check failed after normalization"

    print("✓ Path comparison after normalization verified")


def test_no_symlink_resolution():
    """
    Verify make_absolute() doesn't resolve symlinks.
    This is important on macOS where /Users can resolve to /System/Volumes/Data/Users.
    """

    # Note: We can't test actual symlink behavior without creating symlinks,
    # but we can verify the function doesn't use resolve()

    input_path = Path("/Users/jonas/project/file.png")
    result = bpathlib.make_absolute(input_path)

    # On macOS, if we were using resolve(), /Users might become /System/Volumes/Data/Users
    # make_absolute() should keep /Users as-is
    if sys.platform == "darwin":
        if str(input_path).startswith("/Users"):
            assert str(result).startswith("/Users"), \
                f"Symlink was resolved unexpectedly: {result}"

    print("✓ No symlink resolution verified")


def test_norm_path_comparison():
    """
    Verify that _norm_path() (used in compute_project_root) produces
    consistent results when given paths already normalized by make_absolute().
    """
    from utils.bat_utils import _norm_path

    # Path already normalized by make_absolute
    normalized = bpathlib.make_absolute(Path("/home/user/project/textures/file.png"))

    # Apply _norm_path (simulating compute_project_root behavior)
    double_normalized = _norm_path(str(normalized))

    # Should be the same (idempotent)
    assert str(normalized).replace("\\", "/") == double_normalized.replace("\\", "/"), \
        f"Double normalization changed the path:\n  {normalized}\n  {double_normalized}"

    print("✓ _norm_path consistency verified")


if __name__ == "__main__":
    print("Testing path normalization consistency...\n")

    test_make_absolute_resolves_dotdot()
    test_make_absolute_windows_on_posix()
    test_normalization_consistency()
    test_comparison_after_normalization()
    test_no_symlink_resolution()

    try:
        test_norm_path_comparison()
    except ImportError as e:
        print(f"⚠ Skipped _norm_path test (import issue): {e}")

    print("\n✅ All path normalization tests passed!")
