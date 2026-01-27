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
import fnmatch
import logging
import os
import pathlib
import typing

log = logging.getLogger(__name__)


def _looks_like_cloud_storage(p: pathlib.Path) -> bool:
    """Check if a path appears to be on cloud storage."""
    s = str(p).replace("\\", "/").lower()
    return (
        "/library/cloudstorage/" in s
        or "/dropbox" in s
        or "/onedrive" in s
        or "/icloud" in s
        or "/mobile documents/" in s
        or "/google drive/" in s
        or "googledrive" in s
        or "/my drive/" in s
    )


def _glob_fallback(path: pathlib.Path) -> typing.Iterator[pathlib.Path]:
    """Fallback glob using os.listdir + fnmatch for cloud storage.

    Standard glob() can fail on cloud storage due to various filesystem issues.
    This uses a more basic approach that's more compatible.
    """
    parent = path.parent
    pattern = path.name

    if not parent.exists():
        return

    try:
        entries = os.listdir(parent)
    except (PermissionError, OSError) as e:
        log.debug("Cannot list directory %s: %s", parent, e)
        return

    for entry in sorted(entries):
        if fnmatch.fnmatch(entry, pattern):
            full_path = parent / entry
            try:
                if full_path.is_file():
                    yield full_path
            except (PermissionError, OSError):
                # File exists but is inaccessible (cloud placeholder?)
                log.debug("Cannot access file: %s", full_path)
                continue


class DoesNotExist(OSError):
    """Indicates a path does not exist on the filesystem."""

    def __init__(self, path: pathlib.Path) -> None:
        super().__init__(path)
        self.path = path


def expand_sequence(path: pathlib.Path) -> typing.Iterator[pathlib.Path]:
    """Expand a file sequence path into the actual file paths.

    :param path: can be either a glob pattern (must contain a * character)
        or the path of the first file in the sequence.

    For cloud storage paths, uses fallback directory listing if glob fails.
    """
    is_cloud = _looks_like_cloud_storage(path)

    if "<UDIM>" in path.name:  # UDIM tiles
        # Change <UDIM> marker to a glob pattern, then let the glob case handle it.
        # This assumes that all files that match the glob are actually UDIM
        # tiles; this could cause some false-positives.
        path = path.with_name(path.name.replace("<UDIM>", "*"))

    if "*" in str(path):  # assume it is a glob
        import glob

        log.debug("expanding glob %s", path)
        found_any = False

        try:
            for fname in sorted(glob.glob(str(path), recursive=True)):
                found_any = True
                yield pathlib.Path(fname)
        except (PermissionError, OSError) as e:
            log.debug("glob failed for %s: %s", path, e)

        # Fallback for cloud storage if glob found nothing
        if not found_any and is_cloud:
            log.debug("Trying fallback glob for cloud path: %s", path)
            for p in _glob_fallback(path):
                yield p

        return

    # Check existence with better error handling for cloud storage
    try:
        exists = path.exists()
    except (PermissionError, OSError) as e:
        log.debug("Cannot check existence of %s: %s", path, e)
        # For cloud storage, try to continue anyway
        if is_cloud:
            exists = False
        else:
            raise DoesNotExist(path)

    if not exists:
        raise DoesNotExist(path)

    try:
        is_directory = path.is_dir()
    except (PermissionError, OSError):
        is_directory = False

    if is_directory:
        # Explode directory paths into separate files.
        try:
            for subpath in path.rglob("*"):
                try:
                    if subpath.is_file():
                        yield subpath
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError) as e:
            log.debug("Cannot recurse directory %s: %s", path, e)
            # Fallback to non-recursive listing
            try:
                for entry in os.listdir(path):
                    full_path = path / entry
                    try:
                        if full_path.is_file():
                            yield full_path
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError):
                pass
        return

    log.debug("expanding file sequence %s", path)

    import string

    stem_no_digits = path.stem.rstrip(string.digits)
    if stem_no_digits == path.stem:
        # Just a single file, no digits here.
        yield path
        return

    # Return everything start starts with 'stem_no_digits' and ends with the
    # same suffix as the first file. This may result in more files than used
    # by Blender, but at least it shouldn't miss any.
    pattern = "%s*%s" % (stem_no_digits, path.suffix)

    found_any = False
    try:
        for p in sorted(path.parent.glob(pattern)):
            found_any = True
            yield p
    except (PermissionError, OSError) as e:
        log.debug("glob failed for %s: %s", path.parent / pattern, e)

    # Fallback for cloud storage
    if not found_any and is_cloud:
        glob_path = path.parent / pattern
        for p in _glob_fallback(glob_path):
            yield p
