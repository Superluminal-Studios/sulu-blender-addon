"""Run inside official Blender after installing the packaged extension."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import bpy


def arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


slow_descriptor_path = Path(arguments()[0]).resolve()
descriptor_path = Path(arguments()[1]).resolve()
origin = arguments()[2]
expected_sha256 = arguments()[3]
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

addon = importlib.import_module(module_name + ".addon")
bridge = importlib.import_module(module_name + ".sulu_bridge")


def active_operator():  # noqa: ANN201
    operator = addon._ACTIVE_IMPORT_OPERATOR
    if operator is None or operator._job is None:
        raise RuntimeError("Modal Sulu Market worker was not retained after startup")
    return operator


def poll_terminal(operator, *, timeout: float = 10.0):  # noqa: ANN001, ANN201
    deadline = time.monotonic() + timeout
    while operator._job is not None and operator._job.is_alive():
        if time.monotonic() >= deadline:
            raise RuntimeError("Modal Sulu Market worker did not terminate")
        time.sleep(0.01)
    result = operator.modal(bpy.context, SimpleNamespace(type="TIMER"))
    if addon._ACTIVE_IMPORT_OPERATOR is not None:
        raise RuntimeError("Terminal modal result left the global import guard active")
    if operator._job is not None or operator._timer is not None or operator._cancel_requested:
        raise RuntimeError("Terminal modal result leaked worker, timer, or cancellation state")
    return result


# EXEC_DEFAULT is how the FileHandler dispatches a dropped descriptor. The mock deliberately
# stalls this download, proving that dispatch returns while pure preparation is still running.
started_at = time.monotonic()
result = bpy.ops.sulu_market.import_asset("EXEC_DEFAULT", filepath=str(slow_descriptor_path))
start_elapsed = time.monotonic() - started_at
if result != {"RUNNING_MODAL"}:
    raise RuntimeError(f"FileHandler-style import did not start modally: {result}")
slow_operator = active_operator()
if start_elapsed >= 1.0 or not slow_operator._job.is_alive():
    raise RuntimeError(
        f"EXEC_DEFAULT blocked instead of returning an active modal worker ({start_elapsed:.3f}s)"
    )

# A second operator cannot create another worker/timer while one import owns the guard.
duplicate = bpy.ops.sulu_market.import_asset("EXEC_DEFAULT", filepath=str(descriptor_path))
if duplicate != {"CANCELLED"}:
    raise RuntimeError(f"Duplicate Sulu Market import was not rejected: {duplicate}")
if active_operator() is not slow_operator:
    raise RuntimeError("Duplicate import replaced the active guarded worker")

# Give the local worker enough time to reach the mock's deliberately half-sent response. It must
# still be alive there; otherwise the mock did not exercise cancellation of blocking network I/O.
time.sleep(0.25)
if not slow_operator._job.is_alive():
    raise RuntimeError("Slow EXEC_DEFAULT worker ended before the blocked response was released")

if slow_operator.modal(bpy.context, SimpleNamespace(type="ESC")) != {"RUNNING_MODAL"}:
    raise RuntimeError("ESC did not cooperatively cancel the modal worker")
if poll_terminal(slow_operator) != {"CANCELLED"}:
    raise RuntimeError("Cancelled EXEC_DEFAULT import did not terminate as CANCELLED")

# File-selector completion uses invoke-with-filepath and must share the same guarded worker path.
invoke_started_at = time.monotonic()
invoke_result = bpy.ops.sulu_market.import_asset(
    "INVOKE_DEFAULT",
    filepath=str(slow_descriptor_path),
)
invoke_elapsed = time.monotonic() - invoke_started_at
if invoke_result != {"RUNNING_MODAL"} or invoke_elapsed >= 1.0:
    raise RuntimeError("Invoke-with-filepath did not return through the non-blocking modal path")
invoke_operator = active_operator()
time.sleep(0.25)
if not invoke_operator._job.is_alive():
    raise RuntimeError("Invoke-with-filepath did not retain its active pure worker")
invoke_operator.modal(bpy.context, SimpleNamespace(type="ESC"))
if poll_terminal(invoke_operator) != {"CANCELLED"}:
    raise RuntimeError("Cancelled invoke-with-filepath import did not cleanly terminate")

bpy.context.scene.cursor.location = (1.25, -2.5, 3.75)
result = bpy.ops.sulu_market.import_asset("EXEC_DEFAULT", filepath=str(descriptor_path))
if result != {"RUNNING_MODAL"}:
    raise RuntimeError(f"Sulu Market import operator did not start modally: {result}")
successful_operator = active_operator()
if poll_terminal(successful_operator) != {"FINISHED"}:
    raise RuntimeError("Sulu Market modal import did not finish")

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
    compatibility=bridge.BridgeCompatibility(
        protocol_version=1,
        bridge_min_version="0.1.0",
        bridge_max_version_exclusive="0.2.0",
        blender_min_version="5.2.0",
        blender_max_version_exclusive="5.3.0",
    ),
    server_max_artifact_bytes=4 * 1024**3,
)
wrong_prepared = bridge.PreparedAsset(
    descriptor=bridge.Descriptor(
        schema_version=1,
        api_origin=origin,
        ticket="unused-ticket-123456789",
        compatibility=wrong_grant.compatibility,
        display=bridge.DisplayHints(),
    ),
    grant=wrong_grant,
    cache=bridge.CacheResult(path=cached, reused=True),
)
counts_before_failed_import = {
    "objects": len(bpy.data.objects),
    "meshes": len(bpy.data.meshes),
    "materials": len(bpy.data.materials),
    "images": len(bpy.data.images),
}
try:
    addon.import_prepared_asset(bpy.context, wrong_prepared)
except bridge.ImportAssetError as exc:
    if "identity does not match" not in str(exc):
        raise
else:
    raise RuntimeError("Wrong immutable asset identity was accepted")
if any(obj.get("sulu_market_asset_id") == "asset:wrong-identity:v1" for obj in bpy.data.objects):
    raise RuntimeError("Wrong immutable object survived failed import")
counts_after_failed_import = {
    "objects": len(bpy.data.objects),
    "meshes": len(bpy.data.meshes),
    "materials": len(bpy.data.materials),
    "images": len(bpy.data.images),
}
if counts_after_failed_import != counts_before_failed_import:
    raise RuntimeError(
        "Failed entitlement import leaked appended Blender dependencies: "
        f"before={counts_before_failed_import}, after={counts_after_failed_import}"
    )

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
    compatibility=wrong_grant.compatibility,
    server_max_artifact_bytes=wrong_grant.server_max_artifact_bytes,
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
    if replay != {"RUNNING_MODAL"}:
        raise RuntimeError("Replayed descriptor did not enter the guarded modal path")
    replay_operator = active_operator()
    replay_terminal = poll_terminal(replay_operator)
    if replay_terminal != {"CANCELLED"}:
        raise RuntimeError("A replayed one-use descriptor ticket was accepted")

print(
    "SULU_BRIDGE_E2E_OK "
    + json.dumps(
        {
            "blender": bpy.app.version_string,
            "file_handler": True,
            "exec_default_modal_seconds": round(start_elapsed, 6),
            "invoke_filepath_modal_seconds": round(invoke_elapsed, 6),
            "duplicate_start_denied": True,
            "cancellation_cleanup": True,
            "error_cleanup": True,
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
