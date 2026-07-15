"""Run inside official Blender after installing the packaged extension."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import bpy


def arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


descriptor_path = Path(arguments()[0]).resolve()
origin = arguments()[1]
expected_sha256 = arguments()[2]
module_name = "bl_ext.user_default.sulu_market_bridge"

if module_name not in bpy.context.preferences.addons:
    raise RuntimeError("Packaged Sulu Market Bridge is not enabled")
if not hasattr(bpy.types, "SULU_MARKET_FH_asset"):
    raise RuntimeError(".suluasset FileHandler is not registered")
if not hasattr(bpy.ops.sulu_market, "import_asset"):
    raise RuntimeError("Sulu Market import operator is not registered")

preferences = bpy.context.preferences.addons[module_name].preferences
preferences.api_origin = origin
preferences.allow_insecure_localhost = True
preferences.timeout_seconds = 10
preferences.max_download_mib = 64

bpy.context.scene.cursor.location = (1.25, -2.5, 3.75)
result = bpy.ops.sulu_market.import_asset("EXEC_DEFAULT", filepath=str(descriptor_path))
if result != {"FINISHED"}:
    raise RuntimeError(f"Sulu Market import operator failed: {result}")

matching = [
    obj for obj in bpy.data.objects if obj.get("sulu_market_asset_id") == "asset:sulu-fixture:v1"
]
if len(matching) != 1:
    raise RuntimeError(f"Expected one exact immutable object, found {len(matching)}")
imported = matching[0]
if imported.name != "SuluFixtureObject":
    raise RuntimeError(f"Wrong object imported: {imported.name}")
if imported.asset_data is None:
    raise RuntimeError("Imported object is not marked as an asset")
if tuple(round(value, 4) for value in imported.matrix_world.translation) != (1.25, -2.5, 3.75):
    raise RuntimeError("Imported object was not placed at the documented 3D cursor position")
if not any(
    imported.name in collection.objects
    for collection in bpy.context.scene.collection.children_recursive
):
    if imported.name not in bpy.context.scene.collection.objects:
        raise RuntimeError("Imported object is not linked to the active scene")

addon = importlib.import_module(module_name + ".addon")
bridge = importlib.import_module(module_name + ".sulu_bridge")
cache_root = Path(
    bpy.utils.user_resource(
        "DATAFILES",
        path="sulu_market_bridge/redeemed_assets",
        create=False,
    )
).resolve()
cached = cache_root / "objects" / expected_sha256[:2] / f"{expected_sha256}.blend"
if not cached.is_file():
    raise RuntimeError("Verified content-addressed cache entry is missing")
if hashlib.sha256(cached.read_bytes()).hexdigest() != expected_sha256:
    raise RuntimeError("Cached Blender artifact hash changed after verification")

libraries = bpy.context.preferences.filepaths.asset_libraries
registered = [
    library for library in libraries if Path(bpy.path.abspath(library.path)).resolve() == cache_root
]
if len(registered) != 1 or not registered[0].enabled or registered[0].import_method != "APPEND":
    raise RuntimeError("Redeemed asset cache was not safely registered as a local asset library")

# The exact immutable marker is authoritative in addition to type/name/hash.
wrong_grant = bridge.RedeemGrant(
    schema_version=1,
    claim_id="claim-wrong-id-123",
    download_path="/api/market/assets/download/claim-wrong-id-123",
    download_token="unused-download-token-123",
    artifact=bridge.ArtifactSpec(sha256=expected_sha256, size=cached.stat().st_size),
    asset=bridge.AssetIdentity(
        immutable_id="asset:wrong-identity:v1",
        id_type="OBJECT",
        name="SuluFixtureObject",
        import_method="APPEND",
    ),
)
wrong_prepared = bridge.PreparedAsset(
    descriptor=bridge.Descriptor(
        schema_version=1,
        api_origin=origin,
        ticket="unused-ticket-123456789",
        display=bridge.DisplayHints(),
    ),
    grant=wrong_grant,
    cache=bridge.CacheResult(path=cached, reused=True),
)
try:
    addon.import_prepared_asset(bpy.context, wrong_prepared)
except bridge.ImportAssetError as exc:
    if "identity does not match" not in str(exc):
        raise
else:
    raise RuntimeError("Wrong immutable asset identity was accepted")
if any(obj.get("sulu_market_asset_id") == "asset:wrong-identity:v1" for obj in bpy.data.objects):
    raise RuntimeError("Wrong immutable object survived failed import")

# V1 is deliberately narrow: non-OBJECT ID types fail explicitly instead of
# guessing a target or mutating arbitrary selected datablocks.
unsupported_grant = bridge.RedeemGrant(
    schema_version=1,
    claim_id="claim-material-123",
    download_path="/api/market/assets/download/claim-material-123",
    download_token="unused-download-token-123",
    artifact=wrong_grant.artifact,
    asset=bridge.AssetIdentity(
        immutable_id="asset:sulu-fixture:v1",
        id_type="MATERIAL",
        name="SuluFixtureObject",
        import_method="APPEND",
    ),
)
unsupported_prepared = bridge.PreparedAsset(
    descriptor=wrong_prepared.descriptor,
    grant=unsupported_grant,
    cache=wrong_prepared.cache,
)
try:
    addon.import_prepared_asset(bpy.context, unsupported_prepared)
except bridge.ImportAssetError as exc:
    if "MATERIAL is not supported yet" not in str(exc):
        raise
else:
    raise RuntimeError("Unsupported MATERIAL import was accepted")

# The mock atomically consumed the descriptor ticket during the first import.
# Blender raises a RuntimeError for an operator ERROR report in Python contexts;
# interactive invocation receives the normal CANCELLED result and visible report.
try:
    replay = bpy.ops.sulu_market.import_asset("EXEC_DEFAULT", filepath=str(descriptor_path))
except RuntimeError as exc:
    if "invalid, expired, or used" not in str(exc):
        raise
else:
    if replay != {"CANCELLED"}:
        raise RuntimeError("A replayed one-use descriptor ticket was accepted")

print(
    "SULU_BRIDGE_E2E_OK "
    + json.dumps(
        {
            "blender": bpy.app.version_string,
            "file_handler": True,
            "operator": True,
            "object": imported.name,
            "immutable_id": imported["sulu_market_asset_id"],
            "cache_sha256": expected_sha256,
            "asset_library": registered[0].name,
            "replay_denied": True,
            "unsupported_type_denied": True,
            "wrong_identity_denied": True,
        },
        sort_keys=True,
    )
)
