"""
Cloud file handling utilities - cross-platform.

Provides robust file reading for cloud-mounted drives (OneDrive, Google Drive,
iCloud, Dropbox, etc.) that use placeholder/dehydrated files.

The approach is simple and OS-agnostic:
1. Try to open and read the file
2. If reading succeeds, the file is available
3. If reading fails, classify the error appropriately
"""
from __future__ import annotations

import os
from typing import Optional, Tuple


def read_file_with_hydration(
    path: str,
    hydrate: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Read a file, ensuring it's fully available (hydrated for cloud files).

    This is a simple, cross-platform approach that works by actually reading
    the file content. For cloud-mounted drives, reading the file typically
    triggers the cloud provider to download it.

    Args:
        path: Path to the file
        hydrate: If True, read the entire file to ensure full availability.
                 If False, just read 1 byte to verify accessibility.

    Returns:
        (success, error_message) tuple where success=True means the file
        is readable.
    """
    path_str = str(path)

    # Quick check for directories. A directory is not an uploadable file; callers
    # that need directory dependencies should expand them before probing.
    try:
        if os.path.isdir(path_str):
            return (False, "is a directory")
    except Exception:
        pass

    # Reading checks existence and readability and triggers hydration when needed.
    try:
        with open(path_str, "rb") as f:
            if hydrate:
                # Read the entire file in chunks to ensure it's fully available.
                # This triggers cloud sync for dehydrated placeholders.
                chunk_size = 1024 * 1024  # 1 MiB
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
            else:
                # Just read 1 byte to verify accessibility
                f.read(1)
        return (True, None)

    except FileNotFoundError:
        return (False, "File not found")
    except IsADirectoryError:
        return (False, "is a directory")
    except PermissionError as e:
        return (False, f"Permission denied: {e}")
    except OSError as e:
        # OSError can indicate various issues including cloud file problems
        # Common error codes:
        # - ENOENT (2): No such file or directory
        # - EACCES (13): Permission denied
        # - EIO (5): I/O error (can happen with cloud files)
        error_code = getattr(e, 'errno', None)
        if error_code == 2:  # ENOENT
            return (False, "File not found")
        return (False, f"OS error: {e}")
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}")
