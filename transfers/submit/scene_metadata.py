from __future__ import annotations

from collections import OrderedDict
from typing import Any

if __package__:
    from .rna_utils import _iter_collection, _name, _safe_get, _safe_int
else:
    import importlib.util

    _rna_spec = importlib.util.spec_from_file_location(
        "sulu_submit_rna_utils", __file__.replace("scene_metadata.py", "rna_utils.py")
    )
    _rna_utils = importlib.util.module_from_spec(_rna_spec)
    _rna_spec.loader.exec_module(_rna_utils)
    _iter_collection = _rna_utils._iter_collection
    _name = _rna_utils._name
    _safe_get = _rna_utils._safe_get
    _safe_int = _rna_utils._safe_int


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_float(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _pass_label(pass_id: str) -> str:
    return pass_id.replace("_", " ").title()


def _pass_flags_from(source: Any, source_name: str) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if source is None:
        return flags
    for attr in dir(source):
        if not attr.startswith("use_pass_"):
            continue
        value = _safe_get(source, attr, None)
        if not isinstance(value, bool):
            continue
        pass_id = attr.removeprefix("use_pass_").upper()
        flags.append(
            {
                "id": pass_id,
                "name": _pass_label(pass_id),
                "property": attr,
                "source": source_name,
                "enabled": bool(value),
            }
        )
    return flags


def _view_layer_pass_flags(view_layer: Any) -> list[dict[str, Any]]:
    flags = _pass_flags_from(view_layer, "view_layer")
    for child_name in ("cycles", "eevee"):
        flags.extend(_pass_flags_from(_safe_get(view_layer, child_name), child_name))

    by_key: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
    for flag in flags:
        by_key[(flag["source"], flag["property"], flag["id"])] = flag

    if not any(flag["id"] == "COMBINED" for flag in by_key.values()):
        by_key[("view_layer", "combined", "COMBINED")] = {
            "id": "COMBINED",
            "name": "Combined",
            "property": "combined",
            "source": "view_layer",
            "enabled": True,
        }

    for aov in _iter_collection(_safe_get(view_layer, "aovs")):
        aov_name = _name(aov)
        if not aov_name:
            continue
        pass_id = f"AOV:{aov_name}"
        by_key[("aov", aov_name, pass_id)] = {
            "id": pass_id,
            "name": aov_name,
            "property": aov_name,
            "source": "aov",
            "type": str(_safe_get(aov, "type", "") or "").strip(),
            "enabled": True,
        }

    return list(by_key.values())


def _unique_pass_ids(flags: list[dict[str, Any]], *, enabled_only: bool) -> list[str]:
    out: OrderedDict[str, None] = OrderedDict()
    for flag in flags:
        if enabled_only and not flag.get("enabled"):
            continue
        pass_id = str(flag.get("id", "") or "").strip()
        if pass_id:
            out[pass_id] = None
    return list(out.keys())


def _view_layer_metadata(view_layer: Any, active_view_layer_name: str) -> dict[str, Any]:
    flags = _view_layer_pass_flags(view_layer)
    name = _name(view_layer)
    return {
        "name": name,
        "is_active": bool(name and name == active_view_layer_name),
        "enabled_passes": _unique_pass_ids(flags, enabled_only=True),
        "available_passes": _unique_pass_ids(flags, enabled_only=False),
        "pass_flags": flags,
    }


def _scene_fps(render: Any) -> dict[str, Any]:
    fps_base = _safe_float(_safe_get(render, "fps_base", 1.0), 1.0)
    if fps_base <= 0:
        fps_base = 1.0
    fps_numerator = _safe_int(_safe_get(render, "fps", 24), 24)
    return {
        "fps": _round_float(fps_numerator / fps_base),
        "fps_numerator": fps_numerator,
        "fps_base": fps_base,
    }


def _scene_resolution(render: Any) -> dict[str, Any]:
    base_width = max(0, _safe_int(_safe_get(render, "resolution_x", 0), 0))
    base_height = max(0, _safe_int(_safe_get(render, "resolution_y", 0), 0))
    percentage = max(0, _safe_int(_safe_get(render, "resolution_percentage", 100), 100))
    pixel_aspect_x = _safe_float(_safe_get(render, "pixel_aspect_x", 1.0), 1.0) or 1.0
    pixel_aspect_y = _safe_float(_safe_get(render, "pixel_aspect_y", 1.0), 1.0) or 1.0
    width = int(round(base_width * percentage / 100.0))
    height = int(round(base_height * percentage / 100.0))
    aspect_ratio = 0.0
    if width > 0 and height > 0:
        aspect_ratio = (width * pixel_aspect_x) / (height * pixel_aspect_y)
    return {
        "base_width": base_width,
        "base_height": base_height,
        "percentage": percentage,
        "width": width,
        "height": height,
        "pixel_aspect_x": pixel_aspect_x,
        "pixel_aspect_y": pixel_aspect_y,
        "aspect_ratio": _round_float(aspect_ratio),
    }


def _scene_camera_names(scene: Any) -> list[str]:
    cameras: list[str] = []
    for obj in _iter_collection(_safe_get(scene, "objects")):
        if str(_safe_get(obj, "type", "") or "").upper() == "CAMERA":
            name = _name(obj)
            if name:
                cameras.append(name)
    return cameras


def _scene_camera_markers(scene: Any) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for marker in _iter_collection(_safe_get(scene, "timeline_markers")):
        camera = _safe_get(marker, "camera")
        camera_name = _name(camera)
        if not camera_name:
            continue
        markers.append(
            {
                "frame": _safe_int(_safe_get(marker, "frame", 0), 0),
                "camera": camera_name,
                "marker": _name(marker),
            }
        )
    return markers


def _scene_metadata(scene: Any, active_scene_name: str, active_view_layer_name: str) -> dict[str, Any]:
    render = _safe_get(scene, "render")
    fps = _scene_fps(render)
    resolution = _scene_resolution(render)
    view_layers = [
        _view_layer_metadata(layer, active_view_layer_name)
        for layer in _iter_collection(_safe_get(scene, "view_layers"))
    ]
    enabled_passes: OrderedDict[str, None] = OrderedDict()
    available_passes: OrderedDict[str, None] = OrderedDict()
    for layer in view_layers:
        for pass_id in layer["enabled_passes"]:
            enabled_passes[pass_id] = None
        for pass_id in layer["available_passes"]:
            available_passes[pass_id] = None

    name = _name(scene)
    return {
        "name": name,
        "is_active": bool(name and name == active_scene_name),
        "frame_start": _safe_int(_safe_get(scene, "frame_start", 0), 0),
        "frame_end": _safe_int(_safe_get(scene, "frame_end", 0), 0),
        "frame_step": max(1, _safe_int(_safe_get(scene, "frame_step", 1), 1)),
        "render_engine": str(_safe_get(render, "engine", "") or "").strip().upper(),
        **fps,
        "resolution": resolution,
        "active_camera": _name(_safe_get(scene, "camera")) or None,
        "cameras": _scene_camera_names(scene),
        "camera_markers": _scene_camera_markers(scene),
        "view_layers": view_layers,
        "enabled_passes": list(enabled_passes.keys()),
        "available_passes": list(available_passes.keys()),
    }


def _camera_catalog(bpy_module: Any, scenes: list[Any]) -> list[dict[str, Any]]:
    cameras: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for obj in _iter_collection(_safe_get(_safe_get(bpy_module, "data"), "objects")):
        if str(_safe_get(obj, "type", "") or "").upper() != "CAMERA":
            continue
        name = _name(obj)
        if name:
            cameras[name] = {
                "name": name,
                "data": _name(_safe_get(obj, "data")) or None,
                "scenes": [],
                "active_in_scenes": [],
                "marker_frames": [],
            }

    for scene in scenes:
        scene_name = _name(scene)
        active_camera_name = _name(_safe_get(scene, "camera"))
        scene_camera_names = set(_scene_camera_names(scene))
        for camera_name in scene_camera_names:
            camera = cameras.setdefault(
                camera_name,
                {
                    "name": camera_name,
                    "data": None,
                    "scenes": [],
                    "active_in_scenes": [],
                    "marker_frames": [],
                },
            )
            if scene_name and scene_name not in camera["scenes"]:
                camera["scenes"].append(scene_name)
            if camera_name == active_camera_name and scene_name:
                camera["active_in_scenes"].append(scene_name)
        for marker in _scene_camera_markers(scene):
            camera = cameras.setdefault(
                marker["camera"],
                {
                    "name": marker["camera"],
                    "data": None,
                    "scenes": [],
                    "active_in_scenes": [],
                    "marker_frames": [],
                },
            )
            camera["marker_frames"].append(
                {"scene": scene_name, "frame": marker["frame"], "marker": marker["marker"]}
            )

    return list(cameras.values())


def build_scene_metadata(bpy_module: Any, context: Any) -> dict[str, Any]:
    """Collect lightweight Blender scene metadata for job display and cloning.

    This must run in Blender's foreground process before the submit worker is
    launched. The worker may run in an isolated Python process and should not
    touch bpy objects.
    """
    active_scene = _safe_get(context, "scene")
    active_scene_name = _name(active_scene)
    active_view_layer_name = _name(_safe_get(context, "view_layer"))
    scenes = _iter_collection(_safe_get(_safe_get(bpy_module, "data"), "scenes"))
    if not scenes and active_scene is not None:
        scenes = [active_scene]

    scene_items = [
        _scene_metadata(scene, active_scene_name, active_view_layer_name)
        for scene in scenes
    ]
    active = next((scene for scene in scene_items if scene.get("is_active")), None)
    if active is None and scene_items:
        active = scene_items[0]

    current = {}
    if active:
        current = {
            "scene": active.get("name"),
            "fps": active.get("fps"),
            "fps_numerator": active.get("fps_numerator"),
            "fps_base": active.get("fps_base"),
            "resolution": active.get("resolution"),
            "camera": active.get("active_camera"),
            "render_engine": active.get("render_engine"),
            "enabled_passes": active.get("enabled_passes", []),
            "available_passes": active.get("available_passes", []),
        }

    return {
        "schema_version": 1,
        "active_scene": active_scene_name or None,
        "active_view_layer": active_view_layer_name or None,
        "available_scenes": [_name(scene) for scene in scenes if _name(scene)],
        "scenes": scene_items,
        "cameras": _camera_catalog(bpy_module, scenes),
        "current": current,
    }
