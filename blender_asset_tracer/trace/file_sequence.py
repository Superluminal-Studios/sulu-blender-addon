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
import logging
import os
import pathlib
import typing

log = logging.getLogger(__name__)


class DoesNotExist(OSError):
    """Indicates a path does not exist on the filesystem."""

    def __init__(self, path: pathlib.Path) -> None:
        super().__init__(path)
        self.path = path


def _prime_cloud_directory(directory: pathlib.Path) -> None:
    """
    Attempt to 'wake up' a cloud-mounted directory.

    On cloud drives (OneDrive, Google Drive, iCloud, Dropbox), placeholder
    files might not appear in directory listings until the directory is
    accessed. This function tries to trigger that sync by:
    1. Listing the directory contents (triggers cloud metadata sync)
    2. Attempting to access a few entries (triggers cloud to update)

    This is a best-effort operation - it may not work for all cloud providers.
    """
    try:
        if not directory.is_dir():
            return

        # List directory contents - this often triggers cloud sync
        entries = list(directory.iterdir())

        # Try to stat a few entries to further trigger sync
        for entry in entries[:5]:
            try:
                entry.stat()
            except Exception:
                pass

    except Exception:
        # Ignore errors - this is just a best-effort attempt
        pass


def _try_open_file(path: pathlib.Path) -> bool:
    """
    Try to open a file for reading.

    Returns True if the file can be opened, False otherwise.
    This triggers cloud providers to download placeholder files.
    """
    try:
        with open(path, "rb") as f:
            f.read(1)
        return True
    except Exception:
        return False


def expand_sequence(path: pathlib.Path) -> typing.Iterator[pathlib.Path]:
    """Expand a file sequence path into the actual file paths.

    :param path: can be either a glob pattern (must contain a * character)
        or the path of the first file in the sequence.

    For cloud-mounted drives, this function attempts to trigger sync before
    listing directories, as placeholder files might not appear otherwise.
    """

    if "<UDIM>" in path.name:  # UDIM tiles
        # Change <UDIM> marker to a glob pattern, then let the glob case handle it.
        # This assumes that all files that match the glob are actually UDIM
        # tiles; this could cause some false-positives.
        path = path.with_name(path.name.replace("<UDIM>", "*"))

    if "*" in str(path):  # assume it is a glob
        import glob

        log.debug("expanding glob %s", path)

        # Prime the parent directory to trigger cloud sync before globbing
        parent = path.parent
        if parent.is_dir():
            _prime_cloud_directory(parent)

        for fname in sorted(glob.glob(str(path), recursive=True)):
            yield pathlib.Path(fname)
        return

    # For non-glob paths, try to open the file first (triggers cloud sync)
    # before falling back to exists() check
    if _try_open_file(path):
        if path.is_dir():
            # Explode directory paths into separate files.
            _prime_cloud_directory(path)
            for subpath in path.rglob("*"):
                if subpath.is_file():
                    yield subpath
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
        _prime_cloud_directory(path.parent)
        yield from sorted(path.parent.glob(pattern))
        return

    # File doesn't exist or can't be opened
    if not path.exists():
        raise DoesNotExist(path)
