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


    def test_artifact_ships_runtime_only(self):
        archive = self._build("--version", "1.3.15")
        names = archive.namelist()
        parts = {part for name in names for part in Path(name).parts[1:]}

        # Secrets, workstation metadata, test bootstrap and independently
        # packaged extensions never ship; runtime profiles do.
        for excluded in (
            "session.json",
            ".DS_Store",
            "conftest.py",
            "tests",
            "extensions",
        ):
            self.assertNotIn(excluded, parts)
        self.assertIn("SuperluminalRender/environment.py", names)
        self.assertIn('BUILD_ENVIRONMENT = "production"', archive.read("SuperluminalRender/build_info.py").decode())

    def test_lab_build_fixes_its_service_target_without_changing_source(self):
        original = (REPO_ROOT / "build_info.py").read_bytes()
        archive = self._build("--version", "1.3.15", "--environment", "test")
        self.assertIn('BUILD_ENVIRONMENT = "test"', archive.read("SuperluminalRender/build_info.py").decode())
        self.assertEqual((REPO_ROOT / "build_info.py").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
