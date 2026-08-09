import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
