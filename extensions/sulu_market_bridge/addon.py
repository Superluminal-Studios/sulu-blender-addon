# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender registration and exact asset import integration."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from .sulu_bridge import (
    DEFAULT_API_ORIGIN,
    BridgeError,
    ImportAssetError,
    PreparedAsset,
    normalize_api_origin,
    redeem_descriptor,
)

ADDON_MODULE = __package__
CACHE_LIBRARY_NAME = "Sulu Market Redeemed Assets"
IMMUTABLE_ASSET_ID_PROPERTY = "sulu_market_asset_id"


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
    return Path(path).resolve()


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


def _remove_loaded_object(obj: bpy.types.Object | None) -> None:
    if obj is None:
        return
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except (ReferenceError, RuntimeError):
        pass


def _import_object(
    context: bpy.types.Context,
    prepared: PreparedAsset,
) -> bpy.types.Object:
    identity = prepared.grant.asset
    name = identity.name
    loaded_object: bpy.types.Object | None = None

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
        _remove_loaded_object(loaded_object)
        raise
    except (OSError, RuntimeError, TypeError) as exc:
        _remove_loaded_object(loaded_object)
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
        default=2048,
        min=1,
        max=16384,
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

    _worker: threading.Thread | None = None
    _timer: Any = None
    _worker_state: dict[str, Any] | None = None
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
    def _prepare(settings: dict[str, Any]) -> PreparedAsset:
        # Pure Python only: safe to execute in a worker thread. Never touch bpy here.
        return redeem_descriptor(**settings)

    def _finish_import(self, context: bpy.types.Context, prepared: PreparedAsset) -> set[str]:
        import_prepared_asset(context, prepared)
        reused = " from cache" if prepared.cache.reused else ""
        self.report(
            {"INFO"},
            f"Imported {prepared.grant.asset.name}{reused} from Sulu Market",
        )
        return {"FINISHED"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            prepared = self._prepare(self._settings(context))
            return self._finish_import(context, prepared)
        except BridgeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception:
            self.report({"ERROR"}, "Unexpected error while importing the Sulu Market asset")
            return {"CANCELLED"}

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        del event
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        try:
            settings = self._settings(context)
        except BridgeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception:
            self.report({"ERROR"}, "Unexpected error while preparing the Sulu Market asset")
            return {"CANCELLED"}

        # The worker owns only this ordinary Python dictionary. It never reads
        # or writes the bpy Operator instance (or any other Blender RNA value).
        state: dict[str, Any] = {"prepared": None, "error": None}
        self._worker_state = state
        self._cancel_requested = False

        def run() -> None:
            try:
                state["prepared"] = redeem_descriptor(**settings)
            except BaseException as exc:  # Store only; Blender API reporting stays on main thread.
                state["error"] = exc

        self._worker = threading.Thread(target=run, name="SuluMarketAssetDownload", daemon=True)
        self._worker.start()
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if event.type == "ESC":
            self._cancel_requested = True
        if event.type != "TIMER" or (self._worker is not None and self._worker.is_alive()):
            return {"RUNNING_MODAL"}

        self._clear_timer(context)
        if self._cancel_requested:
            self._worker_state = None
            self.report({"WARNING"}, "Sulu Market asset import cancelled")
            return {"CANCELLED"}
        state = self._worker_state or {}
        worker_error = state.get("error")
        if worker_error is not None:
            self._worker_state = None
            if isinstance(worker_error, BridgeError):
                self.report({"ERROR"}, str(worker_error))
            else:
                self.report({"ERROR"}, "Unexpected error while preparing the Sulu Market asset")
            return {"CANCELLED"}
        prepared = state.get("prepared")
        if not isinstance(prepared, PreparedAsset):
            self._worker_state = None
            self.report({"ERROR"}, "Sulu Market asset preparation did not complete")
            return {"CANCELLED"}
        self._worker_state = None
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
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def cancel(self, context: bpy.types.Context) -> None:
        self._cancel_requested = True
        self._clear_timer(context)


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
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
