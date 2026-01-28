#!/usr/bin/env python3
"""
Master test runner for Sulu + BAT tests.

Usage:
    python tests/run_tests.py                    # Run all tests
    python tests/run_tests.py --quick            # Run quick tests only (no slow/integration)
    python tests/run_tests.py --category paths   # Run only path tests
    python tests/run_tests.py --category bat     # Run only BAT tests
    python tests/run_tests.py --verbose          # Verbose output
    python tests/run_tests.py --list             # List available tests

Categories:
    paths       - Path handling, drive detection, S3 key tests
    bat         - Blender Asset Tracer core tests
    integration - Combined BAT + Sulu pipeline tests
    fixtures    - Test fixture generation tests

Requirements:
    - Python 3.9+
    - pytest (optional, falls back to unittest)
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path
from datetime import datetime

# Add addon directory to path
_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
sys.path.insert(0, str(_addon_dir))


def discover_tests(category: str = None, verbose: bool = False) -> unittest.TestSuite:
    """Discover tests, optionally filtered by category."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Define test directories by category
    categories = {
        "paths": _tests_dir / "paths",
        "bat": _tests_dir / "bat",
        "integration": _tests_dir / "integration",
    }

    if category:
        if category not in categories:
            print(f"Unknown category: {category}")
            print(f"Available: {', '.join(categories.keys())}")
            sys.exit(1)
        dirs = [categories[category]]
    else:
        dirs = list(categories.values())

    for test_dir in dirs:
        if test_dir.exists():
            discovered = loader.discover(
                start_dir=str(test_dir),
                pattern="test_*.py",
                top_level_dir=str(_addon_dir)
            )
            suite.addTests(discovered)

    return suite


def list_tests():
    """List all available tests."""
    print("\n" + "=" * 78)
    print("  AVAILABLE TESTS")
    print("=" * 78)

    categories = {
        "paths": _tests_dir / "paths",
        "bat": _tests_dir / "bat",
        "integration": _tests_dir / "integration",
    }

    for cat_name, cat_dir in categories.items():
        print(f"\n  [{cat_name.upper()}] {cat_dir}")
        print("  " + "-" * 70)

        if cat_dir.exists():
            for test_file in sorted(cat_dir.glob("test_*.py")):
                print(f"    • {test_file.name}")
        else:
            print("    (directory not found)")


def run_with_pytest(category: str = None, verbose: bool = False, quick: bool = False):
    """Try to run with pytest if available."""
    try:
        import pytest
    except ImportError:
        return False

    args = [str(_tests_dir)]

    if category:
        category_dirs = {
            "paths": str(_tests_dir / "paths"),
            "bat": str(_tests_dir / "bat"),
            "integration": str(_tests_dir / "integration"),
        }
        if category in category_dirs:
            args = [category_dirs[category]]

    if verbose:
        args.append("-v")

    if quick:
        args.extend(["-m", "not slow"])

    # Add color output
    args.append("--color=yes")

    return pytest.main(args) == 0


def run_with_unittest(category: str = None, verbose: bool = False):
    """Run with unittest."""
    suite = discover_tests(category, verbose)

    verbosity = 2 if verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    return result.wasSuccessful()


def write_summary_report(category: str, success: bool, runner: str, quick: bool):
    """Write a summary report to tests/reports/."""
    reports_dir = _tests_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"test_run_{timestamp}.txt"

    lines = [
        "=" * 70,
        "  SULU + BAT TEST RUN SUMMARY",
        "=" * 70,
        "",
        f"  Timestamp: {datetime.now().isoformat()}",
        f"  Runner:    {runner}",
        f"  Category:  {category or 'all'}",
        f"  Quick:     {quick}",
        f"  Result:    {'PASSED' if success else 'FAILED'}",
        "",
        "=" * 70,
        "",
        "Note: For detailed test reports with individual test results,",
        "use the TestReporter class from tests/reporting.py directly,",
        "or run real-world tests with:",
        "  python tests/realworld/test_farm_upload.py --report",
        "",
    ]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n  Report written to: {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run Sulu + BAT test suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python tests/run_tests.py                    # Run all tests
    python tests/run_tests.py --category paths   # Run path tests only
    python tests/run_tests.py --verbose          # Verbose output
    python tests/run_tests.py --quick            # Skip slow tests
    python tests/run_tests.py --list             # List available tests
    python tests/run_tests.py --report           # Write report to tests/reports/

Real-world farm tests (separate script):
    python tests/realworld/test_farm_upload.py --dry-run   # Validate only
    python tests/realworld/test_farm_upload.py             # Actually upload
        """
    )

    parser.add_argument(
        "-c", "--category",
        choices=["paths", "bat", "integration"],
        help="Run only tests in specified category"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "-q", "--quick",
        action="store_true",
        help="Skip slow tests (integration, etc.)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available tests and exit"
    )
    parser.add_argument(
        "--no-pytest",
        action="store_true",
        help="Force use of unittest instead of pytest"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Write test reports to tests/reports/"
    )

    args = parser.parse_args()

    if args.list:
        list_tests()
        return

    print("\n" + "=" * 78)
    print("  SULU + BAT TEST SUITE")
    print("=" * 78)

    if args.category:
        print(f"  Category: {args.category}")
    else:
        print("  Running all tests")

    print("=" * 78 + "\n")

    # Try pytest first, fall back to unittest
    success = None
    runner_used = None

    if not args.no_pytest:
        success = run_with_pytest(args.category, args.verbose, args.quick)
        if success is not False:  # pytest ran (success or failure)
            runner_used = "pytest"
        else:
            # pytest not available, fall back
            print("  (pytest not available, using unittest)\n")
            success = None

    if success is None:
        success = run_with_unittest(args.category, args.verbose)
        runner_used = "unittest"

    # Write report if requested
    if args.report:
        write_summary_report(
            category=args.category,
            success=success,
            runner=runner_used,
            quick=args.quick
        )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
