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


_scene_metadata = _load_module_directly(
    "scene_metadata",
    _addon_dir / "transfers" / "submit" / "scene_metadata.py",
)


class _PassSettings:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


def _camera(name: str):
    return SimpleNamespace(name=name, type="CAMERA", data=SimpleNamespace(name=f"{name}Data"))


def _mesh(name: str):
    return SimpleNamespace(name=name, type="MESH")


def _render(**overrides):
    values = {
        "fps": 24,
        "fps_base": 1.0,
        "resolution_x": 1920,
        "resolution_y": 1080,
        "resolution_percentage": 50,
        "pixel_aspect_x": 1.0,
        "pixel_aspect_y": 1.0,
        "engine": "CYCLES",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestSceneMetadata(unittest.TestCase):
    def test_collects_current_scene_fps_resolution_cameras_and_passes(self):
        camera_a = _camera("Camera_A")
        camera_b = _camera("Camera_B")
        scene = SimpleNamespace(
            name="Shot",
            frame_start=100,
            frame_end=140,
            frame_step=2,
            render=_render(fps=24000, fps_base=1001, resolution_percentage=75),
            camera=camera_a,
            objects=[camera_a, camera_b, _mesh("Cube")],
            timeline_markers=[
                SimpleNamespace(name="Cut A", frame=100, camera=camera_a),
                SimpleNamespace(name="Cut B", frame=120, camera=camera_b),
            ],
            view_layers=[
                SimpleNamespace(
                    name="Beauty",
                    use_pass_z=True,
                    use_pass_normal=False,
                    cycles=_PassSettings(use_pass_volume_direct=True),
                    aovs=[SimpleNamespace(name="crypto_matte", type="COLOR")],
                )
            ],
        )
        bpy = SimpleNamespace(data=SimpleNamespace(scenes=[scene], objects=[camera_a, camera_b]))
        context = SimpleNamespace(scene=scene, view_layer=scene.view_layers[0])

        metadata = _scene_metadata.build_scene_metadata(bpy, context)

        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["active_scene"], "Shot")
        self.assertEqual(metadata["available_scenes"], ["Shot"])

        current = metadata["current"]
        self.assertAlmostEqual(current["fps"], 23.976024, places=6)
        self.assertEqual(current["resolution"]["base_width"], 1920)
        self.assertEqual(current["resolution"]["base_height"], 1080)
        self.assertEqual(current["resolution"]["percentage"], 75)
        self.assertEqual(current["resolution"]["width"], 1440)
        self.assertEqual(current["resolution"]["height"], 810)
        self.assertEqual(current["camera"], "Camera_A")

        scene_meta = metadata["scenes"][0]
        self.assertEqual(scene_meta["camera_markers"][1]["frame"], 120)
        self.assertEqual(scene_meta["camera_markers"][1]["camera"], "Camera_B")
        self.assertIn("Z", scene_meta["enabled_passes"])
        self.assertIn("NORMAL", scene_meta["available_passes"])
        self.assertNotIn("NORMAL", scene_meta["enabled_passes"])
        self.assertIn("VOLUME_DIRECT", scene_meta["enabled_passes"])
        self.assertIn("AOV:crypto_matte", scene_meta["enabled_passes"])
        self.assertIn("COMBINED", scene_meta["enabled_passes"])

        camera_catalog = {camera["name"]: camera for camera in metadata["cameras"]}
        self.assertEqual(camera_catalog["Camera_A"]["active_in_scenes"], ["Shot"])
        self.assertEqual(camera_catalog["Camera_B"]["marker_frames"][0]["frame"], 120)


if __name__ == "__main__":
    unittest.main()
