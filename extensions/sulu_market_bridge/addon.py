# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender registration and exact asset import integration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from .sulu_bridge import (
    DEFAULT_API_ORIGIN,
    BridgeError,
    CancellationToken,
    ImportAssetError,
    ModalPreparationWorker,
    PreparedAsset,
    normalize_api_origin,
    redeem_descriptor,
)

ADDON_MODULE = __package__
CACHE_LIBRARY_NAME = "Sulu Market Redeemed Assets"
IMMUTABLE_ASSET_ID_PROPERTY = "sulu_market_asset_id"
_ACTIVE_IMPORT_OPERATOR: SULU_MARKET_OT_import_asset | None = None


def _preferences(context: bpy.types.Context) -> SULU_MARKET_Preferences:
    addon = context.preferences.addons.get(ADDON_MODULE)
    if addon is None:
        raise ImportAssetError("Sulu Market Bridge preferences are unavailable")
    return addon.preferences


def _cache_root() -> Path:
    path = bpy.utils.user_resource(
        "DATAFILES",
        path="sulu_market_bridge/redeemed_assets",
        create=True,
    )
    if not path:
        raise ImportAssetError("Blender could not create the Sulu Market asset cache")
    return Path(os.path.abspath(path))


def _register_local_asset_library(context: bpy.types.Context, cache_root: Path) -> bool:
    """Register the verified cache in current preferences without forcing a save."""

    try:
        canonical = os.path.normcase(os.path.realpath(cache_root))
        libraries = context.preferences.filepaths.asset_libraries
        for library in libraries:
            if not library.path:
                continue
            if os.path.normcase(os.path.realpath(bpy.path.abspath(library.path))) == canonical:
                library.enabled = True
                if library.import_method != "APPEND":
                    library.import_method = "APPEND"
                return False
        library = libraries.new(name=CACHE_LIBRARY_NAME, directory=str(cache_root))
        library.enabled = True
        library.import_method = "APPEND"
        return True
    except (AttributeError, OSError, RuntimeError, TypeError):
        # Local library registration is a convenience. Never report the exact,
        # already-imported asset as failed because preferences are read-only.
        return False


def _datablock_snapshot() -> set[int]:
    pointers: set[int] = set()
    for property_definition in bpy.data.bl_rna.properties:
        if property_definition.identifier == "rna_type" or property_definition.type != "COLLECTION":
            continue
        try:
            values = getattr(bpy.data, property_definition.identifier)
            iterator = iter(values)
        except (AttributeError, TypeError):
            continue
        for datablock in iterator:
            try:
                pointers.add(datablock.as_pointer())
            except (AttributeError, ReferenceError):
                continue
    return pointers


def _remove_new_datablocks(before: set[int]) -> None:
    new_datablocks: list[Any] = []
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
            try:
                pointer = datablock.as_pointer()
            except (AttributeError, ReferenceError):
                continue
            if pointer not in before and pointer not in seen:
                seen.add(pointer)
                new_datablocks.append(datablock)
    if not new_datablocks:
        return
    try:
        bpy.data.batch_remove(new_datablocks)
    except (ReferenceError, RuntimeError, TypeError):
        # Best-effort fallback for an unusual dependency cycle. The transaction
        # snapshot remains preferable because it removes meshes, materials,
        # images, and other appended dependencies, not only the root object.
        for datablock in reversed(new_datablocks):
            try:
                collection = getattr(bpy.data, datablock.bl_rna.identifier.lower() + "s", None)
                if collection is not None:
                    collection.remove(datablock)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass


def _import_object(
    context: bpy.types.Context,
    prepared: PreparedAsset,
) -> bpy.types.Object:
    identity = prepared.grant.asset
    name = identity.name
    before = _datablock_snapshot()

    try:
        with bpy.data.libraries.load(
            str(prepared.cache.path),
            link=False,
            assets_only=True,
        ) as (data_from, data_to):
            matches = [candidate for candidate in data_from.objects if candidate == name]
            if len(matches) != 1:
                if not matches:
                    raise ImportAssetError(
                        "The verified artifact does not contain the exact purchased object asset"
                    )
                raise ImportAssetError(
                    "The verified artifact contains duplicate purchased object identities"
                )
            data_to.objects = [name]

        loaded = [obj for obj in data_to.objects if obj is not None]
        if len(loaded) != 1:
            raise ImportAssetError("Blender did not append the exact purchased object")
        loaded_object = loaded[0]
        if loaded_object.asset_data is None:
            raise ImportAssetError("The purchased object is not marked as a Blender asset")
        immutable_marker = loaded_object.get(IMMUTABLE_ASSET_ID_PROPERTY)
        if not isinstance(immutable_marker, str):
            raise ImportAssetError(
                "The purchased object is missing its immutable Sulu Market identity"
            )
        if immutable_marker != identity.immutable_id:
            raise ImportAssetError(
                "The purchased object identity does not match the redeemed entitlement"
            )

        destination = context.collection or context.scene.collection
        if loaded_object.name not in destination.objects:
            destination.objects.link(loaded_object)
        loaded_object.matrix_world.translation = context.scene.cursor.location
        loaded_object.select_set(True)
        context.view_layer.objects.active = loaded_object
        return loaded_object
    except ImportAssetError:
        _remove_new_datablocks(before)
        raise
    except (OSError, RuntimeError, TypeError) as exc:
        _remove_new_datablocks(before)
        raise ImportAssetError("Blender could not append the purchased object asset") from exc


def import_prepared_asset(
    context: bpy.types.Context,
    prepared: PreparedAsset,
) -> Any:
    identity = prepared.grant.asset
    if identity.import_method != "APPEND":
        raise ImportAssetError(
            f"Import method {identity.import_method} is not supported by this bridge version"
        )

    importers = {
        "OBJECT": _import_object,
    }
    importer = importers.get(identity.id_type)
    if importer is None:
        supported = ", ".join(sorted(importers))
        raise ImportAssetError(
            f"Asset ID type {identity.id_type} is not supported yet; supported types: {supported}"
        )
    imported = importer(context, prepared)
    _register_local_asset_library(context, prepared.cache.path.parents[2])
    return imported


class SULU_MARKET_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_MODULE

    api_origin: StringProperty(
        name="Sulu API Origin",
        description="Exact approved origin used to redeem Sulu Market asset tickets",
        default=DEFAULT_API_ORIGIN,
    )
    allow_insecure_localhost: BoolProperty(
        name="Allow insecure localhost development",
        description="Allow plain HTTP only for localhost or a loopback IP during explicit local testing",
        default=False,
    )
    timeout_seconds: IntProperty(
        name="Network timeout",
        description="Maximum seconds for each Market request",
        default=30,
        min=5,
        max=300,
    )
    max_download_mib: IntProperty(
        name="Maximum asset size (MiB)",
        description="Hard upper bound accepted from signed artifact metadata",
        default=4096,
        min=1,
        max=4096,
    )

    def draw(self, context: bpy.types.Context) -> None:
        del context
        layout = self.layout
        layout.prop(self, "api_origin")
        layout.prop(self, "timeout_seconds")
        layout.prop(self, "max_download_mib")
        layout.separator()
        layout.prop(self, "allow_insecure_localhost")
        if self.allow_insecure_localhost:
            warning = layout.box()
            warning.label(
                text="Development only: plain HTTP is limited to loopback hosts", icon="ERROR"
            )


class SULU_MARKET_OT_import_asset(bpy.types.Operator):
    bl_idname = "sulu_market.import_asset"
    bl_label = "Import Sulu Market Asset"
    bl_description = "Redeem a one-use Sulu Market descriptor and import its exact Blender asset"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.suluasset", options={"HIDDEN"})

    _job: ModalPreparationWorker[PreparedAsset] | None = None
    _timer: Any = None
    _cancel_requested: bool = False

    def _settings(self, context: bpy.types.Context) -> dict[str, Any]:
        prefs = _preferences(context)
        origin = normalize_api_origin(
            prefs.api_origin,
            allow_insecure_localhost=prefs.allow_insecure_localhost,
        )
        if not bpy.app.online_access and not (
            prefs.allow_insecure_localhost and origin.startswith("http://")
        ):
            raise ImportAssetError(
                "Blender online access is disabled; enable Online Access before redeeming Market assets"
            )
        version = ".".join(str(value) for value in bpy.app.version)
        return {
            "descriptor_path": self.filepath,
            "cache_root": _cache_root(),
            "configured_origin": origin,
            "allow_insecure_localhost": prefs.allow_insecure_localhost,
            "timeout_seconds": float(prefs.timeout_seconds),
            "max_artifact_bytes": int(prefs.max_download_mib) * 1024 * 1024,
            "blender_version": version,
        }

    @staticmethod
    def _prepare(
        settings: dict[str, Any],
        cancellation: CancellationToken,
    ) -> PreparedAsset:
        # Pure Python only: safe to execute in a worker thread. Never touch bpy here.
        return redeem_descriptor(**settings, cancellation=cancellation)

    def _finish_import(self, context: bpy.types.Context, prepared: PreparedAsset) -> set[str]:
        import_prepared_asset(context, prepared)
        reused = " from cache" if prepared.cache.reused else ""
        self.report(
            {"INFO"},
            f"Imported {prepared.grant.asset.name}{reused} from Sulu Market",
        )
        return {"FINISHED"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        return self._start_modal_worker(context)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        del event
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self._start_modal_worker(context)

    def _start_modal_worker(self, context: bpy.types.Context) -> set[str]:
        """Start the one guarded pure worker from execute or invoke-with-filepath."""

        global _ACTIVE_IMPORT_OPERATOR

        if _ACTIVE_IMPORT_OPERATOR is self and self._job is not None:
            return {"RUNNING_MODAL"}
        if _ACTIVE_IMPORT_OPERATOR is not None:
            self.report({"WARNING"}, "A Sulu Market asset import is already in progress")
            return {"CANCELLED"}

        try:
            settings = self._settings(context)
        except BridgeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception:
            self.report({"ERROR"}, "Unexpected error while preparing the Sulu Market asset")
            return {"CANCELLED"}

        job = ModalPreparationWorker(settings, self._prepare)
        self._job = job
        self._cancel_requested = False
        _ACTIVE_IMPORT_OPERATOR = self
        try:
            if not job.start():
                raise RuntimeError("Sulu Market asset worker was already started")
            self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
            context.window_manager.modal_handler_add(self)
        except Exception:
            self._release_runtime(context, cancel=True)
            self.report({"ERROR"}, "Unexpected error while preparing the Sulu Market asset")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if event.type == "ESC":
            self._cancel_requested = True
            if self._job is not None:
                self._job.cancel()
        if event.type != "TIMER" or (self._job is not None and self._job.is_alive()):
            return {"RUNNING_MODAL"}

        job = self._job
        outcome = job.outcome if job is not None else None
        cancellation_requested = self._cancel_requested
        self._release_runtime(context)
        if cancellation_requested:
            self.report({"WARNING"}, "Sulu Market asset import cancelled")
            return {"CANCELLED"}
        worker_error = outcome.error if outcome is not None else None
        if worker_error is not None:
            if isinstance(worker_error, BridgeError):
                self.report({"ERROR"}, str(worker_error))
            else:
                self.report({"ERROR"}, "Unexpected error while preparing the Sulu Market asset")
            return {"CANCELLED"}
        prepared = outcome.result if outcome is not None else None
        if not isinstance(prepared, PreparedAsset):
            self.report({"ERROR"}, "Sulu Market asset preparation did not complete")
            return {"CANCELLED"}
        try:
            return self._finish_import(context, prepared)
        except BridgeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception:
            self.report({"ERROR"}, "Unexpected error while importing the Sulu Market asset")
            return {"CANCELLED"}

    def _clear_timer(self, context: bpy.types.Context) -> None:
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (ReferenceError, RuntimeError):
                pass
            self._timer = None

    def _release_runtime(self, context: bpy.types.Context, *, cancel: bool = False) -> None:
        global _ACTIVE_IMPORT_OPERATOR

        job = self._job
        if cancel and job is not None:
            job.cancel()
        self._clear_timer(context)
        self._job = None
        self._cancel_requested = False
        if _ACTIVE_IMPORT_OPERATOR is self:
            _ACTIVE_IMPORT_OPERATOR = None

    def cancel(self, context: bpy.types.Context) -> None:
        self._release_runtime(context, cancel=True)


class SULU_MARKET_FH_asset(bpy.types.FileHandler):
    bl_idname = "SULU_MARKET_FH_asset"
    bl_label = "Sulu Market Asset"
    bl_import_operator = SULU_MARKET_OT_import_asset.bl_idname
    bl_file_extensions = ".suluasset"

    @classmethod
    def poll_drop(cls, context: bpy.types.Context) -> bool:
        area = context.area
        if area is None:
            return False
        if area.type == "VIEW_3D":
            return True
        if area.type != "FILE_BROWSER":
            return False
        space = area.spaces.active
        return getattr(space, "browse_mode", "") == "ASSETS"


def _menu_import(self: bpy.types.Menu, context: bpy.types.Context) -> None:
    del context
    self.layout.operator(
        SULU_MARKET_OT_import_asset.bl_idname,
        text="Sulu Market Asset (.suluasset)",
    )


_CLASSES = (
    SULU_MARKET_Preferences,
    SULU_MARKET_OT_import_asset,
    SULU_MARKET_FH_asset,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)


def unregister() -> None:
    global _ACTIVE_IMPORT_OPERATOR

    active = _ACTIVE_IMPORT_OPERATOR
    if active is not None:
        try:
            active.cancel(bpy.context)
        except (ReferenceError, RuntimeError):
            if active._job is not None:
                active._job.cancel()
            _ACTIVE_IMPORT_OPERATOR = None
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
