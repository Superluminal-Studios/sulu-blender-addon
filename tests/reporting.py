"""
Test reporting system for Sulu tests.

Generates detailed reports of test runs including:
- Pass/fail status for each test
- Timing information
- Error details and tracebacks
- Summary statistics
- JSON export for CI integration
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from enum import Enum


class TestStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    status: TestStatus
    duration_ms: float = 0
    message: str = ""
    error: str = ""
    traceback: str = ""
    category: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class TestSuiteReport:
    """Report for a test suite run."""
    name: str
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0
    results: List[TestResult] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.FAILED)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.SKIPPED)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.ERROR)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100

    def add_result(self, result: TestResult):
        self.results.append(result)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "skipped": self.skipped,
                "errors": self.errors,
                "success_rate": f"{self.success_rate:.1f}%",
            },
            "environment": self.environment,
            "results": [r.to_dict() for r in self.results],
        }


class TestReporter:
    """
    Test reporter that collects results and generates reports.

    Usage:
        reporter = TestReporter("My Test Suite")
        reporter.start()

        with reporter.test("test_something") as t:
            # run test
            if failed:
                t.fail("reason")

        reporter.finish()
        reporter.write_reports("reports/")
    """

    def __init__(self, suite_name: str):
        self.report = TestSuiteReport(name=suite_name)
        self._current_test: Optional[TestContext] = None

    def start(self):
        """Start the test suite."""
        self.report.started_at = datetime.now().isoformat()
        self.report.environment = {
            "python_version": sys.version,
            "platform": sys.platform,
            "cwd": os.getcwd(),
        }

    def finish(self):
        """Finish the test suite."""
        self.report.finished_at = datetime.now().isoformat()
        # Calculate total duration
        if self.report.started_at and self.report.finished_at:
            start = datetime.fromisoformat(self.report.started_at)
            end = datetime.fromisoformat(self.report.finished_at)
            self.report.duration_ms = (end - start).total_seconds() * 1000

    def test(self, name: str, category: str = "", tags: List[str] = None) -> "TestContext":
        """Context manager for running a test."""
        return TestContext(self, name, category, tags or [])

    def add_result(self, result: TestResult):
        """Add a test result."""
        self.report.add_result(result)

    def write_reports(self, output_dir: str):
        """Write all report formats to output directory."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"test_report_{timestamp}"

        # JSON report
        json_path = output_path / f"{base_name}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.report.to_dict(), f, indent=2, ensure_ascii=False)

        # Text report
        txt_path = output_path / f"{base_name}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(self.generate_text_report())

        # Markdown report
        md_path = output_path / f"{base_name}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.generate_markdown_report())

        return {
            "json": str(json_path),
            "txt": str(txt_path),
            "md": str(md_path),
        }

    def generate_text_report(self) -> str:
        """Generate plain text report."""
        lines = []
        lines.append("=" * 80)
        lines.append(f"  TEST REPORT: {self.report.name}")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"Started:  {self.report.started_at}")
        lines.append(f"Finished: {self.report.finished_at}")
        lines.append(f"Duration: {self.report.duration_ms:.0f}ms")
        lines.append("")
        lines.append("-" * 80)
        lines.append("  SUMMARY")
        lines.append("-" * 80)
        lines.append(f"  Total:   {self.report.total}")
        lines.append(f"  Passed:  {self.report.passed}")
        lines.append(f"  Failed:  {self.report.failed}")
        lines.append(f"  Skipped: {self.report.skipped}")
        lines.append(f"  Errors:  {self.report.errors}")
        lines.append(f"  Success: {self.report.success_rate:.1f}%")
        lines.append("")

        # Group by category
        categories: Dict[str, List[TestResult]] = {}
        for r in self.report.results:
            cat = r.category or "uncategorized"
            categories.setdefault(cat, []).append(r)

        for cat_name, results in sorted(categories.items()):
            lines.append("-" * 80)
            lines.append(f"  CATEGORY: {cat_name.upper()}")
            lines.append("-" * 80)

            for r in results:
                status_icon = {
                    TestStatus.PASSED: "[PASS]",
                    TestStatus.FAILED: "[FAIL]",
                    TestStatus.SKIPPED: "[SKIP]",
                    TestStatus.ERROR: "[ERR!]",
                }[r.status]

                lines.append(f"  {status_icon} {r.name} ({r.duration_ms:.0f}ms)")

                if r.message:
                    lines.append(f"         Message: {r.message}")
                if r.error:
                    lines.append(f"         Error: {r.error}")
                if r.traceback and r.status in (TestStatus.FAILED, TestStatus.ERROR):
                    lines.append("         Traceback:")
                    # Handle both string and list tracebacks
                    tb_text = r.traceback if isinstance(r.traceback, str) else "".join(r.traceback)
                    for tb_line in tb_text.split("\n"):
                        lines.append(f"           {tb_line}")

            lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)

    def generate_markdown_report(self) -> str:
        """Generate Markdown report."""
        lines = []
        lines.append(f"# Test Report: {self.report.name}")
        lines.append("")
        lines.append(f"**Started:** {self.report.started_at}  ")
        lines.append(f"**Finished:** {self.report.finished_at}  ")
        lines.append(f"**Duration:** {self.report.duration_ms:.0f}ms")
        lines.append("")

        # Summary table
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Count |")
        lines.append("|--------|-------|")
        lines.append(f"| Total | {self.report.total} |")
        lines.append(f"| ✅ Passed | {self.report.passed} |")
        lines.append(f"| ❌ Failed | {self.report.failed} |")
        lines.append(f"| ⏭️ Skipped | {self.report.skipped} |")
        lines.append(f"| ⚠️ Errors | {self.report.errors} |")
        lines.append(f"| Success Rate | {self.report.success_rate:.1f}% |")
        lines.append("")

        # Group by category
        categories: Dict[str, List[TestResult]] = {}
        for r in self.report.results:
            cat = r.category or "uncategorized"
            categories.setdefault(cat, []).append(r)

        for cat_name, results in sorted(categories.items()):
            lines.append(f"## {cat_name.title()}")
            lines.append("")

            for r in results:
                status_icon = {
                    TestStatus.PASSED: "✅",
                    TestStatus.FAILED: "❌",
                    TestStatus.SKIPPED: "⏭️",
                    TestStatus.ERROR: "⚠️",
                }[r.status]

                lines.append(f"### {status_icon} {r.name}")
                lines.append("")
                lines.append(f"- **Status:** {r.status.value}")
                lines.append(f"- **Duration:** {r.duration_ms:.0f}ms")

                if r.message:
                    lines.append(f"- **Message:** {r.message}")
                if r.error:
                    lines.append(f"- **Error:** `{r.error}`")
                if r.traceback and r.status in (TestStatus.FAILED, TestStatus.ERROR):
                    lines.append("")
                    lines.append("<details>")
                    lines.append("<summary>Traceback</summary>")
                    lines.append("")
                    lines.append("```")
                    # Handle both string and list tracebacks
                    tb_text = r.traceback if isinstance(r.traceback, str) else "".join(r.traceback)
                    lines.append(tb_text)
                    lines.append("```")
                    lines.append("</details>")

                if r.metadata:
                    lines.append("")
                    lines.append("**Metadata:**")
                    for k, v in r.metadata.items():
                        lines.append(f"- {k}: `{v}`")

                lines.append("")

        return "\n".join(lines)

    def print_summary(self):
        """Print summary to console."""
        print("\n" + "=" * 70)
        print(f"  {self.report.name}")
        print("=" * 70)
        print(f"  Total: {self.report.total} | "
              f"Passed: {self.report.passed} | "
              f"Failed: {self.report.failed} | "
              f"Skipped: {self.report.skipped}")
        print(f"  Success Rate: {self.report.success_rate:.1f}%")
        print("=" * 70)

        if self.report.failed > 0 or self.report.errors > 0:
            print("\n  FAILURES:")
            for r in self.report.results:
                if r.status in (TestStatus.FAILED, TestStatus.ERROR):
                    print(f"    [FAIL] {r.name}: {r.message or r.error}")


class TestContext:
    """Context manager for running a single test."""

    def __init__(self, reporter: TestReporter, name: str, category: str, tags: List[str]):
        self.reporter = reporter
        self.name = name
        self.category = category
        self.tags = tags
        self.start_time: float = 0
        self.result: Optional[TestResult] = None
        self.metadata: Dict[str, Any] = {}

    def __enter__(self) -> "TestContext":
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000

        if self.result:
            # Result already set (pass/fail/skip called)
            self.result.duration_ms = duration_ms
        elif exc_type:
            # Exception occurred
            self.result = TestResult(
                name=self.name,
                status=TestStatus.ERROR,
                duration_ms=duration_ms,
                error=str(exc_val),
                traceback=traceback.format_exc(),
                category=self.category,
                tags=self.tags,
                metadata=self.metadata,
            )
        else:
            # No result set and no exception = passed
            self.result = TestResult(
                name=self.name,
                status=TestStatus.PASSED,
                duration_ms=duration_ms,
                category=self.category,
                tags=self.tags,
                metadata=self.metadata,
            )

        self.reporter.add_result(self.result)
        return True  # Suppress exception

    def passed(self, message: str = ""):
        """Mark test as passed."""
        self.result = TestResult(
            name=self.name,
            status=TestStatus.PASSED,
            message=message,
            category=self.category,
            tags=self.tags,
            metadata=self.metadata,
        )

    def fail(self, message: str, error: str = ""):
        """Mark test as failed."""
        self.result = TestResult(
            name=self.name,
            status=TestStatus.FAILED,
            message=message,
            error=error,
            traceback="".join(traceback.format_stack()),
            category=self.category,
            tags=self.tags,
            metadata=self.metadata,
        )

    def skip(self, reason: str):
        """Mark test as skipped."""
        self.result = TestResult(
            name=self.name,
            status=TestStatus.SKIPPED,
            message=reason,
            category=self.category,
            tags=self.tags,
            metadata=self.metadata,
        )

    def add_metadata(self, key: str, value: Any):
        """Add metadata to the test result."""
        self.metadata[key] = value
