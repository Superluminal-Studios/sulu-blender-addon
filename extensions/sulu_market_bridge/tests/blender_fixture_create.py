"""Create a minimal marked OBJECT asset fixture in real Blender 5.2."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


def arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


output = Path(arguments()[0]).resolve()
output.parent.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
fixture = bpy.context.active_object
fixture.name = "SuluFixtureObject"
fixture.data.name = "SuluFixtureMesh"
fixture["sulu_market_asset_id"] = "asset:sulu-fixture:v1"
fixture.asset_mark()
fixture.use_fake_user = True
bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)

if not output.is_file() or output.stat().st_size <= 0:
    raise RuntimeError("Blender did not create the fixture file")
print(f"SULU_FIXTURE_CREATED size={output.stat().st_size}")
