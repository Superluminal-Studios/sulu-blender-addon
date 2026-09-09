"""Regression guard for independently packaged Blender extensions."""

import unittest

import deploy


class DeployExtensionIsolationTests(unittest.TestCase):
    def test_legacy_release_excludes_independent_extensions(self):
        self.assertIn("extensions", deploy.EXCLUDE)

    def test_release_excludes_test_bootstrap_but_includes_runtime_profiles(self):
        self.assertIn("conftest.py", deploy.EXCLUDE)
        self.assertNotIn("environment.py", deploy.EXCLUDE)


if __name__ == "__main__":
    unittest.main()
