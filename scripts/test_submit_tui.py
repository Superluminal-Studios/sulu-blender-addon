#!/usr/bin/env python3
"""
test_submit_tui.py - Test script for the submit TUI.

Run from the addon directory:
    python scripts/test_submit_tui.py

Or with --plain for plain text mode:
    python scripts/test_submit_tui.py --plain
"""
from __future__ import annotations

import sys
import time
import random
from pathlib import Path

# Add parent to path for imports so bundled rich/tqdm are available
addon_dir = Path(__file__).parent.parent
sys.path.insert(0, str(addon_dir.parent))  # parent of addon so 'sulu_blender_addon.rich' works
sys.path.insert(0, str(addon_dir))  # addon dir itself

# Create a fake package module for relative imports to work
import types
pkg_name = addon_dir.name.replace("-", "_")
pkg = types.ModuleType(pkg_name)
pkg.__path__ = [str(addon_dir)]
sys.modules[pkg_name] = pkg

# Now import the module
import importlib
submit_tui = importlib.import_module(f"{pkg_name}.utils.submit_tui")
SubmitTUI = submit_tui.SubmitTUI
RICH_AVAILABLE = submit_tui.RICH_AVAILABLE


def simulate_trace(tui: SubmitTUI, num_files: int = 50):
    """Simulate the tracing phase."""
    tui.set_phase("trace")
    tui.trace_blendfile("/path/to/project/scene.blend")

    # Simulated datablock types
    block_types = [
        "Image",
        "Material",
        "Mesh",
        "Object",
        "Collection",
        "Texture",
        "NodeTree",
        "Library",
        "Armature",
        "Action",
    ]

    # Simulated file paths
    file_templates = [
        "/textures/diffuse_{:03}.png",
        "/textures/normal_{:03}.exr",
        "/textures/roughness_{:03}.png",
        "/models/asset_{:03}.blend",
        "/hdri/env_{:03}.hdr",
        "/cache/fluid_{:03}.vdb",
        "/sounds/effect_{:03}.wav",
        "/fonts/custom_{:03}.ttf",
    ]

    for i in range(num_files):
        # Trace a datablock
        block_type = random.choice(block_types)
        block_name = f"{block_type.lower()}_{i:03}"
        tui.trace_datablock(block_type, block_name)

        # Trace a file with random status
        file_template = random.choice(file_templates)
        file_path = "/path/to/project" + file_template.format(i)

        # Most files are OK, some missing, few unreadable
        r = random.random()
        if r < 0.03:
            status = "missing"
        elif r < 0.05:
            status = "unreadable"
        else:
            status = "ok"

        tui.trace_file(file_path, status=status)

        time.sleep(0.02)  # Simulate work

    tui.trace_done()


def simulate_pack(tui: SubmitTUI, num_files: int = 50, mode: str = "PROJECT"):
    """Simulate the packing phase."""
    tui.set_phase("pack")
    tui.pack_start(total_files=num_files, mode=mode)

    # File templates for variety
    file_templates = [
        "/textures/diffuse_{:03}.png",
        "/textures/normal_{:03}.exr",
        "/models/asset_{:03}.blend",
        "/hdri/env_{:03}.hdr",
        "/cache/fluid_{:03}.vdb",
    ]

    for i in range(num_files):
        file_template = random.choice(file_templates)
        file_path = f"/path/to/project{file_template.format(i)}"
        size = random.randint(10000, 5000000)  # 10KB to 5MB

        # Most files pack OK, occasional issues
        r = random.random()
        if r < 0.03:
            tui.pack_missing(file_path)
        elif r < 0.05:
            tui.pack_unreadable(file_path, "PermissionError")
        elif r < 0.10:
            # Skipped file (already exists)
            tui.pack_file(file_path, size, method="skip")
        else:
            # Normal pack - method determined by mode
            pack_method = "compress" if mode == "ZIP" else "map"
            tui.pack_file(file_path, size, method=pack_method)

        # Rewrite a blend file occasionally
        if random.random() < 0.08 and i % 8 == 0:
            tui.pack_rewrite(f"/path/to/project/lib_{i // 8}.blend")

        time.sleep(0.025)  # Simulate work

    tui.pack_done()


def simulate_upload(tui: SubmitTUI, total_bytes: int = 100_000_000, mode: str = "PROJECT", include_addons: bool = True):
    """Simulate the upload phase based on mode."""
    tui.set_phase("upload")

    if mode == "ZIP":
        # ZIP mode: Main Zip + optional Addons
        zip_size = int(total_bytes * 0.9)
        tui.upload_start(phase="zip", total_bytes=zip_size, total_files=1)

        for i in range(30):
            tui.upload_progress(
                bytes_transferred=int(zip_size * (i + 1) / 30),
                bytes_total=zip_size,
                current_file="project.zip",
            )
            time.sleep(0.04)

        tui.upload_file_done("project.zip")
        tui.upload_phase_done("zip")
        time.sleep(0.1)

    else:
        # PROJECT mode: Main Blend + Dependencies
        blend_size = int(total_bytes * 0.2)
        tui.upload_start(phase="blend", total_bytes=blend_size, total_files=1)

        for i in range(20):
            tui.upload_progress(
                bytes_transferred=int(blend_size * (i + 1) / 20),
                bytes_total=blend_size,
                current_file="scene.blend",
            )
            time.sleep(0.04)

        tui.upload_file_done("scene.blend")
        tui.upload_phase_done("blend")
        time.sleep(0.1)

        # Dependencies
        deps_size = int(total_bytes * 0.7)
        num_deps = 40
        tui.upload_start(phase="deps", total_bytes=deps_size, total_files=num_deps)

        for i in range(num_deps):
            file_name = f"textures/file_{i:03}.png"
            tui.upload_progress(
                bytes_transferred=int(deps_size * (i + 1) / num_deps),
                bytes_total=deps_size,
                current_file=file_name,
            )
            time.sleep(0.025)
            tui.upload_file_done(file_name)

        tui.upload_phase_done("deps")
        time.sleep(0.1)

    # Addons (optional, for both modes)
    if include_addons:
        addon_size = int(total_bytes * 0.1)
        tui.upload_start(phase="addons", total_bytes=addon_size, total_files=2)

        for i in range(10):
            tui.upload_progress(
                bytes_transferred=int(addon_size * (i + 1) / 10),
                bytes_total=addon_size,
                current_file="addon_pack.zip",
            )
            time.sleep(0.025)

        tui.upload_file_done("addon_pack.zip")
        tui.upload_phase_done("addons")
        time.sleep(0.1)

    tui.upload_done()


def simulate_update_dialog(tui: SubmitTUI):
    """Simulate showing an update dialog."""
    tui.show_update_dialog(current_version="1.2.3", new_version="1.3.0")
    time.sleep(1.5)  # Show dialog briefly
    tui.clear_question()


def simulate_browser_dialog(tui: SubmitTUI):
    """Simulate showing a browser dialog after completion."""
    tui.show_browser_dialog(job_name="demo_scene_001")
    time.sleep(1.5)  # Show dialog briefly
    tui.clear_question()
    tui.finish(success=True, message="Job submitted!")


def main():
    """Run the TUI demo."""
    plain_mode = "--plain" in sys.argv
    force_tui = "--force" in sys.argv  # Force TUI even in non-TTY
    zip_mode = "--zip" in sys.argv     # Test ZIP mode instead of PROJECT
    no_addons = "--no-addons" in sys.argv
    skip_dialogs = "--no-dialogs" in sys.argv
    use_tui = force_tui or (RICH_AVAILABLE and not plain_mode)

    upload_type = "ZIP" if zip_mode else "PROJECT"
    include_addons = not no_addons

    if not use_tui:
        print(f"Rich available: {RICH_AVAILABLE}")
        print(f"Plain mode: {plain_mode}")
        print(f"Upload type: {upload_type}")
        print(f"Include addons: {include_addons}")
        print()

    # Create TUI
    tui = SubmitTUI(
        blend_name="demo_scene.blend",
        project_name="MyProject",
        upload_type=upload_type,
        plain_mode=plain_mode,
        force_tui=force_tui,
        include_addons=include_addons,
    )

    try:
        tui.start()

        # Show update dialog first (unless skipped)
        if not skip_dialogs and use_tui:
            simulate_update_dialog(tui)

        simulate_trace(tui, num_files=80)
        time.sleep(0.3)

        simulate_pack(tui, num_files=60, mode=upload_type)
        time.sleep(0.3)

        simulate_upload(tui, total_bytes=150_000_000, mode=upload_type, include_addons=include_addons)
        time.sleep(0.3)

        # Show browser dialog after success (unless skipped)
        if not skip_dialogs and use_tui:
            simulate_browser_dialog(tui)
        else:
            tui.finish(success=True, message="Job submitted successfully!")

    except KeyboardInterrupt:
        tui.finish(success=False, message="Cancelled by user")
        sys.exit(1)

    except Exception as e:
        tui.finish(success=False, message=str(e))
        raise


if __name__ == "__main__":
    main()
