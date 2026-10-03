"""Path identity used by bat_utils when matching traced and missing files."""
import importlib
from pathlib import Path

from blender_asset_tracer import bpathlib

# bat_utils uses relative imports, so it must load in its package context;
# the conftest stub provides the addon parent package without importing bpy.
bat_utils = importlib.import_module(Path(__file__).parent.parent.name + ".utils.bat_utils")


def test_dotdot_spellings_of_one_file_match_after_normalization():
    direct = bpathlib.make_absolute(Path("/home/user/project/textures/wood.png"))
    via_dotdot = bpathlib.make_absolute(
        Path("/home/user/project/scenes/../textures/wood.png")
    )

    assert via_dotdot == direct
    assert via_dotdot in {direct}
    assert bat_utils._norm_path(str(direct)) == str(direct).replace("\\", "/")
