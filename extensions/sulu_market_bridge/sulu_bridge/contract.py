"""Strict version-one wire contract for ``.suluasset`` files.

Descriptors intentionally contain no durable repository or device credential.
The opaque ticket is short-lived and one-use; it is sent only in the body of a
POST request. Server responses are similarly strict so they cannot turn the
bridge into an arbitrary URL fetcher.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

from .errors import ContractError

SCHEMA_VERSION = 1
DEFAULT_API_ORIGIN = "https://api.superlumin.al"
REDEEM_PATH = "/api/market/assets/redeem"
DOWNLOAD_PATH_PREFIX = "/api/market/assets/download/"
DESCRIPTOR_MAX_BYTES = 16 * 1024
REDEEM_RESPONSE_MAX_BYTES = 64 * 1024
DEFAULT_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
BRIDGE_PROTOCOL_VERSION = 1
BRIDGE_VERSION = "0.1.0"

_OPAQUE_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
_CLAIM_ID_RE = re.compile(r"^[A-Za-z0-9._~-]{8,256}$")
_DOWNLOAD_PATH_RE = re.compile(r"^/api/market/assets/download/[A-Za-z0-9._~-]{8,512}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
_IMMUTABLE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


@dataclass(frozen=True, slots=True)
class DisplayHints:
    name: str | None = None
    id_type: str | None = None


@dataclass(frozen=True, slots=True)
class Descriptor:
    schema_version: int
    api_origin: str
    ticket: str
    compatibility: BridgeCompatibility
    display: DisplayHints


@dataclass(frozen=True, slots=True)
class BridgeCompatibility:
    protocol_version: int
    bridge_min_version: str
    bridge_max_version_exclusive: str
    blender_min_version: str
    blender_max_version_exclusive: str


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    immutable_id: str
    id_type: str
    name: str
    import_method: str


@dataclass(frozen=True, slots=True)
class RedeemGrant:
    schema_version: int
    claim_id: str
    download_path: str
    download_token: str
    artifact: ArtifactSpec
    asset: AssetIdentity
    compatibility: BridgeCompatibility
    server_max_artifact_bytes: int


def _reject_json_constant(value: str) -> NoReturn:
    raise ContractError("JSON constants such as NaN and Infinity are not allowed")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _decode_json(raw: bytes, *, label: str, max_bytes: int) -> dict[str, Any]:
    if not raw:
        raise ContractError(f"{label} is empty")
    if len(raw) > max_bytes:
        raise ContractError(f"{label} exceeds the {max_bytes}-byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{label} must be UTF-8 JSON") from exc
    if text.startswith("\ufeff"):
        raise ContractError(f"{label} must not contain a UTF-8 BOM")
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ContractError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ContractError(f"{label} is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ContractError(f"{label} must contain a JSON object")
    return decoded


def _require_exact_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    label: str,
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ContractError(f"{label} is missing required fields")
    if unknown:
        raise ContractError(f"{label} contains unsupported fields")


def _require_version(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != SCHEMA_VERSION:
        raise ContractError(f"{label} uses an unsupported schema version")
    return value


def _parse_semver(value: Any, *, label: str) -> tuple[int, int, int]:
    value = _require_string(value, label=label, maximum=32)
    match = _SEMVER_RE.fullmatch(value)
    if match is None:
        raise ContractError(f"{label} must be a three-part numeric version")
    return tuple(int(part) for part in match.groups())


def _parse_compatibility(value: Any, *, label: str) -> BridgeCompatibility:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    _require_exact_keys(
        value,
        required={
            "protocol_version",
            "bridge_min_version",
            "bridge_max_version_exclusive",
            "blender_min_version",
            "blender_max_version_exclusive",
        },
        label=label,
    )
    protocol = value["protocol_version"]
    if isinstance(protocol, bool) or not isinstance(protocol, int):
        raise ContractError(f"{label} protocol version is invalid")
    if protocol != BRIDGE_PROTOCOL_VERSION:
        raise ContractError(
            f"This asset requires protocol {protocol}; update the Sulu Market Bridge"
        )
    bridge_min = _require_string(
        value["bridge_min_version"], label=f"{label} bridge minimum", maximum=32
    )
    bridge_max = _require_string(
        value["bridge_max_version_exclusive"],
        label=f"{label} bridge maximum",
        maximum=32,
    )
    blender_min = _require_string(
        value["blender_min_version"], label=f"{label} Blender minimum", maximum=32
    )
    blender_max = _require_string(
        value["blender_max_version_exclusive"],
        label=f"{label} Blender maximum",
        maximum=32,
    )
    if _parse_semver(bridge_min, label=f"{label} bridge minimum") >= _parse_semver(
        bridge_max, label=f"{label} bridge maximum"
    ):
        raise ContractError(f"{label} Bridge version range is empty")
    if _parse_semver(blender_min, label=f"{label} Blender minimum") >= _parse_semver(
        blender_max, label=f"{label} Blender maximum"
    ):
        raise ContractError(f"{label} Blender version range is empty")
    return BridgeCompatibility(
        protocol_version=protocol,
        bridge_min_version=bridge_min,
        bridge_max_version_exclusive=bridge_max,
        blender_min_version=blender_min,
        blender_max_version_exclusive=blender_max,
    )


def validate_runtime_compatibility(
    compatibility: BridgeCompatibility,
    *,
    bridge_version: str = BRIDGE_VERSION,
    blender_version: str,
) -> None:
    """Fail before ticket redemption when the installed runtime is unsupported."""

    bridge = _parse_semver(bridge_version, label="Installed Bridge version")
    blender = _parse_semver(blender_version, label="Installed Blender version")
    bridge_min = _parse_semver(
        compatibility.bridge_min_version, label="Required Bridge minimum"
    )
    bridge_max = _parse_semver(
        compatibility.bridge_max_version_exclusive, label="Required Bridge maximum"
    )
    blender_min = _parse_semver(
        compatibility.blender_min_version, label="Required Blender minimum"
    )
    blender_max = _parse_semver(
        compatibility.blender_max_version_exclusive, label="Required Blender maximum"
    )
    if not bridge_min <= bridge < bridge_max:
        raise ContractError(
            "Update the Sulu Market Bridge; this asset requires Bridge "
            f">={compatibility.bridge_min_version} and "
            f"<{compatibility.bridge_max_version_exclusive}"
        )
    if not blender_min <= blender < blender_max:
        raise ContractError(
            "Use a compatible Blender version; this asset requires Blender "
            f">={compatibility.blender_min_version} and "
            f"<{compatibility.blender_max_version_exclusive}"
        )


def _require_string(
    value: Any,
    *,
    label: str,
    minimum: int = 1,
    maximum: int,
    allow_controls: bool = False,
) -> str:
    if not isinstance(value, str) or not (minimum <= len(value) <= maximum):
        raise ContractError(f"{label} has an invalid length")
    if not allow_controls and any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ContractError(f"{label} contains control characters")
    return value


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def normalize_api_origin(origin: Any, *, allow_insecure_localhost: bool = False) -> str:
    """Validate and canonicalize an API *origin*, never a general URL."""

    origin = _require_string(origin, label="API origin", maximum=2048)
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise ContractError("API origin is malformed") from exc

    if parsed.username is not None or parsed.password is not None:
        raise ContractError("API origin must not contain user information")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ContractError("API origin must not contain a path, query, or fragment")
    hostname = parsed.hostname
    if not hostname:
        raise ContractError("API origin must include a hostname")

    scheme = parsed.scheme.lower()
    hostname = hostname.lower()
    is_loopback = _is_loopback_hostname(hostname)
    if scheme != "https":
        if not (allow_insecure_localhost and scheme == "http" and is_loopback):
            raise ContractError("API origin must use HTTPS")
    if not parsed.netloc:
        raise ContractError("API origin is malformed")

    if ":" in hostname:
        host_text = f"[{hostname}]"
    else:
        try:
            host_text = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ContractError("API origin hostname is malformed") from exc

    default_port = 443 if scheme == "https" else 80
    port_text = "" if port is None or port == default_port else f":{port}"
    return f"{scheme}://{host_text}{port_text}"


def _parse_opaque(value: Any, *, label: str, minimum: int = 16) -> str:
    value = _require_string(value, label=label, minimum=minimum, maximum=4096)
    if not _OPAQUE_RE.fullmatch(value):
        raise ContractError(f"{label} contains unsupported characters")
    return value


def parse_descriptor_bytes(
    raw: bytes,
    *,
    configured_origin: str = DEFAULT_API_ORIGIN,
    allow_insecure_localhost: bool = False,
) -> Descriptor:
    payload = _decode_json(raw, label="Asset descriptor", max_bytes=DESCRIPTOR_MAX_BYTES)
    _require_exact_keys(
        payload,
        required={"schema_version", "api_origin", "ticket", "compatibility"},
        optional={"display"},
        label="Asset descriptor",
    )
    schema_version = _require_version(payload["schema_version"], label="Asset descriptor")
    approved = normalize_api_origin(
        configured_origin, allow_insecure_localhost=allow_insecure_localhost
    )
    api_origin = normalize_api_origin(
        payload["api_origin"], allow_insecure_localhost=allow_insecure_localhost
    )
    if api_origin != approved:
        raise ContractError("Asset descriptor API origin is not the configured Sulu origin")
    ticket = _parse_opaque(payload["ticket"], label="Asset descriptor ticket")
    compatibility = _parse_compatibility(
        payload["compatibility"], label="Asset descriptor compatibility"
    )

    display_value = payload.get("display", {})
    if not isinstance(display_value, dict):
        raise ContractError("Asset descriptor display hints must be an object")
    _require_exact_keys(
        display_value,
        required=set(),
        optional={"name", "id_type"},
        label="Asset descriptor display hints",
    )
    name = display_value.get("name")
    if name is not None:
        name = _require_string(name, label="Display name", maximum=255)
    id_type = display_value.get("id_type")
    if id_type is not None:
        id_type = _require_string(id_type, label="Display ID type", maximum=32)
        if not _ID_TYPE_RE.fullmatch(id_type):
            raise ContractError("Display ID type is malformed")

    return Descriptor(
        schema_version=schema_version,
        api_origin=api_origin,
        ticket=ticket,
        compatibility=compatibility,
        display=DisplayHints(name=name, id_type=id_type),
    )


def parse_descriptor_file(
    path: str | Path,
    *,
    configured_origin: str = DEFAULT_API_ORIGIN,
    allow_insecure_localhost: bool = False,
) -> Descriptor:
    descriptor_path = Path(path)
    if descriptor_path.suffix.lower() != ".suluasset":
        raise ContractError("Asset descriptor must use the .suluasset extension")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    file_descriptor = -1
    try:
        if not hasattr(os, "O_NOFOLLOW") and descriptor_path.is_symlink():
            raise ContractError("Asset descriptor must be a non-symlink regular file")
        file_descriptor = os.open(descriptor_path, flags)
        file_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ContractError("Asset descriptor must be a regular file")
        with os.fdopen(file_descriptor, "rb", closefd=True) as handle:
            file_descriptor = -1
            raw = handle.read(DESCRIPTOR_MAX_BYTES + 1)
        if len(raw) > DESCRIPTOR_MAX_BYTES:
            raise ContractError(f"Asset descriptor exceeds the {DESCRIPTOR_MAX_BYTES}-byte limit")
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("Asset descriptor could not be read") from exc
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    return parse_descriptor_bytes(
        raw,
        configured_origin=configured_origin,
        allow_insecure_localhost=allow_insecure_localhost,
    )


def _parse_download_path(value: Any) -> str:
    value = _require_string(value, label="Download path", maximum=1024)
    if not _DOWNLOAD_PATH_RE.fullmatch(value):
        raise ContractError("Download path is outside the Sulu asset download endpoint")
    return value


def parse_redeem_response(
    raw: bytes,
    *,
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> RedeemGrant:
    if isinstance(max_artifact_bytes, bool) or not isinstance(max_artifact_bytes, int):
        raise ContractError("Maximum artifact size is invalid")
    if max_artifact_bytes < 1:
        raise ContractError("Maximum artifact size is invalid")

    payload = _decode_json(
        raw,
        label="Redemption response",
        max_bytes=REDEEM_RESPONSE_MAX_BYTES,
    )
    _require_exact_keys(
        payload,
        required={
            "schema_version",
            "claim_id",
            "download_path",
            "download_token",
            "artifact",
            "asset",
            "compatibility",
            "limits",
        },
        label="Redemption response",
    )
    schema_version = _require_version(payload["schema_version"], label="Redemption response")

    claim_id = _require_string(payload["claim_id"], label="Claim ID", maximum=256)
    if not _CLAIM_ID_RE.fullmatch(claim_id):
        raise ContractError("Claim ID is malformed")
    download_path = _parse_download_path(payload["download_path"])
    if download_path != DOWNLOAD_PATH_PREFIX + claim_id:
        raise ContractError("Download path does not match the redeemed claim ID")
    download_token = _parse_opaque(payload["download_token"], label="Download token")
    compatibility = _parse_compatibility(
        payload["compatibility"], label="Redemption compatibility"
    )

    limits = payload["limits"]
    if not isinstance(limits, dict):
        raise ContractError("Redemption limits must be an object")
    _require_exact_keys(
        limits,
        required={"max_artifact_bytes"},
        label="Redemption limits",
    )
    server_max_artifact_bytes = limits["max_artifact_bytes"]
    if (
        isinstance(server_max_artifact_bytes, bool)
        or not isinstance(server_max_artifact_bytes, int)
        or server_max_artifact_bytes < 1
        or server_max_artifact_bytes > DEFAULT_MAX_ARTIFACT_BYTES
    ):
        raise ContractError("Server artifact limit is invalid")

    artifact = payload["artifact"]
    if not isinstance(artifact, dict):
        raise ContractError("Artifact metadata must be an object")
    _require_exact_keys(
        artifact,
        required={"sha256", "size"},
        label="Artifact metadata",
    )
    sha256 = _require_string(artifact["sha256"], label="Artifact SHA-256", maximum=64)
    if not _SHA256_RE.fullmatch(sha256):
        raise ContractError("Artifact SHA-256 must be lowercase hexadecimal")
    size = artifact["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ContractError("Artifact size is invalid")
    if size > min(max_artifact_bytes, server_max_artifact_bytes):
        raise ContractError("Artifact exceeds the configured download limit")

    asset = payload["asset"]
    if not isinstance(asset, dict):
        raise ContractError("Asset identity must be an object")
    _require_exact_keys(
        asset,
        required={"immutable_id", "id_type", "name", "import_method"},
        label="Asset identity",
    )
    immutable_id = _require_string(asset["immutable_id"], label="Immutable asset ID", maximum=256)
    if not _IMMUTABLE_ID_RE.fullmatch(immutable_id):
        raise ContractError("Immutable asset ID is malformed")
    id_type = _require_string(asset["id_type"], label="Asset ID type", maximum=32)
    if not _ID_TYPE_RE.fullmatch(id_type):
        raise ContractError("Asset ID type is malformed")
    name = _require_string(asset["name"], label="Asset datablock name", maximum=255)
    import_method = _require_string(asset["import_method"], label="Asset import method", maximum=32)
    if import_method != "APPEND":
        raise ContractError("This bridge version only supports the APPEND import method")

    return RedeemGrant(
        schema_version=schema_version,
        claim_id=claim_id,
        download_path=download_path,
        download_token=download_token,
        artifact=ArtifactSpec(sha256=sha256, size=size),
        asset=AssetIdentity(
            immutable_id=immutable_id,
            id_type=id_type,
            name=name,
            import_method=import_method,
        ),
        compatibility=compatibility,
        server_max_artifact_bytes=server_max_artifact_bytes,
    )
