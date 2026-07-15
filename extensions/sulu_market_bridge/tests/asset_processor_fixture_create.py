"""Create hostile-input processor fixtures using official Blender 5.2."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import bpy


def arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--kind",
        required=True,
        choices=("valid", "unsupported", "unmarked", "conflicting"),
    )
    return parser.parse_args(values)


def marked_object(name: str, location: tuple[float, float, float]) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = f"{name}Mesh"
    obj.asset_mark()
    obj.use_fake_user = True
    return obj


options = arguments()
output = options.output.resolve()
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.preferences.filepaths.use_scripts_auto_execute = False

if options.kind == "valid":
    chair = marked_object("Chair", (0.0, 0.0, 0.0))
    chair.asset_data.author = "Sulu Fixture"
    chair.asset_data.description = "A dependency-complete chair fixture"
    chair.asset_data.license = "CC0-1.0"
    chair.asset_data.tags.new("chair")
    chair.asset_data.tags.new("wood")
    chair.asset_data.catalog_id = str(uuid.UUID("2bd854d0-23ca-4e5a-b573-18237c80a7f6"))

    table = marked_object("Table", (3.0, 0.0, 0.0))
    table.asset_data.author = "Sulu Fixture"
    table.asset_data.description = "A second independent OBJECT asset"
    table.asset_data.license = "CC0-1.0"
    table.asset_data.tags.new("table")
elif options.kind == "unsupported":
    material = bpy.data.materials.new("UnsupportedMaterial")
    material.asset_mark()
    material.use_fake_user = True
elif options.kind == "unmarked":
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    bpy.context.active_object.name = "NotAnAsset"
else:
    conflict = marked_object("ConflictingObject", (0.0, 0.0, 0.0))
    conflict["sulu_market_asset_id"] = "seller-controlled-value"

bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False, compress=True)
if not output.is_file() or output.stat().st_size <= 12:
    raise RuntimeError("fixture creation did not produce a Blender file")
print(f"SULU_ASSET_PROCESSOR_FIXTURE_OK kind={options.kind} size={output.stat().st_size}")
