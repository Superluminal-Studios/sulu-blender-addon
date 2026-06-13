from __future__ import annotations

import importlib.util
import sys
import textwrap
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


# A condensed bl_ui-style module exercising the conventions the translator
# must understand (mixins, aliases, branches, headings, helpers, polls).
FIXTURE = textwrap.dedent(
    '''
    from bpy.types import Panel, Menu
    from bl_ui.utils import PresetPanel


    class FakeButtonsPanel:
        bl_space_type = 'PROPERTIES'
        bl_region_type = 'WINDOW'
        bl_context = "render"

        @classmethod
        def poll(cls, context):
            return (context.engine in cls.COMPAT_ENGINES)


    class FAKE_PT_presets(PresetPanel, Panel):
        bl_label = "Presets"


    class FAKE_MT_menu(Menu):
        bl_label = "A Menu"

        def draw(self, context):
            self.layout.label(text="menu")


    def helper_flag(context):
        return context.scene.cycles.use_thing


    def draw_extra(layout, context):
        cscene = context.scene.cycles
        layout.prop(cscene, "extra_prop", text="Extra")


    class FAKE_PT_main(FakeButtonsPanel, Panel):
        bl_label = "Main"
        bl_options = {'DEFAULT_CLOSED'}
        bl_order = 5
        COMPAT_ENGINES = {'CYCLES'}

        def draw_header(self, context):
            self.layout.prop(context.scene.cycles, "use_main", text="")

        def draw(self, context):
            layout = self.layout
            layout.use_property_split = True
            scene = context.scene
            cscene = scene.cycles
            rd = scene.render

            heading = layout.column(align=True, heading="Threshold")
            row = heading.row(align=True)
            row.prop(cscene, "use_adaptive", text="")
            sub = row.row()
            sub.active = cscene.use_adaptive
            sub.prop(cscene, "threshold", text="")

            col = layout.column(align=True)
            if cscene.use_adaptive:
                col.prop(cscene, "samples", text="Max Samples")
            else:
                col.prop(cscene, "samples", text="Samples")

            if rd.mode in {'A', 'B'}:
                col.prop(rd, "mode_prop")

            if helper_flag(context):
                col.prop(cscene, "helper_gated")

            col.separator()
            layout.label(text="Note")
            layout.template_curve_mapping(cscene, "curve")
            draw_extra(layout, context)


    class FAKE_PT_child(FakeButtonsPanel, Panel):
        bl_label = "Child"
        bl_parent_id = "FAKE_PT_main"
        COMPAT_ENGINES = {'CYCLES'}

        def draw(self, context):
            rd = context.scene.render
            layout = self.layout
            if not rd.use_feature:
                return
            layout.prop(rd, "feature_amount")


    class FAKE_PT_dev(FakeButtonsPanel, Panel):
        bl_label = "Debug"
        COMPAT_ENGINES = {'CYCLES'}

        @classmethod
        def poll(cls, context):
            prefs = context.preferences
            return prefs.view.show_developer_ui

        def draw(self, context):
            self.layout.prop(context.scene.cycles, "debug_prop")


    class FAKE_PT_layer(Panel):
        bl_space_type = 'PROPERTIES'
        bl_region_type = 'WINDOW'
        bl_context = "view_layer"
        bl_label = "Layer Things"
        bl_options = {'HIDE_HEADER'}

        def draw(self, context):
            layout = self.layout
            view_layer = context.view_layer
            layout.prop(view_layer, "use_pass_z")
            layout.prop(view_layer.cycles, "use_denoising", text="Denoise")


    class FAKE_PT_output(Panel):
        bl_space_type = 'PROPERTIES'
        bl_region_type = 'WINDOW'
        bl_context = "output"
        bl_label = "Format"
        COMPAT_ENGINES = {'BLENDER_RENDER', 'BLENDER_EEVEE'}

        @staticmethod
        def draw_framerate(layout, rd):
            layout.prop(rd, "fps")
            layout.prop(rd, "fps_base", text="Base")

        def draw(self, context):
            layout = self.layout
            rd = context.scene.render
            layout.prop(rd, "resolution_x", text="Resolution X")
            layout.prop(rd, "views_format", expand=True)
            self.draw_framerate(layout, rd)
            layout.template_image_settings(rd.image_settings, color_management=False)


    class FAKE_PT_excluded(Panel):
        bl_space_type = 'PROPERTIES'
        bl_region_type = 'WINDOW'
        bl_context = "output"
        bl_label = "Excluded"
        COMPAT_ENGINES = {'BLENDER_RENDER'}

        def draw(self, context):
            self.layout.prop(context.scene.render, "dither_intensity")


    class FAKE_PT_dev_composed(FakeButtonsPanel, Panel):
        bl_label = "Debug Composed"
        COMPAT_ENGINES = {'CYCLES'}

        @classmethod
        def poll(cls, context):
            return FAKE_PT_dev.poll(context) and context.scene is not None

        def draw(self, context):
            self.layout.prop(context.scene.cycles, "debug_prop2")


    class FakeShadingMixin(FakeButtonsPanel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'


    class FAKE_VIEW3D_PT_shading(FakeShadingMixin, Panel):
        bl_label = "Render Pass"
        COMPAT_ENGINES = {'CYCLES'}

        def draw(self, context):
            self.layout.prop(context.scene.cycles, "render_pass", text="")


    def get_panels():
        exclude_panels = {
            'FAKE_PT_excluded',
        }
        panels = []
        return panels


    classes = (
        FAKE_PT_output,
        FAKE_PT_excluded,
        FAKE_PT_layer,
        FAKE_PT_main,
        FAKE_PT_child,
    )
    '''
)


def build():
    doc = _layout_parser.build_layout({"fixture": FIXTURE})
    assert doc is not None
    return {p["id"]: p for p in doc["panels"]}, doc


def find_props(items):
    out = []
    for node in items:
        if node.get("t") == "prop":
            out.append(node)
        out.extend(find_props(node.get("items", [])))
    return out


class LayoutParserTests(unittest.TestCase):
    def test_panel_metadata_and_exclusions(self):
        panels, doc = build()
        self.assertIn("FAKE_PT_main", panels)
        self.assertIn("FAKE_PT_child", panels)
        self.assertIn("FAKE_PT_layer", panels)
        # menus, preset panels, and developer-only panels never ship
        self.assertNotIn("FAKE_MT_menu", panels)
        self.assertNotIn("FAKE_PT_presets", panels)
        self.assertNotIn("FAKE_PT_dev", panels)
        # 3D-viewport panels reusing the buttons mixins stay out of the
        # properties editor (Cycles' shading popovers)
        self.assertNotIn("FAKE_VIEW3D_PT_shading", panels)
        # dev gates hidden behind a delegated Mixin.poll(context) call
        self.assertNotIn("FAKE_PT_dev_composed", panels)

        main = panels["FAKE_PT_main"]
        self.assertEqual(main["context"], "render")
        self.assertEqual(main["engines"], ["CYCLES"])
        self.assertEqual(main["order"], 5)
        self.assertTrue(main["default_closed"])
        self.assertEqual(main["header_toggle"], "cycles.use_main")
        self.assertEqual(panels["FAKE_PT_child"]["parent"], "FAKE_PT_main")
        self.assertTrue(panels["FAKE_PT_layer"]["hide_header"])

    def test_heading_group_and_enabled(self):
        panels, _ = build()
        items = panels["FAKE_PT_main"]["items"]
        group = items[0]
        self.assertEqual(group["t"], "group")
        self.assertEqual(group["heading"], "Threshold")
        toggle, threshold = find_props(group["items"])
        self.assertEqual(toggle["path"], "cycles.use_adaptive")
        self.assertEqual(toggle["text"], "")
        self.assertEqual(threshold["path"], "cycles.threshold")
        self.assertEqual(threshold["enabled"], {"op": "get", "path": "cycles.use_adaptive"})

    def test_branch_visibility_through_captured_container(self):
        panels, _ = build()
        props = find_props(panels["FAKE_PT_main"]["items"])
        max_samples = next(p for p in props if p.get("text") == "Max Samples")
        plain_samples = next(p for p in props if p.get("text") == "Samples")
        self.assertEqual(max_samples["visible"], {"op": "get", "path": "cycles.use_adaptive"})
        self.assertEqual(
            plain_samples["visible"],
            {"op": "not", "args": [{"op": "get", "path": "cycles.use_adaptive"}]},
        )

    def test_in_compare_and_helper_inline(self):
        panels, _ = build()
        props = find_props(panels["FAKE_PT_main"]["items"])
        mode_prop = next(p for p in props if p["path"] == "render.mode_prop")
        self.assertEqual(
            mode_prop["visible"],
            {"op": "in", "path": "render.mode", "values": ["A", "B"]},
        )
        helper_gated = next(p for p in props if p["path"] == "cycles.helper_gated")
        self.assertEqual(helper_gated["visible"], {"op": "get", "path": "cycles.use_thing"})

    def test_draw_helper_inlining_and_misc_nodes(self):
        panels, _ = build()
        items = panels["FAKE_PT_main"]["items"]
        props = find_props(items)
        self.assertTrue(any(p["path"] == "cycles.extra_prop" for p in props))
        kinds = [n.get("kind") for n in items if n.get("t") == "skipped"]
        self.assertIn("template_curve_mapping", kinds)
        self.assertTrue(any(n.get("t") == "label" and n["text"] == "Note" for n in items))
        self.assertTrue(any(n.get("t") == "sep" for n in items))

    def test_early_return_inverts_rest(self):
        panels, _ = build()
        props = find_props(panels["FAKE_PT_child"]["items"])
        self.assertEqual(props[0]["path"], "render.feature_amount")
        self.assertEqual(props[0]["visible"], {"op": "get", "path": "render.use_feature"})

    def test_view_layer_paths(self):
        panels, _ = build()
        props = find_props(panels["FAKE_PT_layer"]["items"])
        self.assertEqual(props[0]["path"], "@layer.use_pass_z")
        self.assertEqual(props[1]["path"], "@layer.cycles.use_denoising")

    def test_static_method_helper_inlines_and_template_expands(self):
        panels, _ = build()
        output = panels["FAKE_PT_output"]
        props = find_props(output["items"])
        paths = [p["path"] for p in props]
        self.assertIn("render.resolution_x", paths)
        # self.draw_framerate(layout, rd) inlined
        self.assertIn("render.fps", paths)
        self.assertIn("render.fps_base", paths)
        # template_image_settings expands to a struct_props node
        structs = [n for n in output["items"] if n.get("t") == "struct_props"]
        self.assertEqual(structs, [{"t": "struct_props", "path": "render.image_settings"}])
        # expand=True survives translation (web renders a segmented row)
        views = next(p for p in props if p["path"] == "render.views_format")
        self.assertTrue(views.get("expand"))
        self.assertFalse(any(p.get("expand") for p in props if p["path"] == "render.resolution_x"))

    def test_panels_follow_registration_tuple_order(self):
        _, doc = build()
        ids = [p["id"] for p in doc["panels"]]
        # the classes = (...) tuple, not definition order, drives panel order
        self.assertLess(ids.index("FAKE_PT_output"), ids.index("FAKE_PT_main"))
        self.assertLess(ids.index("FAKE_PT_layer"), ids.index("FAKE_PT_main"))

    def test_cycles_adoption_respects_exclude_list(self):
        panels, _ = build()
        # FAKE_PT_output carries BLENDER_RENDER and a CYCLES panel exists in
        # the fixture → adopted; FAKE_PT_excluded is in get_panels excludes
        self.assertIn("CYCLES", panels["FAKE_PT_output"]["engines"])
        self.assertNotIn("CYCLES", panels["FAKE_PT_excluded"]["engines"])

    def test_real_blender_sources_translate_when_available(self):
        base = Path(
            "/Users/jonasdichelle/Library/Application Support/current-blenders/"
            "Blender Versions.noindex/blender-5.1.1-macos-arm64/"
            "Blender.app/Contents/Resources/5.1/scripts"
        )
        if not base.exists():
            self.skipTest("no local Blender build")
        sources = {
            "properties_render": (base / "startup/bl_ui/properties_render.py").read_text(),
            "properties_output": (base / "startup/bl_ui/properties_output.py").read_text(),
            "properties_view_layer": (base / "startup/bl_ui/properties_view_layer.py").read_text(),
            "cycles_ui": (base / "addons_core/cycles/ui.py").read_text(),
        }
        doc = _layout_parser.build_layout(sources)
        self.assertIsNotNone(doc)
        panels = doc["panels"]
        self.assertGreater(len(panels), 80)
        prop_count = sum(len(find_props(p["items"])) for p in panels)
        self.assertGreater(prop_count, 250)
        contexts = {p["context"] for p in panels}
        self.assertEqual(contexts, {"render", "output", "view_layer"})


if __name__ == "__main__":
    unittest.main()
