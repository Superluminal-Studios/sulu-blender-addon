"""Linked .blend libraries are submission dependencies.

Regression: linked libraries without external files of their own were
dropped. BAT's own LI-block tracing is covered in tests/bat; this guards the
add-on's trace_dependencies() wrapper that decides what gets uploaded.
"""
import importlib
from pathlib import Path

addon_dir = Path(__file__).parent.parent
bat_utils = importlib.import_module(addon_dir.name + ".utils.bat_utils")

BLENDFILES_DIR = addon_dir / "tests" / "bat" / "blendfiles"


def test_trace_dependencies_includes_direct_and_transitive_libraries():
    dep_paths, missing, unreadable, _raw_usages, _optional = (
        bat_utils.trace_dependencies(BLENDFILES_DIR / "doubly_linked.blend", hydrate=False)
    )

    names = {path.name for path in dep_paths}
    assert {"linked_cube.blend", "basic_file.blend", "material_textures.blend"} <= names
    assert not missing
    assert not unreadable
