import os
import pathlib
import sys
import unittest

try:
    import mypy.api
    HAS_MYPY = True
except ImportError:
    HAS_MYPY = False

import blender_asset_tracer


@unittest.skipUnless(HAS_MYPY, "mypy not installed")
class MypyRunnerTest(unittest.TestCase):
    def test_run_mypy(self):
        # This test doesn't work with Tox, it raises an AssertionError:
        # /path/to/blender-asset-tracer/.tox/py37/lib/python3.7/site-packages is in the PYTHONPATH.
        # Please change directory so it is not.
        for path in sys.path:
            if "/.tox/" in path and path.endswith("/site-packages"):
                self.skipTest("Mypy doesn't like Tox")

        path = pathlib.Path(blender_asset_tracer.__file__).parent
        # The addon root has an __init__.py and a non-identifier directory
        # name, so mypy's walk-up package detection aborts before analysis.
        # --explicit-package-bases plus a pinned MYPYPATH anchor the package
        # root regardless of the invoking process's cwd.
        old_mypypath = os.environ.get("MYPYPATH")
        os.environ["MYPYPATH"] = str(path.parent)
        try:
            result = mypy.api.run(
                [
                    "--incremental",
                    "--ignore-missing-imports",
                    "--explicit-package-bases",
                    str(path),
                ]
            )
        finally:
            if old_mypypath is None:
                os.environ.pop("MYPYPATH", None)
            else:
                os.environ["MYPYPATH"] = old_mypypath

        stdout, stderr, status = result

        messages = []
        if stderr:
            messages.append(stderr)
        if stdout:
            messages.append(stdout)
        if status:
            messages.append("Mypy failed with status %d" % status)
        if messages and not all(msg.startswith("Success: ") for msg in messages):
            self.fail("\n".join(["Mypy errors:"] + messages))
