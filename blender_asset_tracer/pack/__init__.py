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

from __future__ import annotations

import collections
import enum
import functools
import logging
import os
import pathlib
import re
import sys
import tempfile
import threading
import typing
import unicodedata

from .. import trace, bpathlib, blendfile
from ..trace import file_sequence, result

from . import filesystem, transfer, progress

log = logging.getLogger(__name__)


class PathAction(enum.Enum):
    KEEP_PATH = 1
    FIND_NEW_LOCATION = 2


class AssetAction:
    """All the info required to rewrite blend files and copy assets."""

    def __init__(self) -> None:
        self.path_action = PathAction.KEEP_PATH
        self.usages = []  # type: typing.List[result.BlockUsage]
        """BlockUsage objects referring to this asset.

        Those BlockUsage objects could refer to data blocks in this blend file
        (if the asset is a blend file) or in another blend file.
        """

        self.new_path = None  # type: typing.Optional[pathlib.PurePath]
        """Absolute path to the asset in the BAT Pack.

        This path may not exist on the local file system at all, for example
        when uploading files to remote S3-compatible storage.
        """

        self.read_from = None  # type: typing.Optional[pathlib.Path]
        """Optional path from which to read the asset.

        This is used when blend files have been rewritten. It is assumed that
        when this property is set, the file can be moved instead of copied.
        """

        self.rewrites = []  # type: typing.List[result.BlockUsage]
        """BlockUsage objects in this asset that may require rewriting.

        Empty list if this AssetAction is not for a blend file.
        """

        # NEW: extra source files that should be packed next to this asset.
        # Used for UDIM tiles and other “multi-file for one logical asset” situations.
        self.extra_files = set()  # type: typing.Set[pathlib.Path]


class Aborted(RuntimeError):
    """Raised by Packer to abort the packing process.

    See the Packer.abort() function.
    """


_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]+")
_UDIM_TOKEN_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_UDIM_MARKER = "<UDIM>"


def _nfc(s: str) -> str:
    """Normalize unicode strings to NFC for cross-platform stability."""
    return unicodedata.normalize("NFC", str(s))


def _nfc_path(p: pathlib.PurePath) -> pathlib.PurePath:
    """Return a path object of the same class but with NFC-normalized string form."""
    cls = type(p)
    return cls(_nfc(str(p)))


def _outside_project_relpath(path: pathlib.Path) -> pathlib.PurePosixPath:
    """Stable, collision-safe path for assets outside project root.

    - POSIX: /Users/a/file -> Users/a/file
    - Windows drive: C:\\Users\\a\\file -> C/Users/a/file
    - Windows UNC: \\\\server\\share\\dir\\file -> UNC/server/share/dir/file

    Also supports "fake" Windows-looking strings on POSIX for testing:
      - "C:/Users/..." or "//server/share/..."
    """
    raw = str(path).replace("\\", "/")

    # UNC-ish path (//server/share/...)
    if raw.startswith("//"):
        rest = raw.lstrip("/")
        parts = [p for p in rest.split("/") if p]
        parts = ["UNC"] + parts
        parts = [_nfc(p) for p in parts if p]
        return pathlib.PurePosixPath(*parts)

    # Windows drive-ish path (C:/...)
    if _WIN_DRIVE_RE.match(raw):
        drive = raw[0].upper()
        rest = raw[2:].lstrip("/")  # drop "C:"
        comps = [p for p in rest.split("/") if p]
        parts = [_nfc(p) for p in ([drive] + comps) if p]
        return pathlib.PurePosixPath(*parts)

    # Try to resolve (best-effort)
    p = path
    try:
        p = p.resolve()
    except Exception:
        p = path

    drv = getattr(p, "drive", "") or ""
    if drv:
        # UNC on Windows: drive like "\\server\share"
        if drv.startswith("\\\\"):
            drv_clean = drv.lstrip("\\")
            comps = [c for c in drv_clean.split("\\") if c]
            rest = list(p.parts[1:]) if len(p.parts) > 1 else []
            parts = ["UNC", *comps, *rest]
            parts = [_nfc(x) for x in parts if x and x not in (os.sep, "\\", "/")]
            return pathlib.PurePosixPath(*parts)

        # Drive letter on Windows: "C:"
        drive_letter = _nfc(drv[0].upper())
        rest = list(p.parts[1:]) if len(p.parts) > 1 else []
        rest = [_nfc(x) for x in rest if x and x not in (os.sep, "\\", "/")]
        return pathlib.PurePosixPath(drive_letter, *rest)

    # POSIX absolute
    parts = list(p.parts)
    if parts and parts[0] == os.sep:
        parts = parts[1:]
    parts = [_nfc(x) for x in parts if x]
    return pathlib.PurePosixPath(*parts)


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _looks_like_cloud_storage(p: pathlib.Path) -> bool:
    s = str(p).replace("\\", "/")
    return (
        "/Library/CloudStorage/" in s
        or "/Dropbox" in s
        or "/OneDrive" in s
        or "/iCloud" in s
        or "/Mobile Documents/" in s
    )


def _macos_permission_hint(path: pathlib.Path, err: str) -> str:
    # Keep this very actionable and non-technical.
    # We can’t know whether this is “Terminal” or “Blender” without the launcher change,
    # so we phrase it as “the app running this upload”.
    lines = [
        "macOS blocked file access.",
        "Fix:",
        "  • System Settings → Privacy & Security → Full Disk Access",
        "  • Enable the app running this upload (Terminal/iTerm if you see a console window; otherwise Blender).",
    ]
    if _looks_like_cloud_storage(path):
        lines += [
            "",
            "Cloud storage note:",
            "  • This file is in a cloud-synced folder.",
            "  • Make sure it’s downloaded / available offline, then retry.",
        ]
    lines += ["", f"Technical: {err}"]
    return "\n".join(lines)


def _udim_template_from_name(name: str) -> typing.Optional[typing.Tuple[str, int]]:
    """Return (glob_template, udim_number) based on last 4-digit token in filename."""
    matches = list(_UDIM_TOKEN_RE.finditer(name))
    if not matches:
        return None
    m = matches[-1]
    try:
        tile = int(m.group(1))
    except Exception:
        return None
    if tile < 1001:
        return None
    template = name[: m.start()] + "*" + name[m.end() :]
    return template, tile


class Packer:
    """Takes a blend file and bundle it with its dependencies.

    The process is separated into two functions:

        - strategise() finds all the dependencies and determines what to do
          with them.
        - execute() performs the actual packing operation, by rewriting blend
          files to ensure the paths to moved files are correct and
          transferring the files.

    Patch notes (Superluminal project uploads):
      - Added `rewrite_blendfiles` kwarg; when True, paths are rewritten even in noop mode.
      - Assets physically *inside* project root are packed inside project layout even if
        referenced by absolute paths.
      - Only assets truly outside project root go under `_outside_project/`.
      - `_outside_project` paths are collision-safe across drives/UNC shares.
      - Target paths are NFC-normalized.

    Diagnostics patch (UDIM + unreadable reporting):
      - Detect UDIM tiles even when BAT doesn't flag `usage.is_sequence`.
      - Track unreadable files separately from missing files.
      - Emit macOS permission hints when unreadable due to access control.
    """

    def __init__(
        self,
        bfile: pathlib.Path,
        project: pathlib.Path,
        target: typing.Union[str, pathlib.Path],
        *,
        noop: bool = False,
        compress: bool = False,
        relative_only: bool = False,
        rewrite_blendfiles: bool = False,
        pre_traced_deps: typing.Optional[typing.Iterable[result.BlockUsage]] = None,
    ) -> None:
        self.blendfile = pathlib.Path(bfile)
        self.project = pathlib.Path(project)

        # Keep the original `.target` for logs, but use `_target_path` for path ops.
        self.target = str(target)
        self._target_path = self._make_target_path(target)

        self.noop = bool(noop)
        self.compress = bool(compress)
        self.relative_only = bool(relative_only)

        # NEW: allow rewriting even when noop=True (project upload wants rewritten .blend without staging)
        self.rewrite_blendfiles = bool(rewrite_blendfiles)

        # NEW: accept pre-traced dependencies to avoid redundant trace.deps() calls
        self._pre_traced_deps = (
            list(pre_traced_deps) if pre_traced_deps is not None else None
        )

        self._aborted = threading.Event()
        self._abort_lock = threading.RLock()
        self._abort_reason = ""
        self.file_map = {}

        # Set this to a custom Callback() subclass instance before calling
        # strategise() to receive progress reports.
        self._progress_cb = progress.Callback()
        self._tscb = progress.ThreadSafeCallback(self._progress_cb)

        self._exclude_globs = set()  # type: typing.Set[str]

        self._shorten = functools.partial(shorten_path, self.project)

        # Filled by strategise()
        self._actions = collections.defaultdict(
            AssetAction
        )  # type: typing.DefaultDict[pathlib.Path, AssetAction]
        self.missing_files = set()  # type: typing.Set[pathlib.Path]

        # NEW: files that exist but can't be read/opened (permissions, cloud placeholders, etc.)
        self.unreadable_files = {}  # type: typing.Dict[pathlib.Path, str]

        self._new_location_paths = set()  # type: typing.Set[pathlib.Path]
        self._output_path = None  # type: typing.Optional[pathlib.PurePath]

        # Caches (speed + consistent reporting)
        self._readability_cache = (
            {}
        )  # type: typing.Dict[pathlib.Path, typing.Tuple[bool, str]]
        self._udim_tiles_cache = (
            {}
        )  # type: typing.Dict[typing.Tuple[pathlib.Path, str], typing.List[pathlib.Path]]

        # Filled by execute()
        self._file_transferer = None  # type: typing.Optional[transfer.FileTransferer]

        # Number of files we would copy, if not for --noop
        self._file_count = 0

        self._tmpdir = tempfile.TemporaryDirectory(prefix="bat-", suffix="-batpack")
        self._rewrite_in = pathlib.Path(self._tmpdir.name)

    def _make_target_path(
        self, target: typing.Union[str, pathlib.Path]
    ) -> pathlib.PurePath:
        """Return a Path for the given target.

        This can be the target directory itself, but can also be a non-existent
        directory if the target doesn't support direct file access. It should
        only be used to perform path operations, and never for file operations.
        """
        return pathlib.Path(target).absolute()

    def close(self) -> None:
        """Clean up any temporary files."""
        self._tscb.flush()
        self._tmpdir.cleanup()

    def __enter__(self) -> "Packer":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def output_path(self) -> pathlib.PurePath:
        """The path of the packed blend file in the target directory."""
        assert self._output_path is not None
        return self._output_path

    @property
    def progress_cb(self) -> progress.Callback:
        return self._progress_cb

    @progress_cb.setter
    def progress_cb(self, new_progress_cb: progress.Callback):
        self._tscb.flush()
        self._progress_cb = new_progress_cb
        self._tscb = progress.ThreadSafeCallback(self._progress_cb)

    def abort(self, reason: str = "") -> None:
        """Aborts the current packing process.

        Can be called from any thread. Aborts as soon as the running strategise
        or execute function gets control over the execution flow, by raising
        an Aborted exception.
        """
        with self._abort_lock:
            self._abort_reason = reason
            if self._file_transferer:
                self._file_transferer.abort()
            self._aborted.set()

    def _check_aborted(self) -> None:
        """Raises an Aborted exception when abort() was called."""
        with self._abort_lock:
            reason = self._abort_reason
            if self._file_transferer is not None and self._file_transferer.has_error:
                log.error("A transfer error occurred")
                reason = self._file_transferer.error_message()
            elif not self._aborted.is_set():
                return

            log.warning("Aborting")
            self._tscb.flush()
            self._progress_cb.pack_aborted(reason)
            raise Aborted(reason)

    def exclude(self, *globs: str):
        """Register glob-compatible patterns of files that should be ignored.

        Must be called before calling strategise().
        """
        if self._actions:
            raise RuntimeError(
                "%s.exclude() must be called before strategise()"
                % self.__class__.__qualname__
            )
        self._exclude_globs.update(globs)

    # -------------------------------------------------------------------------
    # Diagnostics helpers
    # -------------------------------------------------------------------------

    def _record_missing(self, path: pathlib.Path) -> None:
        if path in self.missing_files:
            return
        self.missing_files.add(path)
        try:
            self._progress_cb.missing_file(path)
        except Exception:
            pass

    def _record_unreadable(self, path: pathlib.Path, err: str) -> None:
        if path in self.unreadable_files:
            return
        self.unreadable_files[path] = err
        # Also report via existing callback channel.
        try:
            self._progress_cb.missing_file(path)
        except Exception:
            pass

        if _is_macos():
            log.warning(_macos_permission_hint(path, err))
        else:
            log.warning("Unreadable file: %s (%s)", path, err)

    def _check_readable(self, path: pathlib.Path) -> bool:
        """Return True if the path exists and can be opened for reading.

        Records missing/unreadable internally. Cached.

        Note: We try to open() the file directly rather than checking exists() first,
        because cloud drives (OneDrive, Google Drive, iCloud, etc.) may report
        dehydrated placeholders as non-existent until an open attempt triggers
        the cloud sync.
        """
        # Normalize to an absolute path for cache stability.
        try:
            abs_path = bpathlib.make_absolute(path)
        except Exception:
            abs_path = pathlib.Path(path)

        cached = self._readability_cache.get(abs_path)
        if cached is not None:
            ok, _ = cached
            return ok

        # Directories are "readable enough" for our purposes here; the packer
        # expands them later into files.
        try:
            if abs_path.is_dir():
                self._readability_cache[abs_path] = (True, "")
                return True
        except Exception:
            # If is_dir fails due to permissions, treat as unreadable.
            err = "cannot stat directory"
            self._readability_cache[abs_path] = (False, err)
            self._record_unreadable(abs_path, err)
            return False

        # Try to open the file directly - this can trigger cloud sync for
        # dehydrated placeholders that might fail exists() checks.
        try:
            with abs_path.open("rb") as f:
                f.read(1)
            self._readability_cache[abs_path] = (True, "")
            return True
        except FileNotFoundError:
            self._readability_cache[abs_path] = (False, "missing")
            self._record_missing(abs_path)
            return False
        except (PermissionError, OSError) as exc:
            err = f"{type(exc).__name__}: {exc}"
            self._readability_cache[abs_path] = (False, err)
            self._record_unreadable(abs_path, err)
            return False
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            self._readability_cache[abs_path] = (False, err)
            self._record_unreadable(abs_path, err)
            return False

    def _find_udim_tiles(self, asset_path: pathlib.Path) -> typing.List[pathlib.Path]:
        """Return UDIM tile files for a given path.

        Covers:
          - <UDIM> placeholder filenames
          - filenames containing a 4-digit token >= 1001 (uses the last token)

        Returns [] if this doesn't look like a UDIM tileset or no tiles exist.
        """
        name = asset_path.name

        # Case A: <UDIM> placeholder
        if _UDIM_MARKER in name:
            glob_name = name.replace(_UDIM_MARKER, "*")
            key = (asset_path.parent, glob_name)
            cached = self._udim_tiles_cache.get(key)
            if cached is not None:
                return list(cached)

            glob_path = asset_path.with_name(glob_name)
            try:
                tiles = [
                    p for p in file_sequence.expand_sequence(glob_path) if p.is_file()
                ]
            except Exception:
                tiles = []

            tiles = sorted(set(tiles))
            self._udim_tiles_cache[key] = tiles
            return list(tiles)

        # Case B: numeric token (1001+)
        tpl = _udim_template_from_name(name)
        if not tpl:
            return []
        glob_name, _tile = tpl

        key = (asset_path.parent, glob_name)
        cached = self._udim_tiles_cache.get(key)
        if cached is not None:
            return list(cached)

        tiles = []
        try:
            for cand in sorted(asset_path.parent.glob(glob_name)):
                if not cand.is_file():
                    continue
                cand_tpl = _udim_template_from_name(cand.name)
                if not cand_tpl:
                    continue
                cand_glob_name, cand_tile = cand_tpl
                if cand_glob_name != glob_name:
                    continue
                if cand_tile < 1001:
                    continue
                tiles.append(cand)
        except Exception:
            tiles = []

        tiles = sorted(set(tiles))

        # Only treat as a “tileset” if it’s clearly multi-file.
        if len(tiles) >= 2:
            self._udim_tiles_cache[key] = tiles
            return list(tiles)

        self._udim_tiles_cache[key] = []
        return []

    def strategise(self) -> None:
        """Determine what to do with the assets.

        Places an asset into one of these categories:
            - Can be copied as-is, nothing smart required.
            - Blend files referring to this asset need to be rewritten.

        This function does *not* expand globs. Globs are seen as single
        assets, and are only evaluated when performing the actual transfer
        in the execute() function.
        """
        # The blendfile that we pack is generally not its own dependency, so
        # we have to explicitly add it to the _packed_paths.
        bfile_path = bpathlib.make_absolute(self.blendfile)

        project_abs = bpathlib.make_absolute(self.project)

        # Both paths have to be resolved first, because this also translates
        # network shares mapped to Windows drive letters back to their UNC
        # notation.
        bfile_pp = self._target_path / bfile_path.relative_to(project_abs)
        bfile_pp = _nfc_path(bfile_pp)
        self._output_path = bfile_pp

        self._progress_cb.pack_start()

        act = self._actions[bfile_path]
        act.path_action = PathAction.KEEP_PATH
        act.new_path = bfile_pp

        self._check_aborted()
        self._new_location_paths = set()

        # Use pre-traced dependencies if provided (avoids redundant trace.deps() calls)
        if self._pre_traced_deps is not None:
            deps_iter = iter(self._pre_traced_deps)
            log.debug("Using %d pre-traced dependencies", len(self._pre_traced_deps))
        else:
            deps_iter = trace.deps(self.blendfile, self._progress_cb)

        for usage in deps_iter:
            self._check_aborted()
            asset_path = usage.abspath

            if any(asset_path.match(glob) for glob in self._exclude_globs):
                log.info("Excluding file: %s", asset_path)
                continue

            if self.relative_only and not usage.asset_path.startswith(b"//"):
                log.info("Skipping absolute path: %s", usage.asset_path)
                continue

            if usage.is_sequence:
                self._visit_sequence(asset_path, usage)
            else:
                self._visit_asset(asset_path, usage)

        self._find_new_paths()
        self._group_rewrites()

    def _visit_sequence(self, asset_path: pathlib.Path, usage: result.BlockUsage):
        assert usage.is_sequence

        def handle_missing_file():
            if not usage.is_optional:
                self._record_missing(asset_path)

        try:
            for file_path in file_sequence.expand_sequence(asset_path):
                if file_path.exists():
                    break
            else:
                # At least some file of a sequence must exist.
                handle_missing_file()
                return
        except file_sequence.DoesNotExist:
            # The asset path should point to something existing.
            handle_missing_file()
            return

        # Handle this sequence as an asset.
        self._visit_asset(asset_path, usage)

    def _visit_asset(self, asset_path: pathlib.Path, usage: result.BlockUsage):
        """Determine what to do with this asset.

        Determines where this asset will be packed, whether it needs rewriting,
        and records the blend file data block referring to it.
        """
        # Optional assets (e.g. linked-packed libraries) are only included if within project.
        # Skip silently if outside - their data is already embedded in the blend.
        if usage.is_optional and not self._path_in_project(asset_path):
            log.debug("Skipping optional asset outside project: %s", asset_path)
            return

        is_udim_placeholder = _UDIM_MARKER in asset_path.name
        udim_tiles = self._find_udim_tiles(asset_path) if (is_udim_placeholder) else []

        # Sequences are allowed to not exist at this point.
        if not usage.is_sequence and not asset_path.exists():
            # UDIM placeholders often do not exist as a literal file.
            # If we can find tiles on disk, treat it as present.
            if is_udim_placeholder and udim_tiles:
                log.info(
                    "UDIM placeholder %s expanded to %d tiles",
                    asset_path,
                    len(udim_tiles),
                )
            else:
                if not usage.is_optional:
                    self._record_missing(asset_path)
                return

        bfile_path = usage.block.bfile.filepath.absolute()
        self._progress_cb.trace_asset(asset_path)

        # Needing rewriting is not a per-asset thing, but a per-asset-per-
        # blendfile thing, since different blendfiles can refer to it in
        # different ways (for example with relative and absolute paths).
        if usage.is_sequence:
            first_path = next(file_sequence.expand_sequence(asset_path))
        else:
            first_path = asset_path

        path_in_project = self._path_in_project(first_path)
        use_as_is = usage.asset_path.is_blendfile_relative() and path_in_project
        needs_rewriting = not use_as_is

        act = self._actions[asset_path]
        assert isinstance(act, AssetAction)
        act.usages.append(usage)

        # NEW: UDIM tileset detection even when not flagged as sequence.
        # - If asset is a placeholder: store all discovered tiles.
        # - If asset is a numeric tile: add its sibling tiles as extras.
        if is_udim_placeholder and udim_tiles:
            act.extra_files.update(udim_tiles)
        else:
            tiles = self._find_udim_tiles(asset_path)
            if tiles:
                # Avoid copying the same file twice; the asset itself is already copied separately.
                for t in tiles:
                    if t != asset_path:
                        act.extra_files.add(t)

        project_abs = bpathlib.make_absolute(self.project)

        # PATCH: Always pack physically-in-project assets into the project layout,
        # even if referenced with absolute paths (those will just be rewritten).
        if path_in_project:
            try:
                asset_pp = self._target_path / asset_path.relative_to(project_abs)
                act.new_path = _nfc_path(asset_pp)
            except Exception:
                # If relative_to fails for any reason, treat as outside.
                act.new_path = None
                self._new_location_paths.add(asset_path)
        else:
            # Outside project => defer to _find_new_paths
            self._new_location_paths.add(asset_path)

        if needs_rewriting:
            log.info("%s needs rewritten path to %s", bfile_path, usage.asset_path)
            act.path_action = PathAction.FIND_NEW_LOCATION
            # IMPORTANT: do NOT force inside-project assets into _outside_project.
            # Only true outside-project assets go there.
        else:
            log.debug("%s can keep using %s", bfile_path, usage.asset_path)

    def _find_new_paths(self):
        """Find new locations in the BAT Pack for the given outside-project assets."""
        for path in self._new_location_paths:
            act = self._actions[path]
            assert isinstance(act, AssetAction)

            # Do not overwrite if already planned (can happen if callers add paths to set defensively)
            if act.new_path is not None:
                continue

            relpath = _outside_project_relpath(path)
            act.new_path = _nfc_path(
                pathlib.Path(self._target_path, "_outside_project", relpath)
            )

    def _group_rewrites(self) -> None:
        """For each blend file, collect which fields need rewriting.

        This ensures that the execute() step has to visit each blend file
        only once.
        """
        # Take a copy so we can modify self._actions in the loop.
        actions = set(self._actions.values())

        while actions:
            action = actions.pop()

            if action.path_action != PathAction.FIND_NEW_LOCATION:
                # This asset doesn't require a new location, so no rewriting necessary.
                continue

            for usage in action.usages:
                bfile_path = bpathlib.make_absolute(usage.block.bfile.filepath)
                insert_new_action = bfile_path not in self._actions

                self._actions[bfile_path].rewrites.append(usage)

                if insert_new_action:
                    actions.add(self._actions[bfile_path])

    def _path_in_project(self, path: pathlib.Path) -> bool:
        abs_path = bpathlib.make_absolute(path)
        abs_project = bpathlib.make_absolute(self.project)
        try:
            abs_path.relative_to(abs_project)
        except ValueError:
            return False
        return True

    def execute(self) -> None:
        """Execute the strategy."""
        assert self._actions, "Run strategise() first"

        # PATCH: allow rewriting even in noop mode when requested
        if (not self.noop) or self.rewrite_blendfiles:
            self._rewrite_paths()

        self._start_file_transferrer()
        self._perform_file_transfer()

        # Include unreadables in the “done” callback so they show up in UIs that only know 'missing'.
        missing_all = set(self.missing_files) | set(self.unreadable_files.keys())
        self._progress_cb.pack_done(self.output_path, missing_all)

    def _perform_file_transfer(self):
        """Use file transferrer to do the actual file transfer."""
        self._write_info_file()
        self._copy_files_to_target()

    def _create_file_transferer(self) -> transfer.FileTransferer:
        """Create a FileCopier(), can be overridden in a subclass."""
        if self.compress:
            return filesystem.CompressedFileCopier()
        return filesystem.FileCopier()

    def _start_file_transferrer(self):
        """Starts the file transferrer thread."""
        self._file_transferer = self._create_file_transferer()
        self._file_transferer.progress_cb = self._tscb
        if not self.noop:
            self._file_transferer.start()

    def _copy_files_to_target(self) -> None:
        """Copy all assets to the target directory."""
        log.debug("Executing %d copy actions", len(self._actions))
        assert self._file_transferer is not None

        try:
            for asset_path, action in self._actions.items():
                self._check_aborted()
                self._copy_asset_and_deps(asset_path, action)

            if self.noop:
                log.info("Would copy %d files to %s", self._file_count, self.target)
                return

            self._file_transferer.done_and_join()
            self._on_file_transfer_finished(file_transfer_completed=True)

        except KeyboardInterrupt:
            log.info("File transfer interrupted with Ctrl+C, aborting.")
            self._file_transferer.abort_and_join()
            self._on_file_transfer_finished(file_transfer_completed=False)
            raise
        finally:
            self._tscb.flush()
            self._check_aborted()
            self._file_transferer = None

    def _on_file_transfer_finished(self, *, file_transfer_completed: bool) -> None:
        """Called when the file transfer is finished (hook for subclasses)."""

    def _rewrite_paths(self) -> None:
        """Rewrite paths to the new location of the assets.

        Writes the rewritten blend files to a temporary location.
        """
        for bfile_path, action in self._actions.items():
            if not action.rewrites:
                continue
            self._check_aborted()

            assert isinstance(bfile_path, pathlib.Path)

            bfile_pp = action.new_path
            assert (
                bfile_pp is not None
            ), f"Action {action.path_action.name} on {bfile_path} has no final path set, unable to process"

            bfile_tmp = tempfile.NamedTemporaryFile(
                dir=str(self._rewrite_in),
                prefix="bat-",
                suffix="-" + bfile_path.name,
                delete=False,
            )
            bfile_tp = pathlib.Path(bfile_tmp.name)
            action.read_from = bfile_tp
            log.info("Rewriting %s to %s", bfile_path, bfile_tp)

            bfile = blendfile.open_cached(bfile_path, assert_cached=True)
            bfile.copy_and_rebind(bfile_tp, mode="rb+")

            for usage in action.rewrites:
                self._check_aborted()
                assert isinstance(usage, result.BlockUsage)
                asset_pp = self._actions[usage.abspath].new_path
                assert isinstance(asset_pp, pathlib.Path)

                log.debug("   - %s is packed at %s", usage.asset_path, asset_pp)
                relpath = bpathlib.BlendPath.mkrelative(asset_pp, bfile_pp)
                if relpath == usage.asset_path:
                    log.info("   - %s remained at %s", usage.asset_path, relpath)
                    continue

                log.info("   - %s moved to %s", usage.asset_path, relpath)

                block = bfile.dereference_pointer(usage.block.addr_old)
                assert block is not None

                if usage.path_full_field is None:
                    dir_field = usage.path_dir_field
                    assert dir_field is not None
                    log.debug(
                        "   - updating field %s of block %s",
                        dir_field.name.name_only,
                        block,
                    )
                    reldir = bpathlib.BlendPath.mkrelative(asset_pp.parent, bfile_pp)
                    written = block.set(dir_field.name.name_only, reldir)
                    log.debug("   - written %d bytes", written)
                else:
                    log.debug(
                        "   - updating field %s of block %s",
                        usage.path_full_field.name.name_only,
                        block,
                    )
                    written = block.set(usage.path_full_field.name.name_only, relpath)
                    log.debug("   - written %d bytes", written)

            if bfile.is_modified:
                self._progress_cb.rewrite_blendfile(bfile_path)
            bfile.close()

    def _copy_asset_and_deps(self, asset_path: pathlib.Path, action: AssetAction):
        asset_path_is_dir = asset_path.is_dir()

        # Copy the asset itself, but only if it's not a sequence (sequences are handled below).
        if (
            "*" not in str(asset_path)
            and "<UDIM>" not in asset_path.name
            and not asset_path_is_dir
        ):
            packed_path = action.new_path
            assert packed_path is not None
            read_path = action.read_from or asset_path
            self._send_to_target(
                read_path, packed_path, may_move=action.read_from is not None
            )

        # NEW: Copy any extra files associated with this asset (UDIM tiles, etc.)
        if action.extra_files:
            base_pp = action.new_path
            if base_pp is not None:
                for extra_path in sorted(set(action.extra_files)):
                    if extra_path == asset_path:
                        continue
                    # Place next to the packed asset (same directory, actual filename).
                    try:
                        extra_target = base_pp.with_name(extra_path.name)
                    except Exception:
                        extra_target = pathlib.PurePath(base_pp.parent, extra_path.name)
                    self._send_to_target(extra_path, extra_target)

        if asset_path_is_dir:  # like 'some/directory':
            asset_base_path = asset_path
        else:  # like 'some/directory/prefix_*.bphys':
            asset_base_path = asset_path.parent

        # Copy its sequence dependencies.
        for usage in action.usages:
            if not usage.is_sequence:
                continue

            first_pp = self._actions[usage.abspath].new_path
            assert first_pp is not None

            # In case of globbing, we only support globbing by filename, not by directory.
            assert "*" not in str(first_pp) or "*" in first_pp.name

            if asset_path_is_dir:
                packed_base_dir = first_pp
            else:
                packed_base_dir = first_pp.parent

            for file_path in usage.files():
                relpath = file_path.relative_to(asset_base_path)
                packed_path = packed_base_dir / relpath
                self._send_to_target(file_path, packed_path)

            break

    def _send_to_target(
        self, asset_path: pathlib.Path, target: pathlib.PurePath, may_move: bool = False
    ):
        # Preflight checks so we can report missing/unreadable *before* transfer.
        # This also ensures sequence files & UDIM tiles are validated.
        try:
            # Only check files; for dirs we rely on later expansion to files.
            if asset_path.exists() and asset_path.is_dir():
                ok = True
            else:
                ok = self._check_readable(asset_path)
        except Exception:
            ok = False

        if not ok:
            # Still record the planned target path in noop mode for diagnostics.
            if self.noop:
                self.file_map[asset_path] = _nfc_path(target)
            # Do not queue unreadable/missing files.
            return

        if self.noop:
            # NFC normalize planned target paths
            self.file_map[asset_path] = _nfc_path(target)
            self._file_count += 1
            return

        verb = "move" if may_move else "copy"
        log.debug("Queueing %s of %s", verb, asset_path)

        self._tscb.flush()

        assert self._file_transferer is not None
        if may_move:
            self._file_transferer.queue_move(asset_path, target)
        else:
            self._file_transferer.queue_copy(asset_path, target)

    def _write_info_file(self):
        """Write a little text file with info at the top of the pack."""
        infoname = "pack-info.txt"
        infopath = self._rewrite_in / infoname
        log.debug("Writing info to %s", infopath)

        with infopath.open("wt", encoding="utf8") as infofile:
            print("This is a Blender Asset Tracer pack.", file=infofile)
            print("Start by opening the following blend file:", file=infofile)
            print(
                "    %s" % self._output_path.relative_to(self._target_path).as_posix(),
                file=infofile,
            )

        # In noop mode the queue is ignored; in real mode it is moved into place.
        if self._file_transferer is not None:
            self._file_transferer.queue_move(infopath, self._target_path / infoname)


def shorten_path(cwd: pathlib.Path, somepath: pathlib.Path) -> pathlib.Path:
    """Return 'somepath' relative to CWD if possible."""
    try:
        return somepath.relative_to(cwd)
    except ValueError:
        return somepath
