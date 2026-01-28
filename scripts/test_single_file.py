#!/usr/bin/env python
"""Test hydration on a single cloud file with verbose output."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# File to test - a known cloud placeholder from the previous test
TEST_FILE = r"G:\Shared drives\SOLACE Production\shots\teaser\SH050-asja-reveal\lighting\050_Projection_Layers\SH_050_Proj_1_Master-assets\FG_01b.png"


def get_win_attrs(path: str) -> dict:
    """Get Windows file attributes."""
    if sys.platform != "win32":
        return {}

    FILE_ATTRIBUTE_OFFLINE = 0x1000
    FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

    attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
    if attrs == 0xFFFFFFFF:
        return {"error": "INVALID_FILE_ATTRIBUTES"}

    return {
        "raw": hex(attrs),
        "offline": bool(attrs & FILE_ATTRIBUTE_OFFLINE),
        "recall_on_open": bool(attrs & FILE_ATTRIBUTE_RECALL_ON_OPEN),
        "recall_on_data_access": bool(attrs & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS),
    }


def main():
    path = TEST_FILE
    print(f"Testing: {path}")
    print()

    # Check parent directory
    parent = os.path.dirname(path)
    print(f"Parent directory: {parent}")
    print(f"  exists: {os.path.exists(parent)}")
    print(f"  isdir: {os.path.isdir(parent)}")
    if os.path.isdir(parent):
        try:
            contents = os.listdir(parent)[:10]
            print(f"  contents (first 10): {contents}")
        except Exception as e:
            print(f"  listdir error: {e}")
    print()

    # Check file attributes
    print("Windows attributes:")
    attrs = get_win_attrs(path)
    for k, v in attrs.items():
        print(f"  {k}: {v}")
    print()

    # Check file existence
    print("Standard Python checks:")
    print(f"  os.path.exists: {os.path.exists(path)}")
    print(f"  os.path.isfile: {os.path.isfile(path)}")
    try:
        st = os.stat(path)
        print(f"  os.stat: size={st.st_size}")
    except Exception as e:
        print(f"  os.stat: {type(e).__name__}: {e}")
    print()

    # Try different access methods
    print("Access attempts:")

    # Method 1: Direct open
    print("\n1. Python open():")
    try:
        with open(path, "rb") as f:
            data = f.read(1)
        print(f"   SUCCESS - read {len(data)} byte(s)")
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")

    # Method 2: ctypes CreateFile
    print("\n2. CreateFileW + ReadFile:")
    try:
        kernel32 = ctypes.windll.kernel32
        from ctypes import wintypes

        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80

        handle = kernel32.CreateFileW(
            path, GENERIC_READ, FILE_SHARE_READ, None,
            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
        )
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            print(f"   FAILED: CreateFileW error {error}")
        else:
            buffer = ctypes.create_string_buffer(4096)
            bytes_read = wintypes.DWORD()
            result = kernel32.ReadFile(handle, buffer, 4096, ctypes.byref(bytes_read), None)
            kernel32.CloseHandle(handle)
            if result:
                print(f"   SUCCESS - read {bytes_read.value} bytes")
            else:
                error = ctypes.get_last_error()
                print(f"   ReadFile FAILED: error {error}")
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")

    # Method 3: robocopy
    print("\n3. robocopy to temp:")
    try:
        temp_dir = tempfile.mkdtemp(prefix="test_hydrate_")
        filename = os.path.basename(path)
        parent_dir = os.path.dirname(path)

        result = subprocess.run(
            ["robocopy", parent_dir, temp_dir, filename, "/NFL", "/NDL", "/NJH", "/NJS"],
            capture_output=True,
            timeout=30,
        )
        print(f"   returncode: {result.returncode}")
        print(f"   stdout: {result.stdout.decode('utf-8', errors='replace').strip()}")
        print(f"   stderr: {result.stderr.decode('utf-8', errors='replace').strip()}")

        # Check if file was copied
        temp_file = os.path.join(temp_dir, filename)
        if os.path.exists(temp_file):
            print(f"   File copied successfully: {os.path.getsize(temp_file)} bytes")
        else:
            print(f"   File was NOT copied")

        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")

    # Method 4: cmd copy
    print("\n4. cmd copy to NUL:")
    try:
        result = subprocess.run(
            ["cmd", "/c", f'copy "{path}" NUL'],
            capture_output=True,
            timeout=30,
        )
        print(f"   returncode: {result.returncode}")
        print(f"   stdout: {result.stdout.decode('utf-8', errors='replace').strip()}")
        print(f"   stderr: {result.stderr.decode('utf-8', errors='replace').strip()}")
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")

    # Method 5: Check if file is available after attempts
    print("\n5. Final check - Python open():")
    try:
        with open(path, "rb") as f:
            data = f.read(100)
        print(f"   SUCCESS - read {len(data)} bytes")
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
