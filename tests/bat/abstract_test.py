# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2019, Blender Foundation - Sybren A. Stüvel
"""
Abstract base classes for BAT tests.

These provide setup/teardown for blendfile tests and common utilities.
"""

import logging
import pathlib
import sys
import unittest
from typing import Optional

# Add parent dirs to path for imports
_tests_dir = pathlib.Path(__file__).parent.parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

from blender_asset_tracer import blendfile

logging.basicConfig(
    format="%(asctime)-15s %(levelname)8s %(name)s %(message)s", level=logging.INFO
)


class AbstractBlendFileTest(unittest.TestCase):
    """
    Base class for tests that work with .blend files.

    Provides:
    - self.blendfiles: Path to the blendfiles directory
    - self.bf: BlendFile instance (set to None in setUp, closed in tearDown)
    - Automatic cleanup of cached blendfiles
    """

    blendfiles: pathlib.Path
    bf: Optional[blendfile.BlendFile]

    @classmethod
    def setUpClass(cls):
        # blendfiles directory is in tests/bat/blendfiles/
        cls.blendfiles = pathlib.Path(__file__).parent / "blendfiles"
        if not cls.blendfiles.exists():
            raise RuntimeError(
                f"Test blendfiles directory not found: {cls.blendfiles}\n"
                "Make sure to run tests from the addon root directory."
            )

    def setUp(self):
        self.bf = None

    def tearDown(self):
        if self.bf is not None:
            self.bf.close()
        self.bf = None
        blendfile.close_all_cached()
