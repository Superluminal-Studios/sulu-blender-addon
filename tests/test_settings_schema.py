from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent


def _load_module_directly(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_settings_schema = _load_module_directly(
    "settings_schema",
    _addon_dir / "transfers" / "submit" / "settings_schema.py",
)


def _enum_item(identifier: str, name: str = "", description: str = ""):
    return SimpleNamespace(identifier=identifier, name=name or identifier, description=description)


def _prop(identifier: str, prop_type: str, **overrides):
    values = {
        "identifier": identifier,
        "name": identifier.replace("_", " ").title(),
        "description": f"{identifier} description",
        "type": prop_type,
        "subtype": "NONE",
        "unit": "NONE",
        "is_readonly": False,
        "is_hidden": False,
        "array_length": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _struct(props, **values):
    """Fake RNA struct: current values as attributes plus a bl_rna walk."""
    rna_type = _prop("rna_type", "POINTER")
    struct = SimpleNamespace(**values)
    struct.bl_rna = SimpleNamespace(properties=[rna_type, *props])
    return struct


class _LockedEnumStruct:
    """Fake struct whose dynamic enums reject invalid values the way Blender
    does, including the TypeError message listing valid identifiers."""

    def __init__(self, locked, **values):
        object.__setattr__(self, "_locked", dict(locked))
        for key, value in values.items():
            object.__setattr__(self, key, value)

    def __setattr__(self, name, value):
        locked = self._locked.get(name)
        if locked is not None and value not in locked:
            options = ", ".join(f"'{item}'" for item in locked)
            raise TypeError(
                f'bpy_struct: item.attr = val: enum "{value}" not found in ({options})'
            )
        object.__setattr__(self, name, value)


class _FakeRenderEngineBase:
    pass


class _FakeCyclesEngine(_FakeRenderEngineBase):
    bl_idname = "CYCLES"
    bl_label = "Cycles"


def _fake_bpy():
    return SimpleNamespace(
        types=SimpleNamespace(RenderEngine=_FakeRenderEngineBase),
        app=SimpleNamespace(version_string="4.5.9"),
    )


def _make_view_settings():
    view_settings = _LockedEnumStruct(
        {"view_transform": ("Standard", "AgX", "Filmic"), "look": ("None", "Punchy")},
        view_transform="AgX",
        look="None",
        exposure=0.5,
    )
    object.__setattr__(
        view_settings,
        "bl_rna",
        SimpleNamespace(
            properties=[
                _prop("rna_type", "POINTER"),
                _prop("view_transform", "ENUM", enum_items=[_enum_item("Standard")]),
                _prop("look", "ENUM", enum_items=[_enum_item("None")]),
                _prop("exposure", "FLOAT", soft_min=-10.0, soft_max=10.0, precision=3),
            ]
        ),
    )
    return view_settings


def _make_display_settings():
    display_settings = _LockedEnumStruct(
        {"display_device": ("sRGB", "Display P3")},
        display_device="sRGB",
    )
    object.__setattr__(
        display_settings,
        "bl_rna",
        SimpleNamespace(
            properties=[
                _prop("display_device", "ENUM", enum_items=[_enum_item("sRGB")]),
            ]
        ),
    )
    return display_settings


def _make_scene():
    image_settings = _struct(
        [
            _prop(
                "file_format",
                "ENUM",
                enum_items=[_enum_item("PNG"), _enum_item("OPEN_EXR", "OpenEXR")],
            ),
        ],
        file_format="OPEN_EXR",
    )
    render = _struct(
        [
            _prop(
                "resolution_x",
                "INT",
                subtype="PIXEL",
                default=1920,
                soft_min=4,
                soft_max=65536,
                hard_min=4,
                hard_max=65536,
                step=1,
            ),
            _prop(
                "stamp_foreground",
                "FLOAT",
                subtype="COLOR",
                array_length=4,
                default_array=(0.8, 0.8, 0.8, 1.0),
            ),
            _prop(
                "engine",
                "ENUM",
                default="BLENDER_EEVEE_NEXT",
                enum_items=[_enum_item("BLENDER_EEVEE_NEXT", "EEVEE")],
            ),
            _prop("filepath", "STRING", is_hidden=True),
            _prop("file_extension", "STRING", is_readonly=True),
            _prop("bake", "POINTER"),
            _prop("weird", "FLOAT"),
        ],
        resolution_x=1920,
        stamp_foreground=(0.8, 0.8, 0.8, 1.0),
        engine="CYCLES",
        filepath="/tmp/out",
        file_extension=".png",
        bake=object(),
        weird=object(),
        image_settings=image_settings,
    )
    cycles = _struct(
        [_prop("samples", "INT", default=4096, soft_min=1, soft_max=4096)],
        samples=128,
    )
    layer_cycles = _struct(
        [_prop("use_denoising", "BOOLEAN", default=True)],
        use_denoising=False,
    )
    view_layer = _struct(
        [_prop("use_pass_z", "BOOLEAN", default=False)],
        name="Beauty",
        use_pass_z=True,
        cycles=layer_cycles,
    )
    return SimpleNamespace(
        render=render,
        cycles=cycles,
        view_layers=[view_layer],
        view_settings=_make_view_settings(),
        display_settings=_make_display_settings(),
        world=SimpleNamespace(name="World"),
        camera=SimpleNamespace(name="Camera_A"),
    )


class TestCollectSettingsSchema(unittest.TestCase):
    def test_schema_emits_expected_groups_and_fields(self):
        scene = _make_scene()
        schema, schema_key = _settings_schema.collect_settings_schema(scene, _fake_bpy())

        self.assertEqual(schema["schema_version"], 1)
        self.assertEqual(schema["blender_version"], "4.5.9")
        groups = {group["id"]: group for group in schema["groups"]}
        # eevee group is absent because the fake scene has no eevee struct.
        self.assertEqual(
            list(groups.keys()),
            [
                "render",
                "render.image_settings",
                "cycles",
                "view_layer",
                "view_layer.cycles",
                "view_settings",
                "display_settings",
            ],
        )
        self.assertEqual(groups["render.image_settings"]["label"], "Output")
        self.assertEqual(groups["cycles"]["engine"], "CYCLES")
        self.assertNotIn("engine", groups["render"])
        self.assertFalse(groups["render"]["per_layer"])
        self.assertTrue(groups["view_layer"]["per_layer"])
        self.assertEqual(groups["view_layer.cycles"]["engine"], "CYCLES")
        self.assertEqual(groups["view_settings"]["label"], "Color Management")

        render_props = {prop["identifier"]: prop for prop in groups["render"]["properties"]}
        resolution = render_props["resolution_x"]
        self.assertEqual(resolution["path"], "render.resolution_x")
        self.assertEqual(resolution["type"], "INT")
        self.assertEqual(resolution["subtype"], "PIXEL")
        self.assertEqual(resolution["default"], 1920)
        self.assertEqual(resolution["soft_min"], 4)
        self.assertEqual(resolution["soft_max"], 65536)
        self.assertEqual(resolution["array_length"], 0)
        self.assertIsNone(resolution["enum"])
        for field in (
            "identifier",
            "name",
            "description",
            "type",
            "subtype",
            "unit",
            "default",
            "soft_min",
            "soft_max",
            "hard_min",
            "hard_max",
            "step",
            "precision",
            "array_length",
            "enum",
        ):
            self.assertIn(field, resolution)

        # Array defaults are coerced to plain lists.
        self.assertEqual(render_props["stamp_foreground"]["default"], [0.8, 0.8, 0.8, 1.0])
        self.assertEqual(render_props["stamp_foreground"]["array_length"], 4)

        # rna_type, hidden, readonly, and pointer properties are skipped.
        self.assertNotIn("rna_type", render_props)
        self.assertNotIn("filepath", render_props)
        self.assertNotIn("file_extension", render_props)
        self.assertNotIn("bake", render_props)

        format_prop = groups["render.image_settings"]["properties"][0]
        self.assertEqual(format_prop["path"], "render.image_settings.file_format")
        self.assertEqual(format_prop["enum"][1]["name"], "OpenEXR")

        self.assertRegex(schema_key, r"^bl459-[0-9a-f]{16}$")

    def test_schema_key_is_deterministic(self):
        _, key_a = _settings_schema.collect_settings_schema(_make_scene(), _fake_bpy())
        _, key_b = _settings_schema.collect_settings_schema(_make_scene(), _fake_bpy())
        self.assertEqual(key_a, key_b)

    def test_per_layer_paths_are_layer_relative(self):
        schema, _ = _settings_schema.collect_settings_schema(_make_scene(), _fake_bpy())
        groups = {group["id"]: group for group in schema["groups"]}
        self.assertEqual(groups["view_layer"]["properties"][0]["path"], "use_pass_z")
        self.assertEqual(
            groups["view_layer.cycles"]["properties"][0]["path"],
            "cycles.use_denoising",
        )

    def test_render_engine_enum_combines_subclasses_and_builtins(self):
        schema, _ = _settings_schema.collect_settings_schema(_make_scene(), _fake_bpy())
        groups = {group["id"]: group for group in schema["groups"]}
        render_props = {prop["identifier"]: prop for prop in groups["render"]["properties"]}
        engine_enum = render_props["engine"]["enum"]
        self.assertEqual(
            [item["identifier"] for item in engine_enum],
            ["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"],
        )
        self.assertEqual(engine_enum[0]["name"], "Cycles")
        # Built-ins keep the identifier as the name fallback.
        self.assertEqual(engine_enum[1]["name"], "BLENDER_EEVEE_NEXT")

    def test_dynamic_enums_harvested_from_typeerror(self):
        scene = _make_scene()
        schema, _ = _settings_schema.collect_settings_schema(scene, _fake_bpy())
        groups = {group["id"]: group for group in schema["groups"]}
        view_props = {prop["identifier"]: prop for prop in groups["view_settings"]["properties"]}
        self.assertEqual(
            [item["identifier"] for item in view_props["view_transform"]["enum"]],
            ["Standard", "AgX", "Filmic"],
        )
        self.assertEqual(
            [item["identifier"] for item in view_props["look"]["enum"]],
            ["None", "Punchy"],
        )
        display_prop = groups["display_settings"]["properties"][0]
        self.assertEqual(
            [item["identifier"] for item in display_prop["enum"]],
            ["sRGB", "Display P3"],
        )
        # The failed assignment must not mutate the live value.
        self.assertEqual(scene.view_settings.view_transform, "AgX")

    def test_dynamic_enum_failure_degrades_to_static_items(self):
        scene = _make_scene()
        # A view_settings struct that accepts any assignment yields no
        # harvested identifiers, so the static placeholder survives.
        scene.view_settings = _struct(
            [_prop("view_transform", "ENUM", enum_items=[_enum_item("Standard")])],
            view_transform="Standard",
        )
        # A RenderEngine without __subclasses__ raises inside the special
        # case, leaving render.engine on its static enum items.
        broken_bpy = SimpleNamespace(
            types=SimpleNamespace(RenderEngine=SimpleNamespace()),
            app=SimpleNamespace(version_string="4.5.9"),
        )
        schema, _ = _settings_schema.collect_settings_schema(scene, broken_bpy)
        groups = {group["id"]: group for group in schema["groups"]}
        render_props = {prop["identifier"]: prop for prop in groups["render"]["properties"]}
        self.assertEqual(
            [item["identifier"] for item in render_props["engine"]["enum"]],
            ["BLENDER_EEVEE_NEXT"],
        )
        view_prop = groups["view_settings"]["properties"][0]
        self.assertEqual(
            [item["identifier"] for item in view_prop["enum"]],
            ["Standard"],
        )

    def test_dump_failure_returns_safe_empties(self):
        self.assertEqual(
            _settings_schema.collect_settings_schema(None, _fake_bpy()),
            (None, None),
        )
        # A scene with none of the curated roots produces no groups.
        self.assertEqual(
            _settings_schema.collect_settings_schema(SimpleNamespace(), _fake_bpy()),
            (None, None),
        )


class TestCollectSettingsValues(unittest.TestCase):
    def test_values_use_concrete_scene_relative_paths(self):
        values = _settings_schema.collect_settings_values(_make_scene())

        self.assertEqual(values["render.resolution_x"], 1920)
        self.assertEqual(values["render.engine"], "CYCLES")
        self.assertEqual(values["render.stamp_foreground"], [0.8, 0.8, 0.8, 1.0])
        self.assertEqual(values["render.image_settings.file_format"], "OPEN_EXR")
        self.assertEqual(values["cycles.samples"], 128)
        self.assertEqual(values["view_settings.view_transform"], "AgX")
        self.assertEqual(values["view_settings.exposure"], 0.5)
        self.assertEqual(values["display_settings.display_device"], "sRGB")
        self.assertIs(values['view_layers["Beauty"].use_pass_z'], True)
        self.assertIs(values['view_layers["Beauty"].cycles.use_denoising'], False)
        self.assertEqual(values["world"], "World")
        self.assertEqual(values["camera"], "Camera_A")

        # Hidden/readonly/pointer and non-JSON-serializable values are skipped.
        self.assertNotIn("render.filepath", values)
        self.assertNotIn("render.file_extension", values)
        self.assertNotIn("render.bake", values)
        self.assertNotIn("render.weird", values)

    def test_values_instantiate_every_view_layer(self):
        scene = _make_scene()
        second = _struct(
            [_prop("use_pass_z", "BOOLEAN", default=False)],
            name="Shadow",
            use_pass_z=False,
            cycles=_struct(
                [_prop("use_denoising", "BOOLEAN", default=True)],
                use_denoising=True,
            ),
        )
        scene.view_layers.append(second)
        values = _settings_schema.collect_settings_values(scene)
        self.assertIs(values['view_layers["Beauty"].use_pass_z'], True)
        self.assertIs(values['view_layers["Shadow"].use_pass_z'], False)
        self.assertIs(values['view_layers["Shadow"].cycles.use_denoising'], True)

    def test_missing_world_and_camera_are_none(self):
        scene = _make_scene()
        scene.world = None
        scene.camera = None
        values = _settings_schema.collect_settings_values(scene)
        self.assertIsNone(values["world"])
        self.assertIsNone(values["camera"])

    def test_dump_failure_returns_safe_empties(self):
        self.assertEqual(_settings_schema.collect_settings_values(None), {})

        class _ExplodingLayers:
            def __iter__(self):
                raise RuntimeError("boom")

        scene = _make_scene()
        scene.view_layers = _ExplodingLayers()
        self.assertEqual(_settings_schema.collect_settings_values(scene), {})


if __name__ == "__main__":
    unittest.main()
