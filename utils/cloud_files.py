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
from pathlib import Path
from typing import Optional, Tuple


def read_file_with_hydration(
    path: str,
    hydrate: bool = True,
    timeout_seconds: int = 30,
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
        timeout_seconds: Not used in this implementation (kept for API compat)

    Returns:
        (success, error_message) tuple where success=True means the file
        is readable.
    """
    path_str = str(path)

    # Quick check for directories
    try:
        if os.path.isdir(path_str):
            return (True, None)  # Directories are "readable"
    except Exception:
        pass

    # Try to open and read the file
    # This is the most reliable cross-platform way to:
    # 1. Check if the file exists
    # 2. Trigger cloud providers to download placeholder files
    # 3. Verify the file is actually readable
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
        return (True, None)  # Directories are ok
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


def is_cloud_placeholder(path: str) -> bool:
    """
    Check if a file might be a cloud placeholder.

    This is a heuristic check - it returns True if the file appears to be
    a cloud placeholder that might need hydration. The check is conservative
    and cross-platform.

    Note: This function is kept for API compatibility but the main logic
    in read_file_with_hydration handles cloud files transparently.
    """
    # Simple heuristic: if the file doesn't exist via os.path.exists but
    # we can get some info about it, it might be a cloud placeholder
    try:
        exists = os.path.exists(path)
        if exists:
            return False  # File exists normally, not a placeholder

        # File doesn't exist - could be missing or a placeholder
        # Try to check parent directory
        parent = os.path.dirname(path)
        if parent and os.path.isdir(parent):
            # Parent exists but file doesn't - could be cloud placeholder
            # or just missing. We can't tell for sure cross-platform.
            return False  # Assume missing, not placeholder

        return False
    except Exception:
        return False


# Alias for backwards compatibility
def hydrate_file(path: str, timeout_seconds: int = 30) -> Tuple[bool, Optional[str]]:
    """Alias for read_file_with_hydration with hydrate=True."""
    return read_file_with_hydration(path, hydrate=True, timeout_seconds=timeout_seconds)
