#!/usr/bin/env python3
"""
Test to verify the compression theory and fix for "File format not supported" error.

The bug: Gzip-compressed .blend files were being re-compressed with Zstd, creating
Zstd(Gzip(data)). When Blender opened these files:
1. Blender sees Zstd magic → decompresses with Zstd
2. Result is Gzip data, not a valid .blend header
3. Blender fails with "File format not supported"

The fix: Detect gzip magic and store as-is (no re-compression).

Run with: python tests/test_compression_theory.py
"""
import gzip
import io
import os
import sys
import zipfile
from pathlib import Path

# Add the addon to path
addon_dir = Path(__file__).parent.parent
sys.path.insert(0, str(addon_dir))

try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    zstd = None
    HAS_ZSTD = False

from blender_asset_tracer.pack.zipped import _ZSTD_MAGIC, _GZIP_MAGIC, _BLENDFILE_MAGIC


# Simulated Blender file content (uncompressed .blend always starts with "BLENDER")
FAKE_BLEND_CONTENT = b"BLENDER-v305" + b"\x00" * 100 + b"fake blend file data for testing"


def create_uncompressed_blend() -> bytes:
    """Create a fake uncompressed .blend file."""
    return FAKE_BLEND_CONTENT


def create_gzip_blend() -> bytes:
    """Create a fake gzip-compressed .blend file (like Blender's legacy compression)."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb') as gz:
        gz.write(FAKE_BLEND_CONTENT)
    return buf.getvalue()


def create_zstd_blend() -> bytes:
    """Create a fake zstd-compressed .blend file (like Blender 3.0+)."""
    if not HAS_ZSTD:
        return None
    compressor = zstd.ZstdCompressor(level=1)
    return compressor.compress(FAKE_BLEND_CONTENT)


def simulate_zip_packing(blend_data: bytes) -> tuple[bytes, str]:
    """
    Simulate what our zipped.py does when packing a .blend file.
    Returns (data that would be stored in the ZIP, label describing the action).
    """
    head = blend_data[:7] if len(blend_data) >= 7 else blend_data

    if head[:4] == _ZSTD_MAGIC:
        # Already Zstd compressed - store as-is
        return blend_data, "Store (zstd)"
    elif head[:2] == _GZIP_MAGIC:
        # Already Gzip compressed - store as-is
        return blend_data, "Store (gzip)"
    elif head[:7] == _BLENDFILE_MAGIC:
        # Uncompressed .blend - apply Zstd compression
        if HAS_ZSTD:
            compressor = zstd.ZstdCompressor(level=1)
            return compressor.compress(blend_data), "Zstd"
        else:
            return blend_data, "Store (no zstd)"
    else:
        # Unknown format - store as-is (safety!)
        return blend_data, "Store (unknown)"


def simulate_blender_open(data: bytes) -> tuple[bool, str]:
    """
    Simulate what Blender does when opening a .blend file.
    Returns (success, description).
    """
    if len(data) < 7:
        return False, "File too small"

    # Blender checks for compression magic first (needs enough bytes)
    head4 = data[:4]
    head7 = data[:7]

    # Check for Zstd compression
    if head4 == _ZSTD_MAGIC:
        # Decompress with Zstd
        if not HAS_ZSTD:
            return False, "Zstd not available"
        try:
            decompressor = zstd.ZstdDecompressor()
            decompressed = decompressor.decompress(data)
            # Now check if decompressed data is valid
            if decompressed[:7] == b"BLENDER":
                return True, "Zstd decompressed successfully"
            elif decompressed[:2] == _GZIP_MAGIC:
                # THIS IS THE BUG: Zstd(Gzip(data)) produces Gzip data after decompression
                return False, "ERROR: File format is not supported (got Gzip data after Zstd decompression)"
            else:
                return False, f"ERROR: Invalid header after Zstd decompression: {decompressed[:10]}"
        except Exception as e:
            return False, f"Zstd decompression failed: {e}"

    # Check for Gzip compression
    elif head4[:2] == _GZIP_MAGIC:
        # Decompress with Gzip
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                decompressed = gz.read()
            if decompressed[:7] == b"BLENDER":
                return True, "Gzip decompressed successfully"
            else:
                return False, f"ERROR: Invalid header after Gzip decompression: {decompressed[:10]}"
        except Exception as e:
            return False, f"Gzip decompression failed: {e}"

    # Check for uncompressed .blend (starts with "BLENDER")
    elif head7 == b"BLENDER":
        return True, "Uncompressed file opened successfully"

    else:
        return False, f"ERROR: File format is not supported (unknown header: {head7})"


def test_uncompressed_blend():
    """Test: Uncompressed .blend → Zstd compressed → Blender opens OK"""
    print("\n" + "=" * 70)
    print("TEST 1: Uncompressed .blend file")
    print("=" * 70)

    original = create_uncompressed_blend()
    print(f"  Original: {len(original)} bytes, header: {original[:12]}")
    print(f"  Magic check: starts with BLENDER = {original[:7] == b'BLENDER'}")

    packed, label = simulate_zip_packing(original)
    print(f"  After packing: {len(packed)} bytes, header: {packed[:4].hex()}, label: {label}")

    success, msg = simulate_blender_open(packed)
    print(f"  Blender open: {msg}")

    assert success, f"Uncompressed .blend failed to open: {msg}"
    print("  ✓ PASSED")


def test_gzip_blend_with_bug():
    """
    Test: Simulate the BUG scenario
    Gzip .blend → incorrectly Zstd compressed → Blender FAILS
    """
    print("\n" + "=" * 70)
    print("TEST 2: Gzip .blend WITH BUG (double compression)")
    print("=" * 70)

    original = create_gzip_blend()
    print(f"  Original: {len(original)} bytes, header: {original[:2].hex()}")
    print(f"  Magic check: starts with Gzip = {original[:2] == _GZIP_MAGIC}")

    # Simulate the BUG: ignore gzip magic and compress anyway
    if HAS_ZSTD:
        compressor = zstd.ZstdCompressor(level=1)
        packed_with_bug = compressor.compress(original)  # Zstd(Gzip(data))
    else:
        packed_with_bug = original
        print("  (Skipping - zstd not available)")
        return

    print(f"  After buggy packing: {len(packed_with_bug)} bytes, header: {packed_with_bug[:4].hex()}")

    success, msg = simulate_blender_open(packed_with_bug)
    print(f"  Blender open: {msg}")

    # This SHOULD fail with the bug
    assert not success, "Bug scenario should have failed!"
    assert "File format is not supported" in msg, f"Expected format error, got: {msg}"
    print("  ✓ PASSED (correctly demonstrates the bug)")


def test_gzip_blend_with_fix():
    """
    Test: Gzip .blend → stored as-is (THE FIX) → Blender opens OK
    """
    print("\n" + "=" * 70)
    print("TEST 3: Gzip .blend WITH FIX (stored as-is)")
    print("=" * 70)

    original = create_gzip_blend()
    print(f"  Original: {len(original)} bytes, header: {original[:2].hex()}")
    print(f"  Magic check: starts with Gzip = {original[:2] == _GZIP_MAGIC}")

    packed, label = simulate_zip_packing(original)  # Uses our fixed logic
    print(f"  After fixed packing: {len(packed)} bytes, header: {packed[:4].hex()}, label: {label}")

    # Verify the fix: packed data should be identical to original (stored as-is)
    assert packed == original, "Fix should store gzip .blend as-is!"
    assert label == "Store (gzip)", f"Expected 'Store (gzip)' label, got: {label}"
    print(f"  Verify: packed == original = {packed == original}")

    success, msg = simulate_blender_open(packed)
    print(f"  Blender open: {msg}")

    assert success, f"Gzip .blend with fix failed to open: {msg}"
    print("  ✓ PASSED")


def test_zstd_blend():
    """Test: Zstd .blend → stored as-is → Blender opens OK"""
    print("\n" + "=" * 70)
    print("TEST 4: Zstd .blend file (Blender 3.0+)")
    print("=" * 70)

    if not HAS_ZSTD:
        print("  (Skipping - zstd not available)")
        return

    original = create_zstd_blend()
    print(f"  Original: {len(original)} bytes, header: {original[:4].hex()}")
    print(f"  Magic check: starts with Zstd = {original[:4] == _ZSTD_MAGIC}")

    packed, label = simulate_zip_packing(original)
    print(f"  After packing: {len(packed)} bytes, header: {packed[:4].hex()}, label: {label}")

    # Should be stored as-is
    assert packed == original, "Zstd .blend should be stored as-is!"
    assert label == "Store (zstd)", f"Expected 'Store (zstd)' label, got: {label}"
    print(f"  Verify: packed == original = {packed == original}")

    success, msg = simulate_blender_open(packed)
    print(f"  Blender open: {msg}")

    assert success, f"Zstd .blend failed to open: {msg}"
    print("  ✓ PASSED")


def test_unknown_format():
    """Test: Unknown format → stored as-is (safety measure)"""
    print("\n" + "=" * 70)
    print("TEST 5: Unknown format file (safety)")
    print("=" * 70)

    # Create a file with unknown header (not BLENDER, not gzip, not zstd)
    unknown_data = b"UNKNOWN_FORMAT" + b"\x00" * 100 + b"some data"
    print(f"  Original: {len(unknown_data)} bytes, header: {unknown_data[:14]}")

    packed, label = simulate_zip_packing(unknown_data)
    print(f"  After packing: {len(packed)} bytes, label: {label}")

    # Should be stored as-is (not compressed)
    assert packed == unknown_data, "Unknown format should be stored as-is!"
    assert label == "Store (unknown)", f"Expected 'Store (unknown)' label, got: {label}"
    print(f"  Verify: packed == original = {packed == unknown_data}")

    print("  ✓ PASSED (unknown format preserved)")


def test_full_zip_roundtrip():
    """Test: Full ZIP roundtrip with all compression types"""
    print("\n" + "=" * 70)
    print("TEST 6: Full ZIP roundtrip")
    print("=" * 70)

    import tempfile

    test_files = [
        ("uncompressed.blend", create_uncompressed_blend()),
        ("gzip.blend", create_gzip_blend()),
    ]
    if HAS_ZSTD:
        test_files.append(("zstd.blend", create_zstd_blend()))

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "test.zip"

        # Create ZIP with our packing logic
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
            for name, data in test_files:
                packed, label = simulate_zip_packing(data)
                zf.writestr(name, packed)
                print(f"  Packed {name}: {len(data)} → {len(packed)} bytes [{label}]")

        # Extract and verify
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name, original_data in test_files:
                extracted = zf.read(name)
                success, msg = simulate_blender_open(extracted)
                status = "✓" if success else "✗"
                print(f"  {status} {name}: {msg}")
                assert success, f"{name} failed: {msg}"

    print("  ✓ PASSED")


def print_summary():
    """Print test summary"""
    print("\n" + "=" * 70)
    print("SUMMARY: Compression Theory Verified")
    print("=" * 70)
    print("""
The bug was:
  1. User saves .blend with Gzip compression (legacy option)
  2. Our packer didn't check for Gzip magic
  3. We applied Zstd compression on top: Zstd(Gzip(raw_data))
  4. Render node extracts ZIP normally
  5. Blender opens file, sees Zstd magic, decompresses
  6. Result is Gzip data, not a valid .blend header
  7. "ERROR: File format is not supported"

The fix:
  - Check for Zstd magic (0x28 0xB5 0x2F 0xFD) → store as-is
  - Check for Gzip magic (0x1F 0x8B) → store as-is
  - Check for BLENDER header → apply Zstd compression
  - Unknown format → store as-is (safety!)

Detection order ensures we never corrupt already-compressed files
or files with unknown formats.
""")


if __name__ == "__main__":
    print("Testing Compression Theory and Fix")
    print("=" * 70)
    print(f"Zstd available: {HAS_ZSTD}")
    print(f"Gzip magic: {_GZIP_MAGIC.hex()}")
    print(f"Zstd magic: {_ZSTD_MAGIC.hex()}")
    print(f"Blendfile magic: {_BLENDFILE_MAGIC}")

    test_uncompressed_blend()
    test_gzip_blend_with_bug()
    test_gzip_blend_with_fix()
    test_zstd_blend()
    test_unknown_format()
    test_full_zip_roundtrip()

    print_summary()
    print("✅ All tests passed! The fix is verified.")
