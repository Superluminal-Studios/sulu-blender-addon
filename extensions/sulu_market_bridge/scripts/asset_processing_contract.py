"""Pure validation and identity helpers for seller-side asset processing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import struct
import unicodedata
import uuid
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
PROCESSOR_NAME = "sulu-market-asset-processor"
PROCESSOR_VERSION = "0.1.0"
SUPPORTED_ID_TYPE = "OBJECT"
IMMUTABLE_ID_PROPERTY = "sulu_market_asset_id"

MAPPING_MAX_BYTES = 1024 * 1024
TRUSTED_METADATA_MAX_BYTES = 16 * 1024
DEFAULT_MAX_INPUT_BYTES = 4 * 1024**3
HARD_MAX_INPUT_BYTES = 4 * 1024**3
DEFAULT_MAX_ASSETS = 100
HARD_MAX_ASSETS = 500
DEFAULT_MAX_ARTIFACT_BYTES = 4 * 1024**3
HARD_MAX_ARTIFACT_BYTES = 4 * 1024**3
DEFAULT_MAX_TOTAL_OUTPUT_BYTES = 16 * 1024**3
HARD_MAX_TOTAL_OUTPUT_BYTES = 16 * 1024**3
MAX_PREVIEW_BYTES = 16 * 1024 * 1024
PREVIEW_WIDTH = 128
PREVIEW_HEIGHT = 128
PREVIEW_MEDIA_TYPE = "image/png"
PREVIEW_POLICY = "deterministic_png_v1"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_IMMUTABLE_ID_RE = re.compile(r"asset:sm_[A-Za-z0-9_-]{22,128}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_BUILD_HASH_RE = re.compile(r"[0-9a-f]{7,64}\Z")
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_SELLER_ORG_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")


class ContractError(ValueError):
    """A seller processing request or normalized manifest is invalid."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _expect_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _expect_exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if unknown:
            detail.append(f"unknown {unknown}")
        raise ContractError(f"{label} fields are invalid ({'; '.join(detail)})")


def _expect_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be an integer >= {minimum}")
    return value


def _expect_text(
    value: Any,
    label: str,
    *,
    maximum: int,
    allow_none: bool = False,
    allow_empty: bool = False,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    if not value and not allow_empty:
        raise ContractError(f"{label} must not be empty")
    if len(value) > maximum:
        raise ContractError(f"{label} exceeds {maximum} characters")
    if unicodedata.normalize("NFC", value) != value:
        raise ContractError(f"{label} must use NFC Unicode normalization")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ContractError(f"{label} contains a control or format character")
    return value


def read_strict_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    """Read a bounded UTF-8 JSON object and reject duplicate object fields."""

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
            raise ContractError("JSON input must be a non-symlink regular file")
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContractError("JSON input must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            raw = handle.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            raise ContractError(f"JSON input exceeds {maximum_bytes} bytes")
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ContractError(f"unsupported JSON constant: {value}")
            ),
        )
    except ContractError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("JSON input is not valid strict UTF-8 JSON") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _expect_object(value, "JSON input")


def load_trusted_metadata(path: Path) -> dict[str, str]:
    """Load server-owned legal identity that overrides seller-authored fields."""

    document = read_strict_json(path, maximum_bytes=TRUSTED_METADATA_MAX_BYTES)
    _expect_exact_fields(
        document,
        {"seller_org_id", "author", "license"},
        "trusted metadata",
    )
    seller_org_id = _expect_text(
        document["seller_org_id"], "trusted metadata seller_org_id", maximum=64
    )
    if not _SELLER_ORG_ID_RE.fullmatch(seller_org_id):
        raise ContractError("trusted metadata seller_org_id is malformed")
    author = _expect_text(document["author"], "trusted metadata author", maximum=255)
    license_name = _expect_text(
        document["license"], "trusted metadata license", maximum=64
    )
    return {
        "seller_org_id": seller_org_id,
        "author": author,
        "license": license_name,
    }


def validated_limit(value: int, *, label: str, hard_maximum: int) -> int:
    """Validate a caller-selected resource cap against the compiled hard maximum."""

    value = _expect_int(value, label, minimum=1)
    if value > hard_maximum:
        raise ContractError(f"{label} exceeds hard maximum {hard_maximum}")
    return value


def validate_asset_name(name: Any) -> str:
    return _expect_text(name, "asset name", maximum=255)  # type: ignore[return-value]


def source_key_for(name: str) -> str:
    return f"{SUPPORTED_ID_TYPE}:{validate_asset_name(name)}"


def validate_source_key(value: Any) -> str:
    value = _expect_text(value, "source_key", maximum=512)
    prefix = f"{SUPPORTED_ID_TYPE}:"
    if not value.startswith(prefix):
        raise ContractError("source_key must identify an OBJECT asset")
    if source_key_for(value[len(prefix) :]) != value:
        raise ContractError("source_key is not canonical")
    return value


def validate_immutable_id(value: Any) -> str:
    value = _expect_text(value, "immutable_id", maximum=140)
    if not _IMMUTABLE_ID_RE.fullmatch(value):
        raise ContractError("immutable_id must use the opaque asset:sm_ form")
    return value


def new_immutable_id(existing: set[str]) -> str:
    """Generate a non-semantic opaque ID, retrying on the theoretical collision case."""

    for _attempt in range(32):
        candidate = f"asset:sm_{secrets.token_urlsafe(24)}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("could not generate a unique immutable asset ID")


def artifact_relative_path(immutable_id: str) -> str:
    immutable_id = validate_immutable_id(immutable_id)
    digest = hashlib.sha256(immutable_id.encode("utf-8")).hexdigest()
    return f"artifacts/{digest}.blend"


def preview_relative_path(immutable_id: str) -> str:
    immutable_id = validate_immutable_id(immutable_id)
    digest = hashlib.sha256(immutable_id.encode("utf-8")).hexdigest()
    return f"previews/{digest}.png"


def validate_preview_png(path: Path) -> tuple[str, int]:
    """Validate the complete bounded canonical RGBA preview and return hash/size."""

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
            raise ContractError("preview must be a non-symlink regular file")
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContractError("preview must be a regular file")
        if opened.st_size < 57 or opened.st_size > MAX_PREVIEW_BYTES:
            raise ContractError("preview byte size is outside the canonical bounds")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            raw = handle.read(MAX_PREVIEW_BYTES + 1)
    except ContractError:
        raise
    except OSError as error:
        raise ContractError("preview cannot be read safely") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if len(raw) > MAX_PREVIEW_BYTES or not raw.startswith(_PNG_SIGNATURE):
        raise ContractError("preview is not a bounded canonical PNG")
    offset = len(_PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ContractError("preview PNG contains a truncated chunk")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(raw):
            raise ContractError("preview PNG contains an oversized chunk")
        chunk_type = raw[offset + 4 : offset + 8]
        payload = raw[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", raw[offset + 8 + length : chunk_end])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            raise ContractError("preview PNG contains a corrupt chunk")
        chunks.append((chunk_type, payload))
        offset = chunk_end
        if chunk_type == b"IEND":
            break
    if offset != len(raw) or not chunks or chunks[0][0] != b"IHDR" or chunks[-1][0] != b"IEND":
        raise ContractError("preview PNG has an invalid chunk envelope")
    if len(chunks[0][1]) != 13 or chunks[-1][1]:
        raise ContractError("preview PNG has invalid structural chunks")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1]
    )
    if (
        width != PREVIEW_WIDTH
        or height != PREVIEW_HEIGHT
        or bit_depth != 8
        or color_type != 6
        or compression != 0
        or filter_method != 0
        or interlace != 0
    ):
        raise ContractError("preview PNG does not use the canonical 128x128 RGBA format")
    idat = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    if not idat:
        raise ContractError("preview PNG contains no image data")
    try:
        pixels = zlib.decompress(idat)
    except zlib.error as error:
        raise ContractError("preview PNG image data is invalid") from error
    row_size = 1 + PREVIEW_WIDTH * 4
    if len(pixels) != PREVIEW_HEIGHT * row_size or any(
        pixels[offset] > 4 for offset in range(0, len(pixels), row_size)
    ):
        raise ContractError("preview PNG scanlines are invalid")
    return hashlib.sha256(raw).hexdigest(), len(raw)


def load_identity_mappings(path: Path | None) -> dict[str, str]:
    """Load strict server-owned source-key to immutable-ID mappings."""

    if path is None:
        return {}
    document = read_strict_json(path, maximum_bytes=MAPPING_MAX_BYTES)
    _expect_exact_fields(document, {"schema_version", "mappings"}, "mapping document")
    if document["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported mapping schema_version")
    entries = document["mappings"]
    if not isinstance(entries, list):
        raise ContractError("mappings must be an array")
    if len(entries) > HARD_MAX_ASSETS:
        raise ContractError("mapping count exceeds the hard maximum")

    mappings: dict[str, str] = {}
    used_ids: set[str] = set()
    for index, raw_entry in enumerate(entries):
        entry = _expect_object(raw_entry, f"mappings[{index}]")
        _expect_exact_fields(entry, {"source_key", "immutable_id"}, f"mappings[{index}]")
        source_key = validate_source_key(entry["source_key"])
        immutable_id = validate_immutable_id(entry["immutable_id"])
        if source_key in mappings:
            raise ContractError("mapping document contains a duplicate source_key")
        if immutable_id in used_ids:
            raise ContractError("mapping document contains a duplicate immutable_id")
        mappings[source_key] = immutable_id
        used_ids.add(immutable_id)
    return mappings


def mappings_document_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the server-owned reprocessing mapping document from a valid manifest."""

    validate_processing_manifest(manifest)
    return {
        "schema_version": SCHEMA_VERSION,
        "mappings": [
            {
                "source_key": asset["source_key"],
                "immutable_id": asset["immutable_id"],
            }
            for asset in manifest["assets"]
        ],
    }


def _validate_sha256(value: Any, label: str) -> str:
    value = _expect_text(value, label, maximum=64)
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _validate_version(value: Any, label: str) -> str:
    value = _expect_text(value, label, maximum=32)
    if not _VERSION_RE.fullmatch(value):
        raise ContractError(f"{label} must be a three-part numeric version")
    return value


def validate_blender_build_hash(value: Any) -> str:
    value = _expect_text(value, "Blender build hash", maximum=64)
    if not _BUILD_HASH_RE.fullmatch(value):
        raise ContractError("Blender build hash must be lowercase hexadecimal")
    return value


def _validate_catalog(value: Any, label: str) -> None:
    catalog = _expect_object(value, label)
    _expect_exact_fields(catalog, {"id", "name"}, label)
    catalog_id = catalog["id"]
    if catalog_id is not None:
        catalog_id = _expect_text(catalog_id, f"{label}.id", maximum=36)
        try:
            parsed = uuid.UUID(catalog_id)
        except (ValueError, AttributeError) as error:
            raise ContractError(f"{label}.id must be a UUID or null") from error
        if str(parsed) != catalog_id or parsed.int == 0:
            raise ContractError(f"{label}.id must be a canonical non-nil UUID")
    _expect_text(catalog["name"], f"{label}.name", maximum=255, allow_none=True)


def _validate_metadata(value: Any, label: str) -> None:
    metadata = _expect_object(value, label)
    fields = {"description", "author", "license", "copyright", "tags"}
    _expect_exact_fields(metadata, fields, label)
    for field in fields - {"tags"}:
        _expect_text(
            metadata[field],
            f"{label}.{field}",
            maximum=2048,
            allow_none=True,
        )
    tags = metadata["tags"]
    if not isinstance(tags, list) or len(tags) > 64:
        raise ContractError(f"{label}.tags must be an array with at most 64 entries")
    normalized_tags = [
        _expect_text(tag, f"{label}.tags[{index}]", maximum=128) for index, tag in enumerate(tags)
    ]
    if normalized_tags != sorted(set(normalized_tags)):
        raise ContractError(f"{label}.tags must be unique and sorted")


def validate_processing_manifest(manifest: Any) -> dict[str, Any]:
    """Strictly validate the normalized processing manifest, including unknown fields."""

    root = _expect_object(manifest, "manifest")
    _expect_exact_fields(
        root,
        {"schema_version", "preview_policy", "processor", "source", "assets"},
        "manifest",
    )
    if root["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported manifest schema_version")
    if root["preview_policy"] != PREVIEW_POLICY:
        raise ContractError("unsupported manifest preview_policy")

    processor = _expect_object(root["processor"], "processor")
    _expect_exact_fields(
        processor,
        {"name", "version", "blender_version", "blender_build_hash"},
        "processor",
    )
    if processor["name"] != PROCESSOR_NAME or processor["version"] != PROCESSOR_VERSION:
        raise ContractError("manifest processor identity is invalid")
    _validate_version(processor["blender_version"], "processor.blender_version")
    validate_blender_build_hash(processor["blender_build_hash"])

    source = _expect_object(root["source"], "source")
    _expect_exact_fields(source, {"sha256", "size", "blender_version"}, "source")
    _validate_sha256(source["sha256"], "source.sha256")
    _expect_int(source["size"], "source.size", minimum=1)
    _validate_version(source["blender_version"], "source.blender_version")

    assets = root["assets"]
    if not isinstance(assets, list) or not 1 <= len(assets) <= HARD_MAX_ASSETS:
        raise ContractError("assets must be a non-empty bounded array")
    seen_source_keys: set[str] = set()
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, raw_asset in enumerate(assets):
        label = f"assets[{index}]"
        asset = _expect_object(raw_asset, label)
        _expect_exact_fields(
            asset,
            {
                "source_key",
                "name",
                "id_type",
                "immutable_id",
                "identity_source",
                "catalog",
                "metadata",
                "blender",
                "artifact",
                "preview",
            },
            label,
        )
        source_key = validate_source_key(asset["source_key"])
        name = validate_asset_name(asset["name"])
        if source_key != source_key_for(name) or asset["id_type"] != SUPPORTED_ID_TYPE:
            raise ContractError(f"{label} OBJECT identity fields disagree")
        immutable_id = validate_immutable_id(asset["immutable_id"])
        if asset["identity_source"] not in {"existing", "generated"}:
            raise ContractError(f"{label}.identity_source is invalid")
        _validate_catalog(asset["catalog"], f"{label}.catalog")
        _validate_metadata(asset["metadata"], f"{label}.metadata")

        blender = _expect_object(asset["blender"], f"{label}.blender")
        _expect_exact_fields(
            blender,
            {"minimum_version", "source_version", "processed_version"},
            f"{label}.blender",
        )
        for field in ("minimum_version", "source_version", "processed_version"):
            _validate_version(blender[field], f"{label}.blender.{field}")

        artifact = _expect_object(asset["artifact"], f"{label}.artifact")
        _expect_exact_fields(artifact, {"path", "sha256", "size"}, f"{label}.artifact")
        artifact_path = _expect_text(artifact["path"], f"{label}.artifact.path", maximum=256)
        posix_path = PurePosixPath(artifact_path)
        if (
            posix_path.is_absolute()
            or ".." in posix_path.parts
            or artifact_path != artifact_relative_path(immutable_id)
        ):
            raise ContractError(f"{label}.artifact.path is not canonical")
        _validate_sha256(artifact["sha256"], f"{label}.artifact.sha256")
        _expect_int(artifact["size"], f"{label}.artifact.size", minimum=1)

        preview = _expect_object(asset["preview"], f"{label}.preview")
        _expect_exact_fields(
            preview,
            {"path", "sha256", "size", "width", "height", "media_type"},
            f"{label}.preview",
        )
        preview_path = _expect_text(preview["path"], f"{label}.preview.path", maximum=256)
        preview_posix = PurePosixPath(preview_path)
        if (
            preview_posix.is_absolute()
            or ".." in preview_posix.parts
            or preview_path != preview_relative_path(immutable_id)
        ):
            raise ContractError(f"{label}.preview.path is not canonical")
        _validate_sha256(preview["sha256"], f"{label}.preview.sha256")
        preview_size = _expect_int(preview["size"], f"{label}.preview.size", minimum=1)
        if preview_size > MAX_PREVIEW_BYTES:
            raise ContractError(f"{label}.preview.size exceeds the hard maximum")
        if (
            preview["width"] != PREVIEW_WIDTH
            or preview["height"] != PREVIEW_HEIGHT
            or preview["media_type"] != PREVIEW_MEDIA_TYPE
        ):
            raise ContractError(f"{label}.preview format is not canonical")

        if (
            source_key in seen_source_keys
            or immutable_id in seen_ids
            or artifact_path in seen_paths
            or preview_path in seen_paths
        ):
            raise ContractError("manifest asset identities and paths must be unique")
        seen_source_keys.add(source_key)
        seen_ids.add(immutable_id)
        seen_paths.add(artifact_path)
        seen_paths.add(preview_path)

    if [asset["source_key"] for asset in assets] != sorted(seen_source_keys):
        raise ContractError("manifest assets must be sorted by source_key")
    return root
