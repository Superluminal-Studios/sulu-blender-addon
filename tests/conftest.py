"""
pytest configuration for Sulu tests.

This file is automatically loaded by pytest and provides:
- Shared fixtures
- Test markers
- Path setup
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure addon directory is in path
_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
if str(_addon_dir) not in sys.path:
    sys.path.insert(0, str(_addon_dir))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST MARKERS
# ═══════════════════════════════════════════════════════════════════════════════


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "bat: Tests for Blender Asset Tracer"
    )
    config.addinivalue_line(
        "markers", "paths: Tests for path handling and S3 keys"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests (BAT + Sulu)"
    )
    config.addinivalue_line(
        "markers", "unicode: Tests involving unicode/international characters"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take a long time to run"
    )
    config.addinivalue_line(
        "markers", "requires_blendfiles: Tests that need .blend files"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# BAT AVAILABILITY CHECK
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def has_bat() -> bool:
    """Check if BAT is available."""
    try:
        from blender_asset_tracer import trace, blendfile
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
