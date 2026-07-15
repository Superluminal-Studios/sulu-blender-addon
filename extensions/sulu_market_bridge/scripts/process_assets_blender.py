"""Blender-side hostile-input processor for Sulu Market OBJECT assets.

This file is executed by ``process_assets.py`` under Blender with factory startup,
automatic script execution disabled, and offline mode enabled. It must not be
included in the installable Sulu Market Bridge extension ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unicodedata
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
BRIDGE_ROOT = SCRIPT_DIRECTORY.parent
if str(BRIDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BRIDGE_ROOT))

from scripts.asset_processing_contract import (  # noqa: E402
    DEFAULT_MAX_ARTIFACT_BYTES,
    DEFAULT_MAX_ASSETS,
    DEFAULT_MAX_INPUT_BYTES,
    DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
    HARD_MAX_ARTIFACT_BYTES,
    HARD_MAX_ASSETS,
    HARD_MAX_INPUT_BYTES,
    HARD_MAX_TOTAL_OUTPUT_BYTES,
    IMMUTABLE_ID_PROPERTY,
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_ID_TYPE,
    ContractError,
    artifact_relative_path,
    load_identity_mappings,
    new_immutable_id,
    source_key_for,
    validate_asset_name,
    validate_blender_build_hash,
    validate_processing_manifest,
    validated_limit,
)

MINIMUM_BLENDER_VERSION = (5, 2, 0)
MINIMUM_BLENDER_VERSION_TEXT = "5.2.0"
MANIFEST_MAX_BYTES = 1024 * 1024
ACCEPTED_BLEND_PREFIXES = (b"BLENDER", b"\x28\xb5\x2f\xfd", b"\x1f\x8b")
_NIL_UUID = uuid.UUID(int=0)


class ProcessingError(RuntimeError):
    """A safe, non-path-bearing seller processing failure."""


def _arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mappings", type=Path)
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
    parser.add_argument("--max-assets", type=int, default=DEFAULT_MAX_ASSETS)
    parser.add_argument("--max-artifact-bytes", type=int, default=DEFAULT_MAX_ARTIFACT_BYTES)
    parser.add_argument(
        "--max-total-output-bytes",
        type=int,
        default=DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
    )
    parser.add_argument("--expected-blender-build-hash")
    return parser.parse_args(values)


def _current_build_hash() -> str:
    raw_hash = bpy.app.build_hash
    build_hash = raw_hash.decode("ascii") if isinstance(raw_hash, bytes) else str(raw_hash)
    try:
        return validate_blender_build_hash(build_hash)
    except ContractError as error:
        raise ProcessingError("Blender returned an invalid build hash") from error


def _require_hardened_blender_invocation(expected_build_hash: str | None) -> str:
    required_flags = {"--background", "--factory-startup", "--disable-autoexec", "--offline-mode"}
    missing = sorted(required_flags - set(sys.argv))
    if missing:
        raise ProcessingError("required hardened Blender launch flags are missing")
    if bpy.app.version[:2] != MINIMUM_BLENDER_VERSION[:2]:
        raise ProcessingError("the processor is pinned to official Blender 5.2.x")
    build_hash = _current_build_hash()
    if expected_build_hash is not None:
        try:
            expected_build_hash = validate_blender_build_hash(expected_build_hash)
        except ContractError as error:
            raise ProcessingError("expected Blender build hash is invalid") from error
        if build_hash != expected_build_hash:
            raise ProcessingError("Blender build does not match the pinned production build")
    try:
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    except AttributeError as error:
        raise ProcessingError("automatic script execution could not be disabled") from error
    return build_hash


def _validate_input(path: Path, maximum_bytes: int) -> tuple[os.stat_result, str]:
    if path.suffix.lower() != ".blend":
        raise ProcessingError("seller input must have the .blend extension")
    try:
        file_stat = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
            raise ProcessingError("seller input must be a non-symlink regular file")
        if file_stat.st_size < 12:
            raise ProcessingError("seller input is too small to be a Blender file")
        if file_stat.st_size > maximum_bytes:
            raise ProcessingError("seller input exceeds the configured byte limit")
        with path.open("rb") as handle:
            prefix = handle.read(7)
            if not any(prefix.startswith(magic) for magic in ACCEPTED_BLEND_PREFIXES):
                raise ProcessingError("seller input has no supported Blender file signature")
            handle.seek(0)
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except ProcessingError:
        raise
    except OSError as error:
        raise ProcessingError("seller input cannot be read safely") from error
    return file_stat, digest


def _assert_input_unchanged(path: Path, original: os.stat_result) -> None:
    try:
        current = path.lstat()
    except OSError as error:
        raise ProcessingError("seller input disappeared during processing") from error
    identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    expected = (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns)
    if identity != expected or path.is_symlink():
        raise ProcessingError("seller input changed during processing")


def _format_version(version: Any) -> str:
    try:
        parts = tuple(int(part) for part in version)
    except (TypeError, ValueError) as error:
        raise ProcessingError("Blender returned an invalid file version") from error
    if len(parts) < 2 or any(part < 0 for part in parts[:3]):
        raise ProcessingError("Blender returned an invalid file version")
    padded = (*parts[:3], 0, 0)[:3]
    return ".".join(str(part) for part in padded)


def _discover_assets(path: Path) -> tuple[list[str], str]:
    try:
        with bpy.data.libraries.load(str(path), link=False, assets_only=True) as (data_from, _):
            source_version = _format_version(data_from.version)
            marked_by_type = {
                name: list(getattr(data_from, name))
                for name in dir(data_from)
                if name != "version" and isinstance(getattr(data_from, name), list)
            }
    except (OSError, RuntimeError) as error:
        raise ProcessingError("Blender rejected the seller library") from error

    populated = {name: values for name, values in marked_by_type.items() if values}
    unsupported = sorted(name for name in populated if name != "objects")
    if unsupported:
        raise ProcessingError(
            "seller input contains marked asset types outside the v1 OBJECT-only contract"
        )
    object_names = populated.get("objects", [])
    if not object_names:
        raise ProcessingError("seller input contains no marked OBJECT assets")
    try:
        normalized = [validate_asset_name(name) for name in object_names]
    except ContractError as error:
        raise ProcessingError("seller input contains an invalid asset name") from error
    if len(normalized) != len(set(normalized)):
        raise ProcessingError("seller input contains duplicate OBJECT asset names")
    return sorted(normalized), source_version


def _factory_empty() -> None:
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    except (AttributeError, RuntimeError) as error:
        raise ProcessingError("Blender could not reset to an empty factory state") from error


def _load_object(path: Path, exact_name: str) -> Any:
    try:
        with bpy.data.libraries.load(str(path), link=False, assets_only=True) as (
            data_from,
            data_to,
        ):
            if exact_name not in data_from.objects:
                raise ProcessingError("a discovered OBJECT asset disappeared before append")
            data_to.objects = [exact_name]
        loaded = [item for item in data_to.objects if item is not None]
    except ProcessingError:
        raise
    except (OSError, RuntimeError) as error:
        raise ProcessingError("Blender could not append the exact OBJECT asset") from error
    if len(loaded) != 1 or loaded[0].name != exact_name:
        raise ProcessingError("Blender did not append exactly the requested OBJECT asset")
    if loaded[0].asset_data is None:
        raise ProcessingError("appended OBJECT is no longer marked as an asset")
    return loaded[0]


def _all_datablocks() -> Iterator[Any]:
    seen: set[int] = set()
    for property_definition in bpy.data.bl_rna.properties:
        if property_definition.identifier == "rna_type" or property_definition.type != "COLLECTION":
            continue
        try:
            values = getattr(bpy.data, property_definition.identifier)
            iterator = iter(values)
        except (AttributeError, TypeError):
            continue
        for datablock in iterator:
            pointer = datablock.as_pointer() if hasattr(datablock, "as_pointer") else id(datablock)
            if pointer not in seen:
                seen.add(pointer)
                yield datablock


def _has_packed_payload(datablock: Any) -> bool:
    if getattr(datablock, "packed_file", None) is not None:
        return True
    try:
        return len(datablock.packed_files) > 0
    except (AttributeError, TypeError):
        return False


def _external_filepath(datablock: Any) -> str:
    for attribute in ("filepath_raw", "filepath"):
        value = getattr(datablock, attribute, "")
        if isinstance(value, str) and value:
            return value
    return ""


def _reject_unsafe_loaded_data(*, expected_immutable_id: str | None = None) -> None:
    if len(bpy.data.texts):
        raise ProcessingError("asset dependencies contain embedded script text")

    marker_holders = []
    for datablock in _all_datablocks():
        if getattr(datablock, "library", None) is not None:
            raise ProcessingError("asset dependencies contain a linked datablock")
        try:
            if IMMUTABLE_ID_PROPERTY in datablock.keys():
                marker_holders.append(datablock)
        except AttributeError:
            pass
        animation_data = getattr(datablock, "animation_data", None)
        if animation_data is not None and len(animation_data.drivers):
            raise ProcessingError("asset dependencies contain scripted drivers")

        node_trees = []
        if hasattr(datablock, "nodes"):
            node_trees.append(datablock)
        node_tree = getattr(datablock, "node_tree", None)
        if node_tree is not None:
            node_trees.append(node_tree)
        for tree in node_trees:
            if any(
                getattr(node, "bl_idname", "") == "ShaderNodeScript"
                or getattr(node, "type", "") == "SCRIPT"
                for node in tree.nodes
            ):
                raise ProcessingError("asset dependencies contain an OSL script node")

    for image in bpy.data.images:
        if (
            image.source not in {"GENERATED", "VIEWER"}
            and _external_filepath(image)
            and not _has_packed_payload(image)
        ):
            raise ProcessingError("asset dependencies contain an unpacked external image")
    for font in bpy.data.fonts:
        filepath = _external_filepath(font)
        if filepath not in {"", "<builtin>"} and not _has_packed_payload(font):
            raise ProcessingError("asset dependencies contain an unpacked external font")
    for sound in bpy.data.sounds:
        if _external_filepath(sound) and not _has_packed_payload(sound):
            raise ProcessingError("asset dependencies contain an unpacked external sound")
    for clip in bpy.data.movieclips:
        if _external_filepath(clip) and not _has_packed_payload(clip):
            raise ProcessingError("asset dependencies contain an external movie clip")
    for cache in bpy.data.cache_files:
        if _external_filepath(cache):
            raise ProcessingError("asset dependencies contain an external cache file")
    for volume in bpy.data.volumes:
        if _external_filepath(volume):
            raise ProcessingError("asset dependencies contain an external volume file")

    if expected_immutable_id is None and marker_holders:
        raise ProcessingError("seller data contains the reserved immutable-ID property")
    if expected_immutable_id is not None:
        marked = [obj for obj in bpy.data.objects if obj.asset_data is not None]
        if (
            len(marked) != 1
            or marker_holders != marked
            or marked[0].get(IMMUTABLE_ID_PROPERTY) != expected_immutable_id
        ):
            raise ProcessingError("verified artifact has the wrong immutable asset marker")


def _optional_metadata(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ProcessingError("asset metadata contains a non-string value")
    if unicodedata.normalize("NFC", value) != value:
        raise ProcessingError("asset metadata is not NFC-normalized")
    return value


def _asset_metadata(obj: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    asset_data = obj.asset_data
    raw_catalog_id = str(asset_data.catalog_id)
    try:
        parsed_catalog_id = uuid.UUID(raw_catalog_id)
    except ValueError as error:
        raise ProcessingError("asset catalog ID is invalid") from error
    catalog_id = None if parsed_catalog_id == _NIL_UUID else str(parsed_catalog_id)
    catalog = {
        "id": catalog_id,
        "name": _optional_metadata(asset_data.catalog_simple_name),
    }
    raw_tags = {_optional_metadata(tag.name) for tag in asset_data.tags}
    if None in raw_tags:
        raise ProcessingError("asset metadata contains an empty tag")
    tags = sorted(raw_tags)
    metadata = {
        "description": _optional_metadata(asset_data.description),
        "author": _optional_metadata(asset_data.author),
        "license": _optional_metadata(asset_data.license),
        "copyright": _optional_metadata(asset_data.copyright),
        "tags": tags,
    }
    return catalog, metadata


def _sha256(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as error:
        raise ProcessingError("generated artifact could not be hashed") from error


def _write_artifact(obj: Any, artifact_path: Path) -> None:
    try:
        bpy.data.libraries.write(
            str(artifact_path),
            {obj},
            path_remap="NONE",
            fake_user=True,
            compress=True,
        )
    except (OSError, RuntimeError) as error:
        raise ProcessingError("Blender could not write a canonical asset artifact") from error


def _verify_artifact(path: Path, expected_name: str, immutable_id: str) -> None:
    _factory_empty()
    object_names, _ = _discover_assets(path)
    if object_names != [expected_name]:
        raise ProcessingError("generated artifact does not contain exactly one marked OBJECT")
    loaded = _load_object(path, expected_name)
    if loaded.get(IMMUTABLE_ID_PROPERTY) != immutable_id:
        raise ProcessingError("generated artifact failed immutable identity verification")
    _reject_unsafe_loaded_data(expected_immutable_id=immutable_id)


def _process_one(
    *,
    source_path: Path,
    output_root: Path,
    name: str,
    immutable_id: str,
    identity_source: str,
    source_version: str,
    processed_version: str,
    max_artifact_bytes: int,
) -> dict[str, Any]:
    _factory_empty()
    obj = _load_object(source_path, name)
    if IMMUTABLE_ID_PROPERTY in obj.keys():
        raise ProcessingError("seller asset contains the reserved immutable-ID property")
    _reject_unsafe_loaded_data()
    catalog, metadata = _asset_metadata(obj)
    obj[IMMUTABLE_ID_PROPERTY] = immutable_id

    relative_path = artifact_relative_path(immutable_id)
    artifact_path = output_root / relative_path
    artifact_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_artifact(obj, artifact_path)
    try:
        size = artifact_path.stat().st_size
    except OSError as error:
        raise ProcessingError("generated artifact is not readable") from error
    if size < 1 or size > max_artifact_bytes:
        raise ProcessingError("generated artifact exceeds the configured byte limit")
    digest = _sha256(artifact_path)
    _verify_artifact(artifact_path, name, immutable_id)

    return {
        "source_key": source_key_for(name),
        "name": name,
        "id_type": SUPPORTED_ID_TYPE,
        "immutable_id": immutable_id,
        "identity_source": identity_source,
        "catalog": catalog,
        "metadata": metadata,
        "blender": {
            "minimum_version": MINIMUM_BLENDER_VERSION_TEXT,
            "source_version": source_version,
            "processed_version": processed_version,
        },
        "artifact": {"path": relative_path, "sha256": digest, "size": size},
    }


def _normalized_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    try:
        validate_processing_manifest(manifest)
    except ContractError as error:
        raise ProcessingError(f"normalized manifest validation failed: {error}") from error
    payload = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    if len(payload) > MANIFEST_MAX_BYTES:
        raise ProcessingError("normalized manifest exceeds its hard byte limit")
    return payload


def _run(arguments: argparse.Namespace) -> int:
    blender_build_hash = _require_hardened_blender_invocation(arguments.expected_blender_build_hash)
    try:
        max_input_bytes = validated_limit(
            arguments.max_input_bytes,
            label="max input bytes",
            hard_maximum=HARD_MAX_INPUT_BYTES,
        )
        max_assets = validated_limit(
            arguments.max_assets,
            label="max assets",
            hard_maximum=HARD_MAX_ASSETS,
        )
        max_artifact_bytes = validated_limit(
            arguments.max_artifact_bytes,
            label="max artifact bytes",
            hard_maximum=HARD_MAX_ARTIFACT_BYTES,
        )
        max_total_output_bytes = validated_limit(
            arguments.max_total_output_bytes,
            label="max total output bytes",
            hard_maximum=HARD_MAX_TOTAL_OUTPUT_BYTES,
        )
        mappings = load_identity_mappings(arguments.mappings)
    except ContractError as error:
        raise ProcessingError(f"server processing request is invalid: {error}") from error

    source_path = arguments.input.absolute()
    output_path = arguments.output.absolute()
    if output_path.exists() or output_path.is_symlink():
        raise ProcessingError("output directory must not already exist")
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    input_stat, input_sha256 = _validate_input(source_path, max_input_bytes)
    object_names, source_version = _discover_assets(source_path)
    if len(object_names) > max_assets:
        raise ProcessingError("marked OBJECT asset count exceeds the configured limit")

    used_ids = set(mappings.values())
    identities: dict[str, tuple[str, str]] = {}
    for name in object_names:
        source_key = source_key_for(name)
        if source_key in mappings:
            identities[source_key] = (mappings[source_key], "existing")
        else:
            generated = new_immutable_id(used_ids)
            used_ids.add(generated)
            identities[source_key] = (generated, "generated")

    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.staging-", dir=output_path.parent))
    os.chmod(staging, 0o700)
    try:
        processed_version = _format_version(bpy.app.version)
        assets = []
        artifact_total = 0
        for name in object_names:
            immutable_id, identity_source = identities[source_key_for(name)]
            asset = _process_one(
                source_path=source_path,
                output_root=staging,
                name=name,
                immutable_id=immutable_id,
                identity_source=identity_source,
                source_version=source_version,
                processed_version=processed_version,
                max_artifact_bytes=max_artifact_bytes,
            )
            assets.append(asset)
            artifact_total += asset["artifact"]["size"]
            if artifact_total > max_total_output_bytes:
                raise ProcessingError("generated artifacts exceed the total output byte limit")

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "processor": {
                "name": PROCESSOR_NAME,
                "version": PROCESSOR_VERSION,
                "blender_version": processed_version,
                "blender_build_hash": blender_build_hash,
            },
            "source": {
                "sha256": input_sha256,
                "size": input_stat.st_size,
                "blender_version": source_version,
            },
            "assets": assets,
        }
        manifest_bytes = _normalized_manifest_bytes(manifest)
        if artifact_total + len(manifest_bytes) > max_total_output_bytes:
            raise ProcessingError("generated output exceeds the total output byte limit")
        manifest_path = staging / "manifest.json"
        with manifest_path.open("xb") as handle:
            handle.write(manifest_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        _assert_input_unchanged(source_path, input_stat)
        os.replace(staging, output_path)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    print(json.dumps({"assets_processed": len(assets), "schema_version": SCHEMA_VERSION}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_run(_arguments()))
    except (ContractError, ProcessingError) as error:
        print(f"SULU_ASSET_PROCESSING_ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("SULU_ASSET_PROCESSING_ERROR: unexpected isolated Blender failure", file=sys.stderr)
        raise SystemExit(1) from None
