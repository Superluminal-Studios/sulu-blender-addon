"""Tests for tests/run_tests.py pytest-vs-unittest fallback behavior.

Background: the wrapper previously returned False both when pytest was missing
and when pytest ran but failed, so a real pytest failure would fall through to
the unittest fallback and could hide a broken test suite. The wrapper now
returns three distinct states.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import run_tests  # noqa: E402


class RunPytestThreeStateTests(unittest.TestCase):
    def test_returns_unavailable_when_pytest_missing(self):
        # Simulate "import pytest" raising ImportError.
        with mock.patch.dict(sys.modules, {"pytest": None}):
            result = run_tests.run_with_pytest(category="paths", verbose=False, quick=True)
        self.assertEqual(result, run_tests.PYTEST_UNAVAILABLE)

    def test_returns_passed_when_pytest_exits_zero(self):
        fake_pytest = mock.MagicMock()
        fake_pytest.main.return_value = 0
        with mock.patch.dict(sys.modules, {"pytest": fake_pytest}):
            result = run_tests.run_with_pytest(category="paths", verbose=False, quick=True)
        self.assertEqual(result, run_tests.PYTEST_PASSED)

    def test_returns_failed_when_pytest_exits_nonzero(self):
        fake_pytest = mock.MagicMock()
        fake_pytest.main.return_value = 1
        with mock.patch.dict(sys.modules, {"pytest": fake_pytest}):
            result = run_tests.run_with_pytest(category="paths", verbose=False, quick=True)
        self.assertEqual(result, run_tests.PYTEST_FAILED)


if __name__ == "__main__":
    unittest.main()
