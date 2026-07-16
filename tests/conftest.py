"""pytest fixtures and path setup for the Sulu addon test suite."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Ensure addon directory is in path
_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))

# The addon root is itself a Python package whose __init__.py imports bpy.
# When pytest is given a file or subdirectory argument it materializes a
# Package collector for the repo root and would execute that __init__.py.
# Pre-registering the package name keeps pytest from importing it, while the
# __path__ entry lets tests import submodules in their real package context.
_addon_pkg_name = _addon_dir.name
if _addon_pkg_name not in sys.modules:
    _stub = types.ModuleType(_addon_pkg_name)
    _stub.__path__ = [str(_addon_dir)]
    sys.modules[_addon_pkg_name] = _stub

# When the addon directory name is not a Python identifier (e.g. a hyphenated
# checkout dir), pytest cannot resolve the root package name and falls back to
# importing the root __init__.py under the module name "__init__"; that
# fallback name only ever maps to the addon root, so pre-register the stub
# there too.
if not _addon_pkg_name.isidentifier() and "__init__" not in sys.modules:
    sys.modules["__init__"] = sys.modules[_addon_pkg_name]


@pytest.fixture
def addon_dir() -> Path:
    """Return the addon directory path."""
    return _addon_dir


@pytest.fixture
def tests_dir() -> Path:
    """Return the tests directory path."""
    return _tests_dir


@pytest.fixture
def blendfiles_dir() -> Path:
    """Return the BAT blendfiles directory path."""
    return _tests_dir / "bat" / "blendfiles"


@pytest.fixture
def has_blendfiles(blendfiles_dir) -> bool:
    """Check if blendfiles directory exists and has files."""
    if not blendfiles_dir.exists():
        return False
    return len(list(blendfiles_dir.glob("*.blend"))) > 0


@pytest.fixture
def has_bat() -> bool:
    """Check if BAT is available."""
    try:
        from blender_asset_tracer import trace, blendfile  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture
def bat_modules():
    """Return BAT modules if available."""
    try:
        from blender_asset_tracer import trace, blendfile, bpathlib
        from blender_asset_tracer.pack import Packer
        return {
            "trace": trace,
            "blendfile": blendfile,
            "bpathlib": bpathlib,
            "Packer": Packer,
        }
    except ImportError:
        pytest.skip("BAT not available")
