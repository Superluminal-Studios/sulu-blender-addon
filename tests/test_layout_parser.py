from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent


def _load_module_directly(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_layout_parser = _load_module_directly(
    "layout_parser",
    _addon_dir / "transfers" / "submit" / "layout_parser.py",
)


class LayoutParserTests(unittest.TestCase):
    def test_native_geometry_and_property_presentation_survive_export(self):
        source = '''
from bpy.types import Panel
class TEST_PT_layout(Panel):
    bl_label = 'Layout'
    bl_context = 'output'
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(context.scene.render, 'resolution_x')
        layout.use_property_split = False
        split = layout.split(factor=0.4)
        col = split.column(align=True)
        col.alignment = 'RIGHT'
        col.label(text='Color Space')
        col = split.column()
        col.scale_y = 1.5
        col.active = context.scene.render.use_border
        col.prop(context.scene.render, 'resolution_y')
        grid = layout.grid_flow(columns=2, row_major=True, even_columns=True)
        grid.prop(context.scene.render, 'fps', expand=True)
        layout.separator(factor=0.5)
'''
        doc = _layout_parser.build_layout({'test.py': source})
        self.assertEqual(doc['layout_version'], 2)
        items = doc['panels'][0]['items']
        self.assertTrue(items[0]['presentation']['property_split'])
        split = items[1]
        self.assertEqual(split['kind'], 'split')
        self.assertEqual(split['options']['factor'], 0.4)
        label_col, field_col = split['items']
        self.assertEqual(label_col['items'][0]['align'], 'right')
        self.assertEqual(field_col['options']['scale_y'], 1.5)
        field = field_col['items'][0]
        self.assertFalse(field['presentation']['property_split'])
        self.assertFalse(field['presentation']['property_decorate'])
        self.assertEqual(field['enabled'], {'op': 'get', 'path': 'render.use_border'})
        self.assertEqual(items[2]['options']['columns'], 2)
        self.assertEqual(items[3]['factor'], 0.5)


if __name__ == "__main__":
    unittest.main()
