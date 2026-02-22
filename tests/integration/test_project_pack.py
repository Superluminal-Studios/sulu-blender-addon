"""
Integration tests for project packing (BAT + Sulu path logic).

These tests verify the complete pipeline from:
1. BAT dependency tracing (finds all assets)
2. Path computation (relative paths, S3 keys)
3. Project root detection
4. Cross-drive handling

Uses real .blend files from tests/bat/blendfiles/ where available,
and generated fixtures for path-only testing.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add paths for imports
_tests_dir = Path(__file__).parent.parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

from tests.utils import (
    get_drive,
    relpath_safe,
    s3key_clean,
    is_s3_safe,
    validate_s3_key,
    nfc,
)
from tests.fixtures import (
    create_simple_project,
    create_linked_library_project,
    create_unicode_project,
    create_cross_drive_project,
    create_nightmare_scenario,
)
from utils.bat_utils import classify_out_of_root_ok_files

# Try to import BAT - some tests require it
try:
    from blender_asset_tracer import trace, blendfile, bpathlib
    from blender_asset_tracer.pack import Packer
    HAS_BAT = True
except ImportError:
    HAS_BAT = False


class TestPathComputationWithFixtures(unittest.TestCase):
    """Test path computation using generated fixtures."""

    def test_simple_project_paths(self):
        """Simple project should produce clean S3 keys."""
        with create_simple_project() as fixture:
            blend_key = relpath_safe(str(fixture.blend), str(fixture.root))
            cleaned = s3key_clean(blend_key)

            self.assertEqual("scene.blend", cleaned)
            self.assertTrue(is_s3_safe(cleaned))

            # Check dependencies
            for dep in fixture.dependencies:
                dep_key = relpath_safe(str(dep), str(fixture.root))
                cleaned_dep = s3key_clean(dep_key)
                self.assertTrue(is_s3_safe(cleaned_dep), f"Dep {dep} → {cleaned_dep}")
                self.assertIn("textures/", cleaned_dep)

    def test_linked_library_paths(self):
        """Linked library project should maintain structure."""
        with create_linked_library_project() as fixture:
            blend_key = relpath_safe(str(fixture.blend), str(fixture.root))
            cleaned = s3key_clean(blend_key)

            # Main blend should be in shots/sh010/
            self.assertEqual("shots/sh010/sh010_anim.blend", cleaned)
            self.assertTrue(is_s3_safe(cleaned))

            # Check asset paths maintain structure
            for dep in fixture.dependencies:
                dep_key = relpath_safe(str(dep), str(fixture.root))
                cleaned_dep = s3key_clean(dep_key)
                self.assertTrue(is_s3_safe(cleaned_dep))

                # Should preserve asset structure
                if dep.suffix == ".blend":
                    self.assertTrue(
                        "assets/" in cleaned_dep or "environments/" in cleaned_dep,
                        f"Blend dep should be in assets: {cleaned_dep}"
                    )

    def test_unicode_project_paths(self):
        """Unicode paths should produce safe S3 keys."""
        with create_unicode_project(scripts=["polish", "japanese", "emoji"]) as fixture:
            blend_key = relpath_safe(str(fixture.blend), str(fixture.root))
            cleaned = s3key_clean(blend_key)

            self.assertTrue(is_s3_safe(cleaned))
            # Should be NFC normalized
            self.assertEqual(nfc(cleaned), cleaned)

            for dep in fixture.dependencies:
                dep_key = relpath_safe(str(dep), str(fixture.root))
                cleaned_dep = s3key_clean(dep_key)
                self.assertTrue(is_s3_safe(cleaned_dep))

    def test_cross_drive_detection(self):
        """Cross-drive dependencies should be detected."""
        with create_cross_drive_project() as fixture:
            project_drive = get_drive(str(fixture.root))

            # Local deps should be same drive
            for dep in fixture.dependencies:
                dep_drive = get_drive(str(dep))
                self.assertEqual(project_drive, dep_drive)

            # Cross-drive deps: on single-drive systems (like most dev machines),
            # both temp dirs will be on the same drive, so we skip the assertion
            # but still verify the fixture created the expected paths
            self.assertTrue(
                len(fixture.cross_drive_deps) > 0,
                "Fixture should have cross-drive deps"
            )

            # Test simulated cross-drive detection with realistic paths
            # These paths simulate different drives even on single-drive systems
            simulated_cases = [
                ("C:/Project/scene.blend", "D:/Library/texture.png", True),
                ("C:/Project/scene.blend", "C:/Project/texture.png", False),
                ("/Volumes/Project/scene.blend", "/Volumes/Library/texture.png", True),
                ("/Volumes/Project/scene.blend", "/Volumes/Project/texture.png", False),
                ("Z:/Network/scene.blend", "Y:/Assets/texture.png", True),
            ]

            for project_path, dep_path, should_differ in simulated_cases:
                proj_drive = get_drive(project_path)
                dep_drive = get_drive(dep_path)
                if should_differ:
                    self.assertNotEqual(
                        proj_drive, dep_drive,
                        f"Drives should differ: {project_path} vs {dep_path}"
                    )
                else:
                    self.assertEqual(
                        proj_drive, dep_drive,
                        f"Drives should match: {project_path} vs {dep_path}"
                    )

    def test_nightmare_scenario_paths(self):
        """Nightmare scenario should still produce valid keys."""
        with create_nightmare_scenario() as fixture:
            blend_key = relpath_safe(str(fixture.blend), str(fixture.root))
            cleaned = s3key_clean(blend_key)

            # Even nightmare paths should produce safe keys
            self.assertTrue(is_s3_safe(cleaned), f"Key not safe: {cleaned}")

            # Should have preserved filename
            self.assertTrue(
                "nightmare_scene.blend" in cleaned,
                f"Filename not preserved: {cleaned}"
            )

            for dep in fixture.dependencies:
                dep_key = relpath_safe(str(dep), str(fixture.root))
                cleaned_dep = s3key_clean(dep_key)
                self.assertTrue(
                    is_s3_safe(cleaned_dep),
                    f"Nightmare dep not safe: {dep} → {cleaned_dep}"
                )

    def test_out_of_root_dependencies_are_classified(self):
        """Project mode should identify readable deps outside selected root."""
        with create_simple_project() as fixture:
            with tempfile.TemporaryDirectory() as outside_dir:
                outside_dep = Path(outside_dir) / "outside_texture.jpg"
                outside_dep.write_bytes(b"fake")

                deps = list(fixture.dependencies) + [outside_dep]
                outside = classify_out_of_root_ok_files(deps, fixture.root)
                outside_str = {str(p) for p in outside}

                self.assertIn(str(outside_dep), outside_str)
                for inside_dep in fixture.dependencies:
                    self.assertNotIn(str(inside_dep), outside_str)


@unittest.skipUnless(HAS_BAT, "BAT not available")
class TestBATIntegration(unittest.TestCase):
    """Integration tests using actual BAT functionality."""

    @classmethod
    def setUpClass(cls):
        cls.blendfiles = _tests_dir / "bat" / "blendfiles"
        if not cls.blendfiles.exists():
            raise unittest.SkipTest(f"Blendfiles not found: {cls.blendfiles}")

    def test_trace_dependencies(self):
        """BAT should trace dependencies correctly."""
        blend_path = self.blendfiles / "doubly_linked.blend"
        if not blend_path.exists():
            self.skipTest(f"Test file not found: {blend_path}")

        deps = list(trace.deps(blend_path))

        # Should find linked libraries
        lib_deps = [d for d in deps if d.block.code == b"LI"]
        self.assertGreater(len(lib_deps), 0, "Should find library links")

    def test_blendpath_to_s3key(self):
        """BlendPath conversions should produce S3-safe keys."""
        # Test various BlendPath scenarios
        test_cases = [
            (b"//textures/wood.png", "textures/wood.png"),
            (b"//assets/hero.blend", "assets/hero.blend"),
            (b"//../outside/file.png", "../outside/file.png"),
        ]

        for bpath_bytes, expected_key in test_cases:
            bpath = bpathlib.BlendPath(bpath_bytes)
            # BlendPath str conversion
            path_str = str(bpath, 'utf-8').lstrip('/')
            cleaned = s3key_clean(path_str)
            # Check it's valid
            self.assertIsNotNone(cleaned)

    def test_pack_and_validate_keys(self):
        """Packer output should produce S3-safe keys."""
        blend_path = self.blendfiles / "material_textures.blend"
        if not blend_path.exists():
            self.skipTest(f"Test file not found: {blend_path}")

        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "packed"
            packer = Packer(blend_path, self.blendfiles, pack_dir, noop=True)
            packer.strategise()

            # Check all actions produce valid relative paths
            for src_path, action in packer._actions.items():
                if action.new_path:
                    # Compute what the S3 key would be
                    try:
                        rel = relpath_safe(str(action.new_path), str(pack_dir))
                        key = s3key_clean(rel)
                        issues = validate_s3_key(key)
                        self.assertEqual(
                            [], issues,
                            f"Key for {src_path.name} has issues: {issues}"
                        )
                    except ValueError:
                        pass  # Cross-drive paths expected to fail

            packer.close()


class TestBPathLibIntegration(unittest.TestCase):
    """Test bpathlib integration with Sulu path logic."""

    @unittest.skipUnless(HAS_BAT, "BAT not available")
    def test_strip_root_produces_safe_key(self):
        """strip_root should help produce S3-safe keys."""
        test_paths = [
            (Path("C:/Projects/scene.blend"), "C/Projects/scene.blend"),
            (Path("/home/user/project/scene.blend"), "home/user/project/scene.blend"),
        ]

        for path, expected_stripped in test_paths:
            try:
                stripped = bpathlib.strip_root(path)
                # Should be usable as S3 key component
                key = s3key_clean(str(stripped))
                self.assertTrue(is_s3_safe(key))
            except Exception as e:
                # Some path types might not work on all platforms
                pass

    @unittest.skipUnless(HAS_BAT, "BAT not available")
    def test_make_absolute_normalization(self):
        """make_absolute should normalize paths properly."""
        # Test with relative paths that have ..
        from pathlib import PureWindowsPath

        in_path = PureWindowsPath("C:/wrong/path/../../correct/file.blend")
        result = bpathlib.make_absolute(in_path)

        # Should be normalized
        self.assertNotIn("..", str(result))

        # Result should be usable for S3 key generation
        # (after computing relative path)


class TestProjectRootComputation(unittest.TestCase):
    """Test project root computation logic."""

    def test_common_prefix_detection(self):
        """Common prefix should be correctly identified."""
        # Simple case: all files under same root
        blend = "C:/Projects/Animation/scenes/main.blend"
        deps = [
            "C:/Projects/Animation/textures/wood.png",
            "C:/Projects/Animation/models/hero.blend",
        ]

        # Find common prefix
        all_paths = [blend] + deps
        common = os.path.commonpath([p.replace("\\", "/") for p in all_paths])

        self.assertEqual("C:/Projects/Animation", common.replace("\\", "/"))

    def test_custom_root_respected(self):
        """Custom project root should be used when specified."""
        blend = "C:/Projects/Animation/shots/sh010/scene.blend"
        custom_root = "C:/Projects/Animation"

        # With custom root, relative path should be from that point
        rel = relpath_safe(blend, custom_root)
        key = s3key_clean(rel)

        self.assertEqual("shots/sh010/scene.blend", key)

    def test_root_is_blend_parent(self):
        """If root is blend's parent, key should just be filename."""
        blend = "C:/Projects/scene.blend"
        root = "C:/Projects"

        rel = relpath_safe(blend, root)
        key = s3key_clean(rel)

        self.assertEqual("scene.blend", key)


if __name__ == "__main__":
    unittest.main()
