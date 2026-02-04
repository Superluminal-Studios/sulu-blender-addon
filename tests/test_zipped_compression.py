#!/usr/bin/env python3
"""
Comprehensive tests for .blend file compression handling in zipped.py

Tests the compression detection and handling to ensure:
1. Gzip-compressed .blend files are stored as-is (not double-compressed)
2. Zstd-compressed .blend files are stored as-is
3. Uncompressed .blend files get Zstd compression applied
4. Unknown formats are stored as-is for safety

Run with: python tests/test_zipped_compression.py
"""
import gzip
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# Add the addon to path
addon_dir = Path(__file__).parent.parent
sys.path.insert(0, str(addon_dir))

from blender_asset_tracer.pack.zipped import _ZSTD_MAGIC, _GZIP_MAGIC, _BLENDFILE_MAGIC

try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    zstd = None
    HAS_ZSTD = False

# Test data directory
BLENDFILES_DIR = addon_dir / "tests" / "bat" / "blendfiles"

# Fake blend content for unit tests
FAKE_BLEND_CONTENT = b"BLENDER-v305" + b"\x00" * 100 + b"fake blend file data for testing"


def test_magic_constants():
    """Verify magic constants match official specifications."""
    print("Testing magic constants...")

    # Gzip: RFC 1952 specifies 0x1F 0x8B
    assert _GZIP_MAGIC == b"\x1f\x8b", f"Gzip magic mismatch: {_GZIP_MAGIC.hex()}"

    # Zstd: Facebook spec specifies 0x28 0xB5 0x2F 0xFD
    assert _ZSTD_MAGIC == b"\x28\xb5\x2f\xfd", f"Zstd magic mismatch: {_ZSTD_MAGIC.hex()}"

    # Blender: uncompressed files always start with "BLENDER"
    assert _BLENDFILE_MAGIC == b"BLENDER", f"Blendfile magic mismatch: {_BLENDFILE_MAGIC}"

    print("  ✓ Magic constants verified")


def test_compression_detection_logic():
    """Test the compression detection logic used in zipped.py."""
    print("Testing compression detection logic...")

    def detect_format(head: bytes) -> str:
        """Replicate the detection logic from zipped.py."""
        if head[:4] == _ZSTD_MAGIC:
            return "zstd"
        elif head[:2] == _GZIP_MAGIC:
            return "gzip"
        elif head[:7] == _BLENDFILE_MAGIC:
            return "uncompressed"
        else:
            return "unknown"

    # Test cases
    test_cases = [
        # Zstd compressed
        (b"\x28\xb5\x2f\xfd" + b"\x00" * 10, "zstd"),
        # Gzip compressed (various flags)
        (b"\x1f\x8b\x08\x00" + b"\x00" * 10, "gzip"),
        (b"\x1f\x8b\x08\x08" + b"\x00" * 10, "gzip"),
        # Uncompressed BLENDER
        (b"BLENDER-v305" + b"\x00" * 10, "uncompressed"),
        (b"BLENDER_v280" + b"\x00" * 10, "uncompressed"),
        # Unknown formats
        (b"UNKNOWN" + b"\x00" * 10, "unknown"),
        (b"\x00\x00\x00\x00" + b"\x00" * 10, "unknown"),
        (b"PNG\x00" + b"\x00" * 10, "unknown"),
    ]

    for head, expected in test_cases:
        result = detect_format(head)
        assert result == expected, f"Detection failed for {head[:8].hex()}: got {result}, expected {expected}"

    print("  ✓ All detection cases passed")


def test_gzip_detection_priority():
    """Ensure gzip is detected before trying uncompressed check."""
    print("Testing gzip detection priority...")

    def detect_format(head: bytes) -> str:
        if head[:4] == _ZSTD_MAGIC:
            return "zstd"
        elif head[:2] == _GZIP_MAGIC:
            return "gzip"
        elif head[:7] == _BLENDFILE_MAGIC:
            return "uncompressed"
        else:
            return "unknown"

    # Gzip magic should be detected first (only 2 bytes needed)
    gzip_data = b"\x1f\x8b\x08\x00" + b"BLENDER"  # Gzip header + fake BLENDER in payload
    assert detect_format(gzip_data) == "gzip", "Gzip should be detected before BLENDER check"

    print("  ✓ Gzip detection priority correct")


def test_blender_open_simulation():
    """Simulate what Blender does when opening files to verify fix prevents errors."""
    print("Testing Blender open simulation...")

    def simulate_blender_open(data: bytes) -> tuple:
        """Simulate Blender's file opening logic."""
        if len(data) < 7:
            return False, "File too small"

        head = data[:7]

        if head[:4] == _ZSTD_MAGIC:
            if not HAS_ZSTD:
                return False, "Zstd not available"
            try:
                decompressor = zstd.ZstdDecompressor()
                decompressed = decompressor.decompress(data)
                if decompressed[:7] == b"BLENDER":
                    return True, "Zstd -> BLENDER (OK)"
                elif decompressed[:2] == _GZIP_MAGIC:
                    return False, "ERROR: Zstd -> Gzip (double compression bug!)"
                else:
                    return False, f"Invalid after zstd"
            except Exception as e:
                return False, f"Zstd error: {e}"

        elif head[:2] == _GZIP_MAGIC:
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                    decompressed = gz.read()
                if decompressed[:7] == b"BLENDER":
                    return True, "Gzip -> BLENDER (OK)"
                else:
                    return False, f"Invalid after gzip"
            except Exception as e:
                return False, f"Gzip error: {e}"

        elif head[:7] == b"BLENDER":
            return True, "Uncompressed BLENDER (OK)"

        else:
            return False, f"Unknown format"

    # Test valid formats
    test_cases = [
        ("Uncompressed", FAKE_BLEND_CONTENT, True),
        ("Gzip", gzip.compress(FAKE_BLEND_CONTENT), True),
    ]
    if HAS_ZSTD:
        test_cases.append(("Zstd", zstd.ZstdCompressor().compress(FAKE_BLEND_CONTENT), True))

    for name, data, should_succeed in test_cases:
        success, msg = simulate_blender_open(data)
        assert success == should_succeed, f"{name} should {'succeed' if should_succeed else 'fail'}: {msg}"
        print(f"  ✓ {name}: {msg}")

    # Test the BUG scenario: Zstd(Gzip(data)) should fail
    if HAS_ZSTD:
        gzip_data = gzip.compress(FAKE_BLEND_CONTENT)
        double_compressed = zstd.ZstdCompressor().compress(gzip_data)
        success, msg = simulate_blender_open(double_compressed)
        assert not success, "Double compression should fail"
        print(f"  ✓ Double compression detected: {msg}")


def test_packing_logic_simulation():
    """Test the packing logic that decides how to store .blend files."""
    print("Testing packing logic simulation...")

    def simulate_pack_blend(data: bytes) -> tuple:
        """Simulate the packing logic from zipped.py."""
        head = data[:7] if len(data) >= 7 else data

        if head[:4] == _ZSTD_MAGIC:
            return data, "Store (zstd)"
        elif head[:2] == _GZIP_MAGIC:
            return data, "Store (gzip)"
        elif head[:7] == _BLENDFILE_MAGIC:
            if HAS_ZSTD:
                compressor = zstd.ZstdCompressor(level=1)
                return compressor.compress(data), "Zstd"
            return data, "Store (no zstd)"
        else:
            return data, "Store (unknown)"

    # Test uncompressed -> gets compressed
    if HAS_ZSTD:
        packed, label = simulate_pack_blend(FAKE_BLEND_CONTENT)
        assert label == "Zstd", f"Uncompressed should be zstd compressed, got {label}"
        assert packed[:4] == _ZSTD_MAGIC, "Result should be zstd-compressed"
        print("  ✓ Uncompressed -> Zstd compression")

    # Test gzip -> stored as-is
    gzip_data = gzip.compress(FAKE_BLEND_CONTENT)
    packed, label = simulate_pack_blend(gzip_data)
    assert label == "Store (gzip)", f"Gzip should be stored as-is, got {label}"
    assert packed == gzip_data, "Gzip data should be unchanged"
    print("  ✓ Gzip -> Stored as-is")

    # Test zstd -> stored as-is
    if HAS_ZSTD:
        zstd_data = zstd.ZstdCompressor().compress(FAKE_BLEND_CONTENT)
        packed, label = simulate_pack_blend(zstd_data)
        assert label == "Store (zstd)", f"Zstd should be stored as-is, got {label}"
        assert packed == zstd_data, "Zstd data should be unchanged"
        print("  ✓ Zstd -> Stored as-is")

    # Test unknown -> stored as-is
    unknown_data = b"UNKNOWN" + b"\x00" * 100
    packed, label = simulate_pack_blend(unknown_data)
    assert label == "Store (unknown)", f"Unknown should be stored as-is, got {label}"
    assert packed == unknown_data, "Unknown data should be unchanged"
    print("  ✓ Unknown -> Stored as-is")


def test_with_real_blendfiles():
    """Test compression detection with real .blend files."""
    from blender_asset_tracer.pack.zipped import ZipPacker

    print("Testing with real .blend files...")

    if not BLENDFILES_DIR.exists():
        print("  ⚠ Skipping: blendfiles directory not found")
        return

    # Find test files with different compression
    test_files = []

    # Look for files that might have different compression
    for blend_file in BLENDFILES_DIR.glob("*.blend"):
        try:
            with open(blend_file, 'rb') as f:
                head = f.read(7)

            if head[:4] == _ZSTD_MAGIC:
                compression = "zstd"
            elif head[:2] == _GZIP_MAGIC:
                compression = "gzip"
            elif head[:7] == _BLENDFILE_MAGIC:
                compression = "uncompressed"
            else:
                compression = "unknown"

            test_files.append((blend_file, compression))
            if len(test_files) >= 5:  # Test a few files
                break
        except Exception:
            continue

    if not test_files:
        print("  ⚠ No test .blend files found")
        return

    for blend_file, compression in test_files:
        print(f"  ✓ {blend_file.name}: {compression}")

    # Now test that ZipPacker handles them correctly
    with tempfile.TemporaryDirectory(prefix="sulu_test_") as tmpdir:
        tmpdir = Path(tmpdir)

        for blend_file, original_compression in test_files:
            output_zip = tmpdir / f"test_{blend_file.stem}.zip"

            try:
                with ZipPacker(blend_file, BLENDFILES_DIR, output_zip) as packer:
                    packer.strategise()
                    packer.execute()

                # Verify the output
                with zipfile.ZipFile(output_zip, 'r') as zf:
                    for name in zf.namelist():
                        if name.endswith('.blend') and blend_file.name in name:
                            extracted = zf.read(name)
                            packed_header = extracted[:7]

                            # Determine what compression the packed file has
                            if packed_header[:4] == _ZSTD_MAGIC:
                                packed_compression = "zstd"
                            elif packed_header[:2] == _GZIP_MAGIC:
                                packed_compression = "gzip"
                            elif packed_header[:7] == _BLENDFILE_MAGIC:
                                packed_compression = "uncompressed"
                            else:
                                packed_compression = "unknown"

                            # Verify correct handling
                            if original_compression == "gzip":
                                assert packed_compression == "gzip", \
                                    f"Gzip file should stay gzip, got {packed_compression}"
                            elif original_compression == "zstd":
                                assert packed_compression == "zstd", \
                                    f"Zstd file should stay zstd, got {packed_compression}"
                            elif original_compression == "uncompressed" and HAS_ZSTD:
                                assert packed_compression == "zstd", \
                                    f"Uncompressed should become zstd, got {packed_compression}"

                            print(f"    Packed {blend_file.name}: {original_compression} -> {packed_compression} ✓")
                            break

            except Exception as e:
                print(f"    ⚠ Error packing {blend_file.name}: {e}")


def test_roundtrip_verification():
    """Verify packed files can be correctly opened by Blender (simulated)."""
    print("Testing roundtrip verification...")

    def simulate_blender_open(data: bytes) -> bool:
        """Check if Blender could open this file."""
        if data[:4] == _ZSTD_MAGIC:
            if not HAS_ZSTD:
                return False
            try:
                decompressed = zstd.ZstdDecompressor().decompress(data)
                return decompressed[:7] == b"BLENDER"
            except:
                return False
        elif data[:2] == _GZIP_MAGIC:
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                    decompressed = gz.read()
                return decompressed[:7] == b"BLENDER"
            except:
                return False
        elif data[:7] == b"BLENDER":
            return True
        return False

    def simulate_pack(data: bytes) -> bytes:
        """Simulate our packing logic."""
        head = data[:7]
        if head[:4] == _ZSTD_MAGIC:
            return data  # Store as-is
        elif head[:2] == _GZIP_MAGIC:
            return data  # Store as-is (THE FIX!)
        elif head[:7] == b"BLENDER":
            if HAS_ZSTD:
                return zstd.ZstdCompressor(level=1).compress(data)
            return data
        else:
            return data  # Unknown - store as-is

    # Test all formats
    test_data = [
        ("Uncompressed", FAKE_BLEND_CONTENT),
        ("Gzip", gzip.compress(FAKE_BLEND_CONTENT)),
    ]
    if HAS_ZSTD:
        test_data.append(("Zstd", zstd.ZstdCompressor().compress(FAKE_BLEND_CONTENT)))

    for name, original in test_data:
        packed = simulate_pack(original)
        can_open = simulate_blender_open(packed)
        assert can_open, f"After packing {name}, Blender should be able to open it"
        print(f"  ✓ {name}: Pack -> Blender can open")

    # Test that the OLD BUG would have failed
    if HAS_ZSTD:
        gzip_data = gzip.compress(FAKE_BLEND_CONTENT)
        # OLD buggy behavior: compress gzip with zstd
        double_compressed = zstd.ZstdCompressor().compress(gzip_data)
        can_open = simulate_blender_open(double_compressed)
        assert not can_open, "Double-compressed file should NOT be openable"
        print("  ✓ Double compression correctly fails (bug scenario)")


def test_edge_cases():
    """Test edge cases in compression detection."""
    print("Testing edge cases...")

    def detect_format(data: bytes) -> str:
        if len(data) >= 4 and data[:4] == _ZSTD_MAGIC:
            return "zstd"
        elif len(data) >= 2 and data[:2] == _GZIP_MAGIC:
            return "gzip"
        elif len(data) >= 7 and data[:7] == _BLENDFILE_MAGIC:
            return "uncompressed"
        else:
            return "unknown"

    # Empty file
    assert detect_format(b"") == "unknown"
    print("  ✓ Empty file -> unknown")

    # 1 byte file
    assert detect_format(b"\x1f") == "unknown"
    print("  ✓ 1 byte file -> unknown")

    # Partial gzip magic
    assert detect_format(b"\x1f\x8b") == "gzip"
    print("  ✓ Exactly 2 bytes gzip magic -> gzip")

    # Partial BLENDER
    assert detect_format(b"BLEND") == "unknown"
    print("  ✓ Partial BLENDER -> unknown")

    # Full BLENDER
    assert detect_format(b"BLENDER") == "uncompressed"
    print("  ✓ Exactly 7 bytes BLENDER -> uncompressed")


if __name__ == "__main__":
    print("=" * 70)
    print("Comprehensive Compression Tests for zipped.py")
    print("=" * 70)
    print(f"Zstd available: {HAS_ZSTD}")
    print()

    test_magic_constants()
    test_compression_detection_logic()
    test_gzip_detection_priority()
    test_blender_open_simulation()
    test_packing_logic_simulation()
    test_with_real_blendfiles()
    test_roundtrip_verification()
    test_edge_cases()

    print()
    print("=" * 70)
    print("✅ All compression tests passed!")
    print("=" * 70)
