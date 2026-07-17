"""Append one processed artifact and verify its exact immutable identity in Blender."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--immutable-id", required=True)
    return parser.parse_args(values)


options = arguments()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.preferences.filepaths.use_scripts_auto_execute = False
with bpy.data.libraries.load(str(options.artifact.resolve()), link=False, assets_only=True) as (
    data_from,
    data_to,
):
    if data_from.objects != [options.name]:
        raise RuntimeError("downloaded artifact listing does not expose the exact OBJECT")
    data_to.objects = [options.name]

loaded = [item for item in data_to.objects if item is not None]
if len(loaded) != 1 or loaded[0].get("sulu_market_asset_id") != options.immutable_id:
    raise RuntimeError("downloaded artifact did not preserve exact immutable identity")
if loaded[0].asset_data is None or loaded[0].type != "MESH":
    raise RuntimeError("downloaded artifact did not append the expected marked mesh OBJECT")
bpy.context.scene.collection.objects.link(loaded[0])
if bpy.context.scene.objects.get(options.name) is not loaded[0]:
    raise RuntimeError("downloaded artifact was not linked into the scene")
print("SULU_ASSET_PROCESSOR_IMPORT_OK")
