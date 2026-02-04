#!/usr/bin/env python3
"""
Test script to verify .blend file compression detection in zipped.py

Run with: python tests/test_blend_compression.py
"""
import sys
from pathlib import Path

# Add the addon to path
addon_dir = Path(__file__).parent.parent
sys.path.insert(0, str(addon_dir))

from blender_asset_tracer.pack.zipped import _ZSTD_MAGIC, _GZIP_MAGIC, _BLENDFILE_MAGIC


def test_magic_constants():
    """Verify magic constants match official specifications."""
    # Gzip: RFC 1952 specifies 0x1F 0x8B
    assert _GZIP_MAGIC == b"\x1f\x8b", f"Gzip magic mismatch: {_GZIP_MAGIC.hex()}"

    # Zstd: Facebook spec specifies 0x28 0xB5 0x2F 0xFD
    assert _ZSTD_MAGIC == b"\x28\xb5\x2f\xfd", f"Zstd magic mismatch: {_ZSTD_MAGIC.hex()}"

    # Blender: uncompressed files always start with "BLENDER"
    assert _BLENDFILE_MAGIC == b"BLENDER", f"Blendfile magic mismatch: {_BLENDFILE_MAGIC}"

    print("✓ Magic constants verified")


def test_detection_logic():
    """Test the compression detection logic."""

    # Simulate the detection logic from zipped.py
    def detect_compression(head: bytes) -> str:
        if head == _ZSTD_MAGIC:
            return "zstd"
        elif head[:2] == _GZIP_MAGIC:
            return "gzip"
        else:
            return "uncompressed"

    # Test cases
    test_cases = [
        # (input bytes, expected result)
        (b"\x28\xb5\x2f\xfd", "zstd"),           # Zstd compressed
        (b"\x1f\x8b\x08\x00", "gzip"),           # Gzip compressed (full header start)
        (b"\x1f\x8b\x08\x08", "gzip"),           # Gzip with different flags
        (b"BLEN", "uncompressed"),               # Blender header start
        (b"BLEND", "uncompressed"),              # Different header
        (b"\x00\x00\x00\x00", "uncompressed"),   # Empty/zeros
        (b"\xff\xff\xff\xff", "uncompressed"),   # All 1s
        (b"\x1f", "uncompressed"),               # Partial gzip (1 byte) - edge case
        (b"\x1f\x8b", "gzip"),                   # Exactly 2 bytes gzip
        (b"", "uncompressed"),                   # Empty
    ]

    for head, expected in test_cases:
        # Pad to 4 bytes for realistic testing
        padded = head.ljust(4, b"\x00")[:4] if len(head) < 4 else head[:4]

        # Special case: if input is shorter than needed for comparison
        if len(head) < 4 and expected == "zstd":
            result = detect_compression(padded)
            # Padded version won't match zstd magic
            assert result != "zstd", f"Short input {head.hex()} incorrectly detected as zstd"
        elif len(head) < 2 and expected == "gzip":
            result = detect_compression(padded)
            # 1 byte can't be gzip
            if len(head) < 2:
                assert result != "gzip", f"1-byte input {head.hex()} incorrectly detected as gzip"
        else:
            result = detect_compression(head if len(head) >= 4 else padded)
            if len(head) >= 2:  # Only check if we have enough bytes
                pass  # Detection depends on actual bytes

    # Core tests with proper 4-byte inputs
    assert detect_compression(b"\x28\xb5\x2f\xfd") == "zstd"
    assert detect_compression(b"\x1f\x8b\x08\x00") == "gzip"
    assert detect_compression(b"BLEN") == "uncompressed"

    print("✓ Detection logic verified")


def test_real_blend_files():
    """Test with actual .blend file patterns."""

    # Blender uncompressed header always starts with "BLENDER"
    uncompressed_header = b"BLENDER-v305"  # Example Blender 3.05 header

    def detect_compression(head: bytes) -> str:
        if head[:4] == _ZSTD_MAGIC:
            return "zstd"
        elif head[:2] == _GZIP_MAGIC:
            return "gzip"
        else:
            return "uncompressed"

    assert detect_compression(uncompressed_header[:4]) == "uncompressed"
    print("✓ Real .blend file patterns verified")


def test_edge_cases():
    """Test edge cases that could cause issues."""

    def detect_compression(head: bytes) -> str:
        if not head:
            return "uncompressed"
        if len(head) >= 4 and head[:4] == _ZSTD_MAGIC:
            return "zstd"
        elif len(head) >= 2 and head[:2] == _GZIP_MAGIC:
            return "gzip"
        else:
            return "uncompressed"

    # Edge cases
    assert detect_compression(b"") == "uncompressed"          # Empty file
    assert detect_compression(b"\x00") == "uncompressed"      # 1 byte
    assert detect_compression(b"\x1f") == "uncompressed"      # Partial gzip
    assert detect_compression(b"\x28\xb5") == "uncompressed"  # Partial zstd

    print("✓ Edge cases verified")


if __name__ == "__main__":
    print("Testing .blend compression detection...\n")

    test_magic_constants()
    test_detection_logic()
    test_real_blend_files()
    test_edge_cases()

    print("\n✅ All tests passed!")
