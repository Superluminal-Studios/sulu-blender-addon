# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2018, Blender Foundation - Sybren A. Stüvel
"""ZIP file packer.

Note: There is no official file name encoding for ZIP files. Expect trouble
when you want to use the ZIP cross-platform and you have non-ASCII names.
"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import sys
import time
import gzip
from typing import Iterable, List, Tuple


try:
    import zstandard as zstd
except Exception:  # pragma: no cover
    zstd = None  # type: ignore[assignment]

from . import Packer, transfer

log = logging.getLogger(__name__)


_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_GZIP_MAGIC = b"\x1f\x8b"

def shorten_path(path: str) -> str:
    """
    Return a version of `path` no longer than 64 characters,
    inserting “...” in the middle if it’s longer. Preserves both ends.
    """
    max_len = 64
    dots = "..."
    path = str(path)
    if len(path) <= max_len:
        return path
    keep = max_len - len(dots)
    left = keep // 2
    right = keep - left
    return f"{path[:left]}{dots}{path[-right:]}"


def _env_int(name: str, default: int) -> int:
    try:
        v = os.environ.get(name, "").strip()
        return int(v) if v else int(default)
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name, "").strip()
        return float(v) if v else float(default)
    except Exception:
        return float(default)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return bool(default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _human_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "?"
    if n < 1024:
        return f"{n} B"
    x = float(n)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        x /= 1024.0
        if x < 1024.0 or unit == "TiB":
            return f"{x:.1f} {unit}"
    return f"{x:.1f} TiB"


def _emit(msg: str) -> None:
    """Emit a normal (newline) message visible to users even if logging isn't configured."""
    try:
        log.info(msg)
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except Exception:
        pass


# -------------------------------------------------------------------
#  ZIP Speed Tunables (no new deps)
# -------------------------------------------------------------------
#
# You can override these via environment variables if you want without shipping UI:
#   SULU_ZIP_COMPRESSLEVEL=1..9   (default 1 = fast, 9 = small)
#   SULU_ZIP_IO_BUFSIZE=bytes     (default 1 MiB)
#   SULU_ZIP_STORE_BIG_FILES_MB   (default 256; 0 disables big-file store rule)
#   SULU_ZIP_VERBOSE=1            (prints per-file lines; slower)
#   SULU_ZIP_NO_COMPRESS=1        (store everything; fastest; biggest zip)
#   SULU_ZIP_PRINT_INTERVAL=secs  (default 0.2)
#
ZIP_COMPRESSLEVEL = max(0, min(_env_int("SULU_ZIP_COMPRESSLEVEL", 1), 9))
ZIP_IO_BUFSIZE = max(64 * 1024, _env_int("SULU_ZIP_IO_BUFSIZE", 1024 * 1024))
ZIP_VERBOSE = _env_bool("SULU_ZIP_VERBOSE", False)
ZIP_NO_COMPRESS = _env_bool("SULU_ZIP_NO_COMPRESS", False)
ZIP_PRINT_INTERVAL = max(0.05, _env_float("SULU_ZIP_PRINT_INTERVAL", 0.2))

_store_big_mb = _env_int("SULU_ZIP_STORE_BIG_FILES_MB", 256)
ZIP_STORE_BIG_FILES_BYTES = 0 if _store_big_mb <= 0 else int(_store_big_mb) * 1024 * 1024

# Formats that are typically already compressed / incompressible.
# Storing these avoids wasting CPU on deflate for little/no benefit.
STORE_ONLY = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".exr",
    ".mp4", ".mov", ".mkv", ".avi",
    ".mp3", ".ogg", ".flac",
    ".zip", ".rar", ".7z", ".gz", ".bz2", ".xz",
    ".ktx2", ".dds",
    ".blend"
}

COMPRESSION_LEVELS = {
    0: "Store",
    1: "Fast Compression",
    2: "Fast Compression",
    3: "Normal Compression",
    4: "Normal Compression",
    5: "Balanced Compression",
    6: "High Compression",
    7: "High Compression",
    8: "High Compression",
    9: "Maximum Compression",
}

COMPRESS_ICONS = {
    0: "✅",
    1: "📦",
    2: "📦",
    3: "📦",
    4: "📦",
    5: "📦",
    6: "📦",
    7: "📦",
    8: "📦",
    9: "📦",
}


class ZipPacker(Packer):
    """Creates a zipped BAT Pack instead of a directory."""

    def __init__(
        self,
        bfile: pathlib.Path,
        project: pathlib.Path,
        target,
        *,
        noop: bool = False,
        compress: bool = False,
        relative_only: bool = False,
        rewrite_blendfiles: bool = False,
        quiet: bool = False,
    ):
        super().__init__(
            bfile, project, target,
            noop=noop,
            compress=compress,
            relative_only=relative_only,
            rewrite_blendfiles=rewrite_blendfiles,
        )
        self._quiet = quiet  # Suppress console output when TUI is handling display

    def _create_file_transferer(self) -> transfer.FileTransferer:
        target_path = pathlib.Path(self._target_path)
        return ZipTransferrer(target_path.absolute(), quiet=self._quiet)


class ZipTransferrer(transfer.FileTransferer):
    """Creates a ZIP file instead of writing to a directory.

    UX + performance patch (Superluminal):
    - Much faster defaults:
        • compresslevel=1 for deflated entries
        • store-only for already-compressed formats (png/jpg/exr/video/archives/etc.)
        • optionally store big files above a threshold
        • larger IO buffer into zip stream
    - Clear progress like your other steps:
        📦  Creating zip...
        📦  Zipping [12/340] 1.2 GiB / 8.4 GiB (14.3%) — texture_1001.png
        ✅  Zip complete ...
    - Optional verbose per-file output via SULU_ZIP_VERBOSE=1.
    """

    def __init__(self, zippath: pathlib.Path, quiet: bool = False) -> None:
        super().__init__()
        self.zippath = zippath
        self.quiet = quiet  # Suppress console output when TUI is handling display

    def _choose_compress_type(self, suffix: str, size: int, zipfile_mod) -> int:
        # If user wants maximum speed: store everything.
        if ZIP_NO_COMPRESS:
            return zipfile_mod.ZIP_STORED

        s = (suffix or "").lower()

        # Known already-compressed formats => store.
        if s in STORE_ONLY:
            return zipfile_mod.ZIP_STORED

        # Very large files are often caches and frequently incompressible; avoid burning CPU.
        if ZIP_STORE_BIG_FILES_BYTES and size >= ZIP_STORE_BIG_FILES_BYTES:
            return zipfile_mod.ZIP_STORED

        return zipfile_mod.ZIP_DEFLATED

    def run(self) -> None:
        import zipfile

        zippath = self.zippath.absolute()

        # Collect all queued items first so we can compute totals + give real progress %.
        # (Queueing is quick; compression dominates runtime.)
        items: List[Tuple[pathlib.Path, pathlib.PurePath, transfer.Action]] = []
        try:
            for src, dst, act in self.iter_queue():
                items.append((src, dst, act))
        except Exception:
            log.exception("ZIP queue iteration failed")
            if not self.quiet:
                _emit("❌  ZIP: failed to read queued files.")
            return

        total_files = len(items)

        # Compute total bytes (best effort; missing files count as 0 here)
        total_bytes = 0
        for src, _, _ in items:
            try:
                if src.is_file():
                    total_bytes += src.stat().st_size
            except Exception:
                pass

        # Make sure the parent folder exists.
        try:
            zippath.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Progress state
        bytes_done = 0
        t0 = time.perf_counter()
        last_print = 0.0
        last_len = 0

        def emit_inline(line: str) -> None:
            nonlocal last_len
            try:
                # pad to overwrite previous longer line
                pad = max(0, last_len - len(line))
                sys.stderr.write("\r" + line + (" " * pad))
                sys.stderr.flush()
                last_len = len(line)
            except Exception:
                # fallback: just print a line
                try:
                    print(line, flush=True)
                except Exception:
                    pass

        def finish_inline() -> None:
            try:
                sys.stderr.write("\n")
                sys.stderr.flush()
            except Exception:
                pass

        # Pick default compression (used only if ZipInfo.compress_type not set)
        # We still set per-entry compress_type via ZipInfo to handle STORE_ONLY.
        default_compression = zipfile.ZIP_STORED if ZIP_NO_COMPRESS else zipfile.ZIP_DEFLATED
        default_level = None if ZIP_NO_COMPRESS else ZIP_COMPRESSLEVEL

        if not self.quiet:
            _emit(f"ℹ️  Creating zip: {zippath}")
            _emit(
                f"ℹ️  ZIP settings: "
                f"{'store-only' if ZIP_NO_COMPRESS else f'deflate level {ZIP_COMPRESSLEVEL}'}; "
                f"io_buf={_human_bytes(ZIP_IO_BUFSIZE)}; "
                f"store_big_files={'off' if ZIP_STORE_BIG_FILES_BYTES == 0 else f'>{_store_big_mb}MB'}; "
                f"verbose={'on' if ZIP_VERBOSE else 'off'}"
            )
            if total_files:
                _emit(f"ℹ️  Files queued: {total_files}  (size est.: {_human_bytes(total_bytes)})\n")

        try:
            with zipfile.ZipFile(
                str(zippath),
                mode="w",
                compression=default_compression,
                compresslevel=default_level,
                allowZip64=True,
            ) as outzip:
                #print('\x1b[?7l')
                for idx, (src, dst, act) in enumerate(items, start=1):
                    
                    # Compute archive name (must be POSIX separators)
                    dst_abs = pathlib.Path(dst).absolute()
                    relpath = dst_abs.relative_to(zippath)
                    arcname = str(relpath).replace("\\", "/")

                    # Stat once
                    try:
                        st = src.stat()
                        size = int(st.st_size) if src.is_file() else 0
                        mtime = st.st_mtime
                        mode = st.st_mode
                    except Exception:
                        size = 0
                        mtime = time.time()
                        mode = 0

                    # Decide compression type
                    compress_type = self._choose_compress_type(src.suffix, size, zipfile)
                    comp_label = "stored" if compress_type == zipfile.ZIP_STORED else "deflated"

                    # Optional verbose per-file logging (slower)
                    if ZIP_VERBOSE and not self.quiet:
                        if total_files > 0:
                            _emit(f"ℹ️  [{idx}/{total_files}] Zipping {src} ({_human_bytes(size)}) [{comp_label}]")
                        else:
                            _emit(f"ℹ️  [{idx}] Zipping {src} ({_human_bytes(size)}) [{comp_label}]")

                    try:
                        # Handle directories (rare in your pack flow, but safe)
                        if src.is_dir():
                            if not arcname.endswith("/"):
                                arcname += "/"
                            zi = zipfile.ZipInfo(arcname)
                            zi.compress_type = zipfile.ZIP_STORED
                            outzip.writestr(zi, b"")
                        else:
                            zi = zipfile.ZipInfo(arcname)

                            # Preserve timestamps (local time tuple)
                            try:
                                zi.date_time = time.localtime(mtime)[:6]
                            except Exception:
                                zi.date_time = time.localtime(time.time())[:6]

                            # Preserve unix permissions best-effort
                            try:
                                zi.external_attr = (mode & 0xFFFF) << 16
                            except Exception:
                                pass

                            # For .blend we potentially apply our own Zstd layer.
                            # Keep the ZIP entry stored to avoid double-compressing.
                            if arcname.endswith(".blend"):
                                zi.compress_type = zipfile.ZIP_STORED
                            else:
                                zi.compress_type = compress_type

                            # Write file data with a large buffer (faster)
                            with open(src, "rb") as fp:
                                with outzip.open(zi, mode="w", force_zip64=True) as zf:
                                    if arcname.endswith(".blend"):
                                        head = b""
                                        try:
                                            head = fp.read(4)
                                            fp.seek(0)
                                        except Exception:
                                            head = b""

                                        # If Zstandard isn't available in this Python environment,
                                        # preserve the file bytes (still Blender-openable for gzip/plain).
                                        if zstd is None:
                                            shutil.copyfileobj(fp, zf, length=ZIP_IO_BUFSIZE)
                                            if ZIP_VERBOSE and not self.quiet:
                                                _emit(f"{str(idx).zfill(len(str(total_files)))}/{total_files} ⚠️  Zstd not available; stored .blend as-is: {shorten_path(arcname)}")
                                            continue

                                        # If the source .blend is already Zstd-compressed, keep it as-is.
                                        if head == _ZSTD_MAGIC:
                                            if not self.quiet:
                                                _emit(f"{str(idx).zfill(len(str(total_files)))}/{total_files}✅  Store: {shorten_path(arcname)}")
                                            shutil.copyfileobj(fp, zf, length=ZIP_IO_BUFSIZE)

                                        else:
                                            if not self.quiet:
                                                _emit(f"{str(idx).zfill(len(str(total_files)))}/{total_files}📦  Zstd: {shorten_path(arcname)}")
                                            zstd_compressor = zstd.ZstdCompressor(level=1)
                                            zstd_compressor.copy_stream(fp, zf, read_size=ZIP_IO_BUFSIZE)
                                    else:
                                        if not self.quiet:
                                            _emit(f"{str(idx).zfill(len(str(total_files)))}/{total_files}{COMPRESS_ICONS.get(compress_type, '')} {COMPRESSION_LEVELS.get(compress_type, compress_type)}: {shorten_path(arcname)}")
                                        shutil.copyfileobj(fp, zf, length=ZIP_IO_BUFSIZE)

                        # Delete source if MOVE
                        if act == transfer.Action.MOVE:
                            self.delete_file(src)

                        bytes_done += max(size, 0)

                        # Throttled inline progress update (fast, non-spammy)
                        now = time.perf_counter()
                        # if (now - last_print) >= ZIP_PRINT_INTERVAL or idx == total_files:
                        #     last_print = now

                        #     if total_files > 0:
                        #         prefix = f"📦  Zipping [{idx}/{total_files}]"
                        #     else:
                        #         prefix = f"📦  Zipping [{idx}]"

                        #     if total_bytes > 0:
                        #         pct = (bytes_done / max(total_bytes, 1)) * 100.0
                        #         line = (
                        #             f"{prefix} "
                        #             f"{_human_bytes(bytes_done)} / {_human_bytes(total_bytes)} "
                        #             f"({pct:5.1f}%) — {src.name}"
                        #         )
                        #     else:
                        #         line = f"{prefix} {_human_bytes(bytes_done)} — {src.name}"

                        #     emit_inline(line)

                    except Exception:
                        # Make sure the inline line doesn't hide the traceback / message
                        finish_inline()

                        log.exception("Error transferring %s to %s", src, dst_abs)
                        if not self.quiet:
                            _emit(f"❌  ZIP error while processing: {src}")

                        # Requeue this item and all remaining so the main thread can diagnose.
                        try:
                            # Put current + remaining back into the queue
                            for rem in items[idx - 1:]:
                                self.queue.put(rem)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        return

            finish_inline()
            elapsed = time.perf_counter() - t0
            if not self.quiet:
                _emit(
                    f"✅  Zip complete: {zippath} "
                    f"({total_files} file{'s' if total_files != 1 else ''}, {_human_bytes(bytes_done)}, {elapsed:.1f}s)"
                )

        except Exception:
            # Make sure progress line is finalized before emitting error
            finish_inline()
            log.exception("ZIP creation failed")
            if not self.quiet:
                _emit("❌  Zip creation failed. See logs above for details.")
            return
