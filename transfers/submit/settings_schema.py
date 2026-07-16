from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator, Optional, Tuple

if __package__:
    from .rna_utils import _iter_collection, _name, _safe_get, _safe_int
else:
    import importlib.util

    _rna_spec = importlib.util.spec_from_file_location(
        "sulu_submit_rna_utils", __file__.replace("settings_schema.py", "rna_utils.py")
    )
    _rna_utils = importlib.util.module_from_spec(_rna_spec)
    _rna_spec.loader.exec_module(_rna_utils)
    _iter_collection = _rna_utils._iter_collection
    _name = _rna_utils._name
    _safe_get = _rna_utils._safe_get
    _safe_int = _rna_utils._safe_int

_SCHEMA_VERSION = 1

# Sentinel for values that cannot be represented as JSON and must be skipped.
_SKIP = object()

# Sentinel assigned to dynamic enums to harvest the valid identifiers from
# Blender's TypeError message. The failed assignment does not mutate.
_INVALID_ENUM_SENTINEL = "___SULU_INVALID_ENUM___"

# Pointer/collection properties allowed into the schema. World and camera are
# delivered through the scene_metadata catalogs, so v1 keeps this empty.
_POINTER_ALLOWLIST: frozenset[str] = frozenset()

# Engines compiled into Blender that never show up as RenderEngine subclasses.
_BUILTIN_RENDER_ENGINES = ("BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH")

# (group id, property identifier) pairs whose enum items are dynamic (OCIO
# config driven) and must be harvested from the live struct.
_HARVESTED_ENUMS = {
    ("view_settings", "view_transform"),
    ("view_settings", "look"),
    ("display_settings", "display_device"),
}

# Curated roots walked on the active scene. Per-layer groups are walked on one
# representative view layer; their property paths are layer-relative so the UI
# can instantiate them per view layer as view_layers["Name"].<path>.
_GROUP_DEFS = (
    {"id": "render", "label": "Render", "root": "render", "per_layer": False},
    {
        "id": "render.image_settings",
        "label": "Output",
        "root": "render.image_settings",
        "per_layer": False,
    },
    {"id": "cycles", "label": "Cycles", "root": "cycles", "per_layer": False, "engine": "CYCLES"},
    {
        "id": "eevee",
        "label": "EEVEE",
        "root": "eevee",
        "per_layer": False,
        "engine": "BLENDER_EEVEE_NEXT",
    },
    {"id": "view_layer", "label": "View Layer", "root": "view_layer", "per_layer": True},
    {
        "id": "view_layer.cycles",
        "label": "View Layer · Cycles",
        "root": "view_layer.cycles",
        "per_layer": True,
        "engine": "CYCLES",
    },
    {
        "id": "view_settings",
        "label": "Color Management",
        "root": "view_settings",
        "per_layer": False,
    },
    {
        "id": "display_settings",
        "label": "Color Management",
        "root": "display_settings",
        "per_layer": False,
    },
)


def _json_value(value: Any) -> Any:
    """Coerce *value* to a JSON-safe equivalent, or _SKIP if impossible.

    Enums arrive as identifier strings; vectors/colors become plain lists.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return _SKIP
    try:
        items = list(value)
    except Exception:
        return _SKIP
    out: list[Any] = []
    for item in items:
        coerced = _json_value(item)
        if coerced is _SKIP:
            return _SKIP
        out.append(coerced)
    return out


def _json_or_none(value: Any) -> Any:
    coerced = _json_value(value)
    return None if coerced is _SKIP else coerced


def _resolve_group_struct(scene: Any, group: dict) -> Any:
    """Resolve a group's struct off the scene (or a representative view layer)."""
    if group["per_layer"]:
        layers = _iter_collection(_safe_get(scene, "view_layers"))
        layer = layers[0] if layers else None
        return _layer_struct(layer, group)
    struct = scene
    for attr in group["root"].split("."):
        struct = _safe_get(struct, attr)
        if struct is None:
            return None
    return struct


def _layer_struct(layer: Any, group: dict) -> Any:
    if layer is None:
        return None
    if group["id"] == "view_layer.cycles":
        return _safe_get(layer, "cycles")
    return layer


def _property_path(group: dict, identifier: str) -> str:
    """Schema path: scene-relative, except per-layer groups are layer-relative."""
    if group["per_layer"]:
        prefix = group["root"][len("view_layer"):].lstrip(".")
        return f"{prefix}.{identifier}" if prefix else identifier
    return f"{group['root']}.{identifier}"


def _iter_schema_properties(struct: Any) -> Iterator[tuple[str, Any]]:
    """Yield (identifier, rna property) pairs that belong in the schema."""
    bl_rna = _safe_get(struct, "bl_rna")
    for prop in _iter_collection(_safe_get(bl_rna, "properties")):
        identifier = str(_safe_get(prop, "identifier", "") or "")
        if not identifier or identifier == "rna_type":
            continue
        if _safe_get(prop, "is_readonly", False) or _safe_get(prop, "is_hidden", False):
            continue
        prop_type = str(_safe_get(prop, "type", "") or "")
        if prop_type in ("POINTER", "COLLECTION") and identifier not in _POINTER_ALLOWLIST:
            continue
        yield identifier, prop


def _enum_items(prop: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _iter_collection(_safe_get(prop, "enum_items")):
        identifier = str(_safe_get(item, "identifier", "") or "")
        if not identifier:
            continue
        items.append(
            {
                "identifier": identifier,
                "name": str(_safe_get(item, "name", "") or "") or identifier,
                "description": str(_safe_get(item, "description", "") or ""),
            }
        )
    return items


def _property_schema(prop: Any, path: str) -> dict[str, Any]:
    """Emit one property entry. Different RNA classes expose different
    metadata attributes, so every read is guarded."""
    prop_type = str(_safe_get(prop, "type", "") or "")
    array_length = _safe_int(_safe_get(prop, "array_length", 0))
    if array_length > 0:
        default = _json_or_none(_safe_get(prop, "default_array"))
    else:
        default = _json_or_none(_safe_get(prop, "default"))
    return {
        "identifier": str(_safe_get(prop, "identifier", "") or ""),
        "name": str(_safe_get(prop, "name", "") or ""),
        "description": str(_safe_get(prop, "description", "") or ""),
        "path": path,
        "type": prop_type,
        "subtype": str(_safe_get(prop, "subtype", "") or ""),
        "unit": str(_safe_get(prop, "unit", "") or ""),
        "default": default,
        "soft_min": _json_or_none(_safe_get(prop, "soft_min")),
        "soft_max": _json_or_none(_safe_get(prop, "soft_max")),
        "hard_min": _json_or_none(_safe_get(prop, "hard_min")),
        "hard_max": _json_or_none(_safe_get(prop, "hard_max")),
        "step": _json_or_none(_safe_get(prop, "step")),
        "precision": _json_or_none(_safe_get(prop, "precision")),
        "array_length": array_length,
        "enum": _enum_items(prop) if prop_type == "ENUM" else None,
    }


def _render_engine_items(bpy_module: Any) -> list[dict[str, Any]]:
    """Render engines: RenderEngine subclasses plus built-in C engines."""
    engine_cls = _safe_get(_safe_get(bpy_module, "types"), "RenderEngine")
    items: dict[str, dict[str, Any]] = {}
    for subclass in engine_cls.__subclasses__():
        identifier = str(_safe_get(subclass, "bl_idname", "") or "")
        if not identifier or identifier in items:
            continue
        name = str(_safe_get(subclass, "bl_label", "") or "") or identifier
        items[identifier] = {"identifier": identifier, "name": name, "description": ""}
    for identifier in _BUILTIN_RENDER_ENGINES:
        if identifier not in items:
            items[identifier] = {"identifier": identifier, "name": identifier, "description": ""}
    return list(items.values())


def _harvest_enum_identifiers(struct: Any, identifier: str) -> list[str]:
    """Harvest valid identifiers for a dynamic enum via invalid assignment.

    OCIO-driven enums expose only a placeholder in their static RNA items;
    Blender's TypeError message is the one complete listing. The failed
    assignment does not mutate the property, so nothing is restored.
    """
    try:
        setattr(struct, identifier, _INVALID_ENUM_SENTINEL)
    except TypeError as exc:
        message = str(exc)
        marker = message.find("not found in")
        if marker == -1:
            return []
        return [item for item in re.findall(r"'([^']+)'", message[marker:]) if item]
    return []


def _apply_dynamic_enum(prop_doc: dict[str, Any], group_id: str, struct: Any, bpy_module: Any) -> None:
    """Replace static enum items for known dynamic enums. Any failure leaves
    the (possibly incomplete) static enum_items in place."""
    identifier = prop_doc.get("identifier", "")
    if group_id == "render" and identifier == "engine":
        try:
            items = _render_engine_items(bpy_module)
            if items:
                prop_doc["enum"] = items
        except Exception:
            pass
        return
    if (group_id, identifier) in _HARVESTED_ENUMS:
        try:
            identifiers = _harvest_enum_identifiers(struct, identifier)
            if identifiers:
                prop_doc["enum"] = [
                    {"identifier": item, "name": item, "description": ""}
                    for item in identifiers
                ]
        except Exception:
            pass


def _build_schema(scene: Any, bpy_module: Any) -> Optional[dict[str, Any]]:
    if scene is None:
        return None
    groups: list[dict[str, Any]] = []
    for group in _GROUP_DEFS:
        struct = _resolve_group_struct(scene, group)
        if struct is None:
            continue
        properties: list[dict[str, Any]] = []
        for identifier, prop in _iter_schema_properties(struct):
            prop_doc = _property_schema(prop, _property_path(group, identifier))
            _apply_dynamic_enum(prop_doc, group["id"], struct, bpy_module)
            properties.append(prop_doc)
        if not properties:
            continue
        group_doc: dict[str, Any] = {
            "id": group["id"],
            "label": group["label"],
            "root": group["root"],
            "per_layer": group["per_layer"],
            "properties": properties,
        }
        if group.get("engine"):
            group_doc["engine"] = group["engine"]
        groups.append(group_doc)
    if not groups:
        return None
    return {
        "schema_version": _SCHEMA_VERSION,
        "blender_version": str(_safe_get(_safe_get(bpy_module, "app"), "version_string", "") or ""),
        "groups": groups,
    }


def _schema_key(schema: dict[str, Any]) -> str:
    version_digits = re.sub(r"[^0-9]", "", str(schema.get("blender_version", "")))
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"bl{version_digits}-{digest}"


def _load_layout_parser() -> Any:
    """Import layout_parser both as a package sibling and standalone."""
    try:
        from . import layout_parser  # type: ignore[no-redef]

        return layout_parser
    except Exception:
        pass
    try:
        import importlib.util
        import os

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layout_parser.py")
        spec = importlib.util.spec_from_file_location("sulu_layout_parser", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
    except Exception:
        return None


def collect_settings_schema(scene: Any, bpy_module: Any = None) -> Tuple[Optional[dict], Optional[str]]:
    """Dump a settings schema for the active scene's curated RNA roots.

    This must run in Blender's foreground process (it touches bpy types and
    live RNA structs). Returns (schema, schema_key), or (None, None) on any
    failure — a dump failure must never block submit.

    The schema additionally carries ``layout``: a declarative translation of
    Blender's own bl_ui panel code (see layout_parser), so the web UI can
    reproduce the exact panel tree and row visibility the user sees in
    Blender. Layout extraction is best-effort; on failure the schema ships
    without it and consumers fall back to flat groups.
    """
    try:
        if bpy_module is None:
            import bpy as bpy_module  # type: ignore[no-redef]
        schema = _build_schema(scene, bpy_module)
        if schema is None:
            return None, None
        layout_parser = _load_layout_parser()
        if layout_parser is not None:
            try:
                layout = layout_parser.collect_layout(bpy_module)
                if layout:
                    schema["layout"] = layout
            except Exception:
                pass
        return schema, _schema_key(schema)
    except Exception:
        return None, None


def collect_settings_values(scene: Any) -> dict[str, Any]:
    """Flat snapshot of current values keyed by concrete scene-relative path.

    Per-layer properties are instantiated for every existing view layer as
    view_layers["Name"].<layer-relative path>. Returns {} on any failure.
    """
    try:
        if scene is None:
            return {}
        values: dict[str, Any] = {}
        for group in _GROUP_DEFS:
            if group["per_layer"]:
                continue
            struct = _resolve_group_struct(scene, group)
            if struct is None:
                continue
            for identifier, _prop in _iter_schema_properties(struct):
                value = _json_value(_safe_get(struct, identifier, _SKIP))
                if value is _SKIP:
                    continue
                values[f"{group['root']}.{identifier}"] = value
        for layer in _iter_collection(_safe_get(scene, "view_layers")):
            layer_name = _name(layer)
            if not layer_name:
                continue
            for group in _GROUP_DEFS:
                if not group["per_layer"]:
                    continue
                struct = _layer_struct(layer, group)
                if struct is None:
                    continue
                for identifier, _prop in _iter_schema_properties(struct):
                    value = _json_value(_safe_get(struct, identifier, _SKIP))
                    if value is _SKIP:
                        continue
                    path = _property_path(group, identifier)
                    values[f'view_layers["{layer_name}"].{path}'] = value
        values["world"] = _name(_safe_get(scene, "world")) or None
        values["camera"] = _name(_safe_get(scene, "camera")) or None
        return values
    except Exception:
        return {}


def collect_settings_values_by_scene(bpy_module: Any = None) -> dict[str, Any]:
    """Per-scene values snapshots, keyed by scene name.

    The web editor's scene selector swaps the whole snapshot — every captured
    setting hangs off the scene — so all scenes are captured at submit.
    Returns {} on any failure.
    """
    try:
        if bpy_module is None:
            import bpy as bpy_module  # type: ignore[no-redef]
        snapshots: dict[str, Any] = {}
        for scene in _iter_collection(_safe_get(_safe_get(bpy_module, "data"), "scenes")):
            scene_name = _name(scene)
            if not scene_name:
                continue
            values = collect_settings_values(scene)
            if values:
                snapshots[scene_name] = values
        return snapshots
    except Exception:
        return {}
