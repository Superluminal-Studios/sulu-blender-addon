"""Regression guard for independently packaged Blender extensions."""

import unittest

import deploy


class DeployExtensionIsolationTests(unittest.TestCase):
    def test_legacy_release_excludes_independent_extensions(self):
        self.assertIn("extensions", deploy.EXCLUDE)


if __name__ == "__main__":
    unittest.main()
