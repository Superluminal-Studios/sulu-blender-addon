"""Exercise Blender 5.2's stock remote listing sync and lazy asset downloader."""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--relative-path", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--preview-relative-path", required=True)
    parser.add_argument("--preview-hash", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--immutable-id", required=True)
    values = __import__("sys").argv
    return parser.parse_args(values[values.index("--") + 1 :] if "--" in values else [])


def pump(callback, finished, *, timeout: float = 30) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while not finished():
        if time.monotonic() >= deadline:
            raise RuntimeError("stock Blender asset downloader timed out")
        callback()
        time.sleep(0.01)


def main() -> None:
    # Keep Blender-only imports and all side effects behind the main guard.
    # Blender's stock HTTP downloader uses multiprocessing with ``spawn`` on
    # macOS, which re-imports this file in a plain Python child process.
    import bpy
    from _bpy_internal.assets.remote_library import asset_downloader, listing_downloader

    options = arguments()
    origin = options.origin.rstrip("/") + "/"
    result = bpy.ops.preferences.asset_library_add(
        type="REMOTE",
        name="Sulu Native Online E2E",
        remote_url=origin,
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"stock Blender could not add the remote asset library: {result}")
    library = bpy.context.preferences.filepaths.asset_libraries[-1]
    library.enabled = True
    library.import_method = "APPEND"
    if library.remote_url != origin or not library.use_remote_url:
        raise RuntimeError("stock Blender did not classify the library as remote")
    cache = Path(library.path)
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)

    listing = listing_downloader.RemoteAssetListingDownloader(
        origin,
        cache,
        on_update_callback=lambda _downloader: None,
        on_done_callback=lambda _downloader: None,
    )
    listing.download_and_process()
    pump(
        listing.on_timer_event,
        lambda: listing.status != listing_downloader.DownloadStatus.LOADING,
    )
    if listing.status != listing_downloader.DownloadStatus.FINISHED_SUCCESSFULLY:
        raise RuntimeError(f"stock Blender listing sync failed: {listing.error_message}")
    if not (cache / "_asset-library-meta.json").is_file():
        raise RuntimeError("stock Blender did not persist the remote library metadata")
    if not (cache / "_v1" / "asset-index.processed.json").is_file():
        raise RuntimeError("stock Blender did not persist its processed asset index")

    local_preview = Path("downloaded-previews") / "selected.webp"
    asset_downloader.download_preview(
        origin,
        cache,
        options.preview_relative_path,
        options.preview_hash,
        local_preview,
    )
    preview_downloader = asset_downloader._preview_downloaders[origin]  # noqa: SLF001
    pump(
        preview_downloader.on_timer_event,
        lambda: preview_downloader.status
        not in {
            asset_downloader.DownloadStatus.IDLE,
            asset_downloader.DownloadStatus.DOWNLOADING,
        },
    )
    if preview_downloader.status != asset_downloader.DownloadStatus.FINISHED:
        raise RuntimeError("stock Blender preview download failed")
    preview_hash = options.preview_hash.removeprefix("SHA256:")
    if hashlib.sha256((cache / local_preview).read_bytes()).hexdigest() != preview_hash:
        raise RuntimeError("stock Blender preview download failed SHA-256 verification")

    asset_downloader.download_asset_file(
        origin,
        cache,
        "",
        f"SHA256:{options.sha256}",
        Path(options.relative_path),
    )
    asset_file_downloader = asset_downloader._asset_downloaders[origin]  # noqa: SLF001
    pump(
        asset_file_downloader.on_timer_event,
        lambda: asset_file_downloader.status
        not in {
            asset_downloader.DownloadStatus.IDLE,
            asset_downloader.DownloadStatus.DOWNLOADING,
        },
    )
    if asset_file_downloader.status != asset_downloader.DownloadStatus.FINISHED:
        raise RuntimeError("stock Blender lazy asset download failed")

    downloaded = cache / options.relative_path
    payload = downloaded.read_bytes()
    if hashlib.sha256(payload).hexdigest() != options.sha256:
        raise RuntimeError("stock Blender lazy download failed SHA-256 verification")
    with bpy.data.libraries.load(str(downloaded), link=False, assets_only=True) as (
        data_from,
        data_to,
    ):
        if data_from.objects != [options.name]:
            raise RuntimeError("stock Blender listing artifact contains the wrong object set")
        data_to.objects = [options.name]
    loaded = [item for item in data_to.objects if item is not None]
    if len(loaded) != 1 or loaded[0].get("sulu_market_asset_id") != options.immutable_id:
        raise RuntimeError("stock Blender lazy-downloaded asset has the wrong immutable identity")

    print(
        "SULU_NATIVE_ONLINE_ASSET_E2E_OK "
        f"path={options.relative_path} sha256={options.sha256} "
        f"preview={options.preview_relative_path} object={options.name}"
    )


if __name__ == "__main__":
    main()
