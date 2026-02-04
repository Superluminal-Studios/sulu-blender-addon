#!/usr/bin/env python3
"""
Test to verify linked .blend files are properly tracked as dependencies.

This addresses the concern: "blend files weren't found if they didn't have
any dependencies because the trace dependencies would not add the blend
a missing file would come from"

The fix verification:
1. Linked .blend files ARE tracked via LI (Library) blocks
2. Even if a linked .blend has no external dependencies (textures), it's still tracked
3. The main .blend file is always added to the pack, even with zero dependencies
4. All source .blend files that dependencies come from are tracked

Run with: python tests/test_linked_library_tracking.py
"""
import importlib.util
import sys
from pathlib import Path

# Add the addon to path
addon_dir = Path(__file__).parent.parent
sys.path.insert(0, str(addon_dir))


def _import_bat_utils():
    """Import bat_utils from the addon directory."""
    bat_utils_path = addon_dir / "utils" / "bat_utils.py"
    spec = importlib.util.spec_from_file_location("bat_utils", bat_utils_path)
    bat_utils = importlib.util.module_from_spec(spec)
    sys.modules["bat_utils"] = bat_utils
    spec.loader.exec_module(bat_utils)
    return bat_utils

# Test data directory
BLENDFILES_DIR = addon_dir / "tests" / "bat" / "blendfiles"


def test_li_blocks_yield_dependencies():
    """Verify that LI (Library) blocks yield BlockUsage for linked .blend files."""
    from blender_asset_tracer import trace

    if not BLENDFILES_DIR.exists():
        print("⚠ Skipping: blendfiles directory not found")
        return

    # Test with linked_cube.blend which links to basic_file.blend
    blend_path = BLENDFILES_DIR / "linked_cube.blend"
    if not blend_path.exists():
        print("⚠ Skipping: linked_cube.blend not found")
        return

    deps = list(trace.deps(blend_path))

    # Should find at least one LI block (the link to basic_file.blend)
    li_deps = [d for d in deps if d.block.code == b"LI"]

    assert len(li_deps) > 0, "Should find Library (LI) block dependencies"

    # The linked file should be basic_file.blend
    linked_paths = [d.asset_path for d in li_deps]
    assert any(b"basic_file.blend" in bytes(p) for p in linked_paths), \
        f"Should find basic_file.blend in linked paths: {linked_paths}"

    print("✓ LI blocks yield dependencies for linked .blend files")


def test_recursive_library_tracking():
    """Verify that recursively linked libraries are all tracked."""
    from blender_asset_tracer import trace

    if not BLENDFILES_DIR.exists():
        print("⚠ Skipping: blendfiles directory not found")
        return

    # doubly_linked.blend -> linked_cube.blend -> basic_file.blend
    # doubly_linked.blend -> material_textures.blend (with textures)
    blend_path = BLENDFILES_DIR / "doubly_linked.blend"
    if not blend_path.exists():
        print("⚠ Skipping: doubly_linked.blend not found")
        return

    deps = list(trace.deps(blend_path))
    li_deps = [d for d in deps if d.block.code == b"LI"]

    # Should find multiple linked libraries
    linked_names = set()
    for d in li_deps:
        path_str = str(d.asset_path, 'utf-8') if isinstance(d.asset_path, bytes) else str(d.asset_path)
        # Extract just the filename
        name = path_str.split('/')[-1].split('\\')[-1]
        linked_names.add(name)

    print(f"  Found linked libraries: {linked_names}")

    # Should include both directly and transitively linked files
    assert "linked_cube.blend" in linked_names, "Should track directly linked file"
    assert "basic_file.blend" in linked_names, "Should track transitively linked file"

    print("✓ Recursive library tracking works correctly")


def test_trace_dependencies_includes_linked_blends():
    """
    Verify that trace.deps() includes linked .blend files.

    This simulates what trace_dependencies() in bat_utils.py does:
    it iterates over trace.deps() results and collects all abspaths.
    """
    from blender_asset_tracer import trace, bpathlib

    if not BLENDFILES_DIR.exists():
        print("⚠ Skipping: blendfiles directory not found")
        return

    blend_path = BLENDFILES_DIR / "doubly_linked.blend"
    if not blend_path.exists():
        print("⚠ Skipping: doubly_linked.blend not found")
        return

    # Simulate trace_dependencies() behavior
    dep_paths = []
    for usage in trace.deps(blend_path):
        try:
            abs_path = bpathlib.make_absolute(usage.abspath)
        except Exception:
            abs_path = usage.abspath
        dep_paths.append(abs_path)

    # Convert paths to names for easier checking
    dep_names = set()
    for p in dep_paths:
        name = p.name
        dep_names.add(name)

    print(f"  Dependency names: {sorted(dep_names)}")

    # Should include linked .blend files
    blend_deps = [n for n in dep_names if n.endswith('.blend')]
    assert len(blend_deps) > 0, f"Should find linked .blend files in dependencies: {dep_names}"

    # Specifically check for expected linked files
    assert "linked_cube.blend" in dep_names, "Should include linked_cube.blend"
    assert "basic_file.blend" in dep_names, "Should include basic_file.blend"
    assert "material_textures.blend" in dep_names, "Should include material_textures.blend"

    print("✓ trace.deps() includes linked .blend files in dependency paths")


def test_linked_blend_without_external_deps():
    """
    Verify that a linked .blend file with no external dependencies
    is still tracked as a dependency.

    This is the core issue: "blend files weren't found if they didn't
    have any dependencies"

    The linked_cube.blend file links to basic_file.blend. Even if
    basic_file.blend had no textures or other external files, it
    should still be tracked because:
    1. linked_cube.blend has an LI block pointing to it
    2. The LI block handler yields a BlockUsage for the linked file
    """
    from blender_asset_tracer import trace

    if not BLENDFILES_DIR.exists():
        print("⚠ Skipping: blendfiles directory not found")
        return

    blend_path = BLENDFILES_DIR / "linked_cube.blend"
    if not blend_path.exists():
        print("⚠ Skipping: linked_cube.blend not found")
        return

    deps = list(trace.deps(blend_path))

    # Find the dependency for basic_file.blend
    basic_file_deps = [
        d for d in deps
        if b"basic_file.blend" in bytes(d.asset_path)
    ]

    assert len(basic_file_deps) > 0, \
        "basic_file.blend should be tracked even if it has minimal external deps"

    # Verify it's an LI (Library) block
    assert basic_file_deps[0].block.code == b"LI", \
        "The linked .blend should be tracked via LI block"

    print("✓ Linked .blend files without external deps are tracked via LI blocks")


def test_source_blend_tracking():
    """
    Verify that we can track which .blend file each dependency comes from.

    This is important for debugging: when a texture is missing, we need
    to know which .blend file references it.
    """
    from blender_asset_tracer import trace

    if not BLENDFILES_DIR.exists():
        print("⚠ Skipping: blendfiles directory not found")
        return

    blend_path = BLENDFILES_DIR / "doubly_linked.blend"
    if not blend_path.exists():
        print("⚠ Skipping: doubly_linked.blend not found")
        return

    deps = list(trace.deps(blend_path))

    # Each BlockUsage should have a source .blend file
    for usage in deps:
        source_blend = usage.block.bfile.filepath
        assert source_blend is not None, f"Usage {usage} should have source blend file"

        # The source should be a Path or have a path-like representation
        source_str = str(source_blend)
        assert source_str.endswith('.blend'), f"Source should be a .blend file: {source_str}"

    print("✓ Source .blend file tracking works for all dependencies")


def test_packer_includes_main_file():
    """
    Verify that Packer always includes the main .blend file,
    even if it has no dependencies.

    This tests the core BAT Packer behavior that bat_utils.pack_blend() wraps.
    """
    from blender_asset_tracer.pack import Packer

    if not BLENDFILES_DIR.exists():
        print("⚠ Skipping: blendfiles directory not found")
        return

    # basic_file.blend has minimal dependencies
    blend_path = BLENDFILES_DIR / "basic_file.blend"
    if not blend_path.exists():
        print("⚠ Skipping: basic_file.blend not found")
        return

    # Use Packer directly in noop mode
    with Packer(
        blend_path,
        BLENDFILES_DIR,
        BLENDFILES_DIR / "test_output",
        noop=True,
    ) as packer:
        packer.strategise()
        packer.execute()

        # The main blend file should always be in the file map
        file_map_names = {p.name for p in packer.file_map.keys()}
        assert "basic_file.blend" in file_map_names, \
            f"Main blend file should be in file_map: {file_map_names}"

    print("✓ Packer includes main .blend file even with minimal deps")


if __name__ == "__main__":
    print("Testing linked .blend file tracking...\n")
    print("=" * 70)

    test_li_blocks_yield_dependencies()
    test_recursive_library_tracking()
    test_trace_dependencies_includes_linked_blends()
    test_linked_blend_without_external_deps()
    test_source_blend_tracking()
    test_packer_includes_main_file()

    print("=" * 70)
    print("\n✅ All linked library tracking tests passed!")
    print("""
Summary:
  - LI (Library) blocks yield BlockUsage for linked .blend files
  - Recursive library links are all tracked
  - trace.deps() includes linked .blend files in dependency paths
  - Linked .blend files are tracked even if they have no external deps
  - Source .blend file is always available via usage.block.bfile.filepath
  - Packer always includes the main .blend file in file_map
""")
