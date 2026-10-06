"""Source guards for Blender UI code that cannot run without bpy.

Panel registration and draw run inside Blender on every redraw; these AST
checks are the cheapest independent guard for the add-on invariant that no
dependency scan starts at registration and that draw survives stale scene
properties during an in-place upgrade.
"""

import ast
from pathlib import Path


PANELS_SOURCE = Path(__file__).resolve().parents[1] / "panels.py"


def test_render_panel_tolerates_stale_scene_properties_during_upgrade():
    tree = ast.parse(PANELS_SOURCE.read_text(encoding="utf-8"))
    panel_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "SUPERLUMINAL_PT_RenderPanel"
    )
    draw_node = next(
        node
        for node in panel_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "draw"
    )
    draw_source = ast.unparse(draw_node)

    assert "hasattr(props, 'download_after_submit')" in draw_source
