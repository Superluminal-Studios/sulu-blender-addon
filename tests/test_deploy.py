import subprocess
import sys
import tempfile
import unittest
import zipimport
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestDeployBuildProvenance(unittest.TestCase):
    def _build(self, *args: str) -> zipfile.ZipFile:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        output = Path(self.temp_dir.name) / "SuperluminalRender.zip"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "deploy.py"),
                "--output",
                str(output),
                *args,
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        archive = zipfile.ZipFile(output)
        self.addCleanup(archive.close)
        return archive

    def test_release_artifact_is_explicitly_marked(self):
        archive = self._build("--version", "1.3.11")

        build_info = archive.read("SuperluminalRender/build_info.py").decode()
        addon_init = archive.read("SuperluminalRender/__init__.py").decode()

        self.assertIn('BUILD_CHANNEL = "release"', build_info)
        self.assertIn('"version": (1, 3, 11)', addon_init)

    def test_local_artifact_remains_a_development_build(self):
        archive = self._build()

        build_info = archive.read("SuperluminalRender/build_info.py").decode()

        self.assertIn('BUILD_CHANNEL = "development"', build_info)

    def test_artifact_excludes_workstation_metadata(self):
        archive = self._build("--version", "1.3.15")

        self.assertFalse(
            any(Path(name).name == ".DS_Store" for name in archive.namelist())
        )

    def test_test_addon_is_isolated_and_defaults_to_test(self):
        source_paths = (
            REPO_ROOT / "__init__.py",
            REPO_ROOT / "environment.py",
            REPO_ROOT / "preferences.py",
        )
        source_before = {path: path.read_bytes() for path in source_paths}
        production = self._build()
        test_addon = self._build("--test-addon")

        production_members = {
            name.removeprefix("SuperluminalRender/"): name
            for name in production.namelist()
        }
        test_members = {
            name.removeprefix("SuperluminalRenderTest/"): name
            for name in test_addon.namelist()
        }
        self.assertEqual(production_members.keys(), test_members.keys())
        self.assertTrue(
            all(name.startswith("SuperluminalRender/") for name in production.namelist())
        )
        self.assertTrue(
            all(
                name.startswith("SuperluminalRenderTest/")
                for name in test_addon.namelist()
            )
        )

        replacements = {
            "__init__.py": (
                b'"name": "Superluminal Render Farm"',
                b'"name": "Superluminal Render Farm Test"',
            ),
            "environment.py": (
                b"DEFAULT_ENVIRONMENT = PRODUCTION_ENVIRONMENT",
                b"DEFAULT_ENVIRONMENT = TEST_ENVIRONMENT",
            ),
            "preferences.py": (
                b'default="production",',
                b'default="test",',
            ),
        }
        for relative_name in production_members:
            production_bytes = production.read(production_members[relative_name])
            test_bytes = test_addon.read(test_members[relative_name])
            if relative_name in replacements:
                old, new = replacements[relative_name]
                self.assertEqual(1, production_bytes.count(old), relative_name)
                self.assertEqual(production_bytes.replace(old, new, 1), test_bytes)
            else:
                self.assertEqual(production_bytes, test_bytes, relative_name)

        self.assertFalse(
            any(
                "__pycache__" in Path(name).parts
                for name in test_addon.namelist()
            )
        )
        self.assertEqual(
            source_before,
            {path: path.read_bytes() for path in source_paths},
        )

    def test_test_addon_archive_has_test_module_import_identity(self):
        archive = self._build("--test-addon")

        importer = zipimport.zipimporter(str(archive.filename))
        spec = importer.find_spec("SuperluminalRenderTest")
        self.assertIsNotNone(spec)
        self.assertEqual("SuperluminalRenderTest", spec.name)
        self.assertIsNotNone(importer.get_code("SuperluminalRenderTest"))
        self.assertIsNone(importer.find_spec("SuperluminalRender"))


if __name__ == "__main__":
    unittest.main()
