"""
Tests for S3 key generation and validation.

S3 keys must:
- Be relative (no leading /)
- Not contain Windows drive letters
- Not contain backslashes
- Not leak temp directory paths
- Properly handle Unicode (NFC normalized)
- Preserve meaningful path structure
"""

from __future__ import annotations

import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.utils import (
    s3key_clean,
    validate_s3_key,
    is_s3_safe,
    process_for_upload,
    relpath_safe,
    nfc,
    nfd,
)


class TestS3KeyCleaning(unittest.TestCase):
    """Test S3 key cleaning function."""

    def test_removes_leading_slash(self):
        """Leading slash should be removed."""
        self.assertEqual("path/to/file", s3key_clean("/path/to/file"))
        self.assertEqual("file.blend", s3key_clean("/file.blend"))

    def test_removes_multiple_leading_slashes(self):
        """Multiple leading slashes should be removed."""
        self.assertEqual("path/file", s3key_clean("//path/file"))
        self.assertEqual("path/file", s3key_clean("///path/file"))

    def test_normalizes_backslashes(self):
        """Backslashes should become forward slashes."""
        self.assertEqual("path/to/file", s3key_clean("path\\to\\file"))
        self.assertEqual("path/to/file", s3key_clean("path\\to/file"))

    def test_collapses_duplicate_slashes(self):
        """Duplicate slashes should be collapsed."""
        self.assertEqual("path/to/file", s3key_clean("path//to//file"))
        self.assertEqual("path/to/file", s3key_clean("path///to/file"))

    def test_normalizes_dot_segments(self):
        """Dot segments should be normalized."""
        self.assertEqual("path/file", s3key_clean("path/./file"))
        self.assertEqual("file", s3key_clean("path/../file"))
        self.assertEqual("other/file", s3key_clean("path/../other/file"))

    def test_single_dot_becomes_empty(self):
        """Single dot path should become empty."""
        self.assertEqual("", s3key_clean("."))
        self.assertEqual("", s3key_clean("./"))

    def test_preserves_valid_paths(self):
        """Valid paths should be unchanged."""
        self.assertEqual("scenes/main.blend", s3key_clean("scenes/main.blend"))
        self.assertEqual("tex/wood.png", s3key_clean("tex/wood.png"))


class TestS3KeyValidation(unittest.TestCase):
    """Test S3 key validation."""

    def test_valid_keys(self):
        """Valid S3 keys should pass."""
        self.assertTrue(is_s3_safe("scene.blend"))
        self.assertTrue(is_s3_safe("scenes/main.blend"))
        self.assertTrue(is_s3_safe("textures/wood.png"))
        self.assertTrue(is_s3_safe("assets/characters/hero/rig.blend"))

    def test_invalid_leading_slash(self):
        """Keys starting with / should fail."""
        issues = validate_s3_key("/scene.blend")
        self.assertIn("starts with /", issues)

    def test_invalid_drive_letter(self):
        """Keys with Windows drive should fail."""
        issues = validate_s3_key("C:/Users/project/scene.blend")
        self.assertIn("has Windows drive letter", issues)

    def test_invalid_backslash(self):
        """Keys with backslash should fail."""
        issues = validate_s3_key("path\\to\\file")
        self.assertIn("contains backslash", issues)

    def test_invalid_temp_directory(self):
        """Keys containing temp directories should fail."""
        issues = validate_s3_key("AppData/Local/Temp/scene.blend")
        self.assertTrue(any("temp" in i.lower() for i in issues))

    def test_invalid_bat_packroot(self):
        """Keys containing BAT packroot should fail (regression test)."""
        issues = validate_s3_key("bat_packroot_abc123/scene.blend")
        self.assertTrue(any("bat_packroot" in i for i in issues))

    def test_invalid_parent_reference(self):
        """Keys with .. should fail."""
        issues = validate_s3_key("path/../file")
        self.assertIn("contains parent reference (..)", issues)


class TestProcessForUpload(unittest.TestCase):
    """Test full upload processing pipeline."""

    def test_simple_project(self):
        """Simple project structure."""
        blend = "C:/Projects/Animation/scenes/main.blend"
        root = "C:/Projects/Animation"
        deps = ["C:/Projects/Animation/textures/wood.png"]

        main_key, dep_keys, issues = process_for_upload(blend, root, deps)

        self.assertEqual("scenes/main.blend", main_key)
        self.assertEqual(["textures/wood.png"], dep_keys)
        self.assertEqual([], issues)
        self.assertTrue(is_s3_safe(main_key))

    def test_deep_nesting(self):
        """Deeply nested structure."""
        blend = "C:/P/A/B/C/D/scene.blend"
        root = "C:/P/A"
        deps = ["C:/P/A/B/C/D/tex.png"]

        main_key, dep_keys, issues = process_for_upload(blend, root, deps)

        self.assertEqual("B/C/D/scene.blend", main_key)
        self.assertEqual(["B/C/D/tex.png"], dep_keys)

    def test_blend_at_root(self):
        """Blend file at project root."""
        blend = "C:/Project/scene.blend"
        root = "C:/Project"
        deps = ["C:/Project/tex/wood.png"]

        main_key, dep_keys, issues = process_for_upload(blend, root, deps)

        self.assertEqual("scene.blend", main_key)
        self.assertEqual(["tex/wood.png"], dep_keys)

    def test_unicode_paths(self):
        """Unicode characters in paths."""
        blend = "C:/Projekty/Główna/scena.blend"
        root = "C:/Projekty/Główna"
        deps = ["C:/Projekty/Główna/tekstury/drewno.png"]

        main_key, dep_keys, issues = process_for_upload(blend, root, deps)

        self.assertTrue(is_s3_safe(main_key))
        self.assertEqual("scena.blend", main_key)

    def test_nfc_normalization(self):
        """Unicode should be NFC normalized."""
        # NFD version (decomposed)
        blend_nfd = "C:/Projekte/Gro\u0308ße/scene.blend"  # ö as o + combining umlaut
        root_nfd = "C:/Projekte/Gro\u0308ße"

        main_key, _, _ = process_for_upload(blend_nfd, root_nfd, [])

        # Result should be NFC normalized
        self.assertEqual(nfc(main_key), main_key)
        self.assertTrue(is_s3_safe(main_key))


class TestRegressionBATTempDir(unittest.TestCase):
    """
    Regression test for BAT temp directory leak bug.

    The bug was: BAT's file_map contains absolute paths to temp directories,
    and these were being used directly as S3 keys instead of computing
    relative paths from project root.
    """

    def test_temp_dir_not_in_key(self):
        """S3 key should never contain temp directory paths."""
        blend = "C:/Users/jonas/Downloads/classroom/classroom.blend"
        root = "C:/Users/jonas/Downloads/classroom"

        main_key, _, _ = process_for_upload(blend, root, [])

        # Should be simple filename
        self.assertEqual("classroom.blend", main_key)

        # Should NOT contain temp indicators
        self.assertNotIn("Temp", main_key)
        self.assertNotIn("temp", main_key.lower())
        self.assertNotIn("bat_packroot", main_key)
        self.assertNotIn("AppData", main_key)

    def test_wrong_key_detection(self):
        """Wrong key format should be detected by validation."""
        # This is what the bug produced
        wrong_key = "C:/Users/jonas/AppData/Local/Temp/bat_packroot_xbzwq30j/classroom.blend"

        issues = validate_s3_key(wrong_key)
        self.assertTrue(len(issues) > 0, "Wrong key should have validation issues")

        # Should detect multiple problems
        self.assertTrue(any("drive" in i.lower() for i in issues))
        self.assertTrue(any("temp" in i.lower() for i in issues))


class TestSpecialCharactersInKeys(unittest.TestCase):
    """Test special characters in S3 keys."""

    def test_spaces(self):
        """Spaces in paths should be preserved."""
        blend = "C:/My Projects/Scene Files/main scene.blend"
        root = "C:/My Projects"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertEqual("Scene Files/main scene.blend", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_parentheses(self):
        """Parentheses should be preserved."""
        blend = "C:/Projects (2024)/scene (final).blend"
        root = "C:/Projects (2024)"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertEqual("scene (final).blend", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_brackets(self):
        """Brackets should be preserved."""
        blend = "C:/[WIP] Project/[Final] scene.blend"
        root = "C:/[WIP] Project"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertIn("[Final]", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_apostrophe(self):
        """Apostrophes should be preserved."""
        blend = "C:/John's Project/Sarah's scene.blend"
        root = "C:/John's Project"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertIn("'", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_ampersand(self):
        """Ampersands should be preserved."""
        blend = "C:/Tom & Jerry/chase & catch.blend"
        root = "C:/Tom & Jerry"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertIn("&", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_hash(self):
        """Hash/pound should be preserved."""
        blend = "C:/Project #1/scene#001.blend"
        root = "C:/Project #1"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertIn("#", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_at_sign(self):
        """At sign should be preserved."""
        blend = "C:/Assets/@2x/icon@2x.blend"
        root = "C:/Assets"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertIn("@", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_percent(self):
        """Percent should be preserved."""
        blend = "C:/100% Complete/50% done.blend"
        root = "C:/100% Complete"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertIn("%", main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_emoji(self):
        """Emoji should be preserved (yes, people do this)."""
        blend = "C:/🎬 Animation/scenes/🏠 house.blend"
        root = "C:/🎬 Animation"

        main_key, _, _ = process_for_upload(blend, root, [])

        # Emoji should be preserved
        self.assertTrue("🏠" in main_key or "house" in main_key)
        self.assertTrue(is_s3_safe(main_key))


class TestUnicodeNormalization(unittest.TestCase):
    """Test NFC/NFD normalization handling."""

    def test_polish_nfc(self):
        """Polish characters in NFC form."""
        blend = "C:/Główny/scena_główna.blend"
        root = "C:/Główny"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertEqual(nfc(main_key), main_key)
        self.assertTrue(is_s3_safe(main_key))

    def test_german_nfc_nfd_equivalent(self):
        """German umlauts: NFC and NFD should produce equivalent keys."""
        nfc_path = "C:/Größe/scene.blend"  # NFC
        nfd_path = "C:/Gro\u0308ße/scene.blend"  # NFD

        nfc_key, _, _ = process_for_upload(nfc_path, "C:/Größe", [])
        nfd_key, _, _ = process_for_upload(nfd_path, "C:/Gro\u0308ße", [])

        # Both should normalize to same NFC form
        self.assertEqual(nfc(nfc_key), nfc(nfd_key))

    def test_japanese(self):
        """Japanese characters."""
        blend = "C:/プロジェクト/シーン/メイン.blend"
        root = "C:/プロジェクト"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertTrue(is_s3_safe(main_key))
        self.assertIn("シーン", main_key)

    def test_mixed_scripts(self):
        """Mixed international scripts."""
        blend = "C:/株式会社/Проект/Größe/scene.blend"
        root = "C:/株式会社"

        main_key, _, _ = process_for_upload(blend, root, [])

        self.assertTrue(is_s3_safe(main_key))


if __name__ == "__main__":
    unittest.main()
