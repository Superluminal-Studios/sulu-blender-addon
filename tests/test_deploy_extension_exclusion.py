"""Keep separate Blender extension sources out of the render-farm add-on ZIP."""

import shutil
import unittest

import deploy


class DeployExtensionIsolationTests(unittest.TestCase):
    def test_release_excludes_separate_extension_sources(self):
        self.assertIn("extensions", deploy.EXCLUDE)
        ignored = shutil.ignore_patterns(*deploy.EXCLUDE)(
            "/tmp/addon-source",
            ["extensions", "operators.py"],
        )
        self.assertIn("extensions", ignored)
        self.assertNotIn("operators.py", ignored)


if __name__ == "__main__":
    unittest.main()
