#!/usr/bin/env python3
"""
Direct test of DiagnosticReport class without the full submit worker.

Usage:
    python tests/test_diagnostic_report_direct.py
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from datetime import datetime

# Add addon dir to path
_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
sys.path.insert(0, str(_addon_dir))


def load_dev_config() -> dict:
    """Load dev_config.json."""
    config_path = _addon_dir / "dev_config.json"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("\n" + "=" * 70)
    print("  DIAGNOSTIC REPORT DIRECT TEST")
    print("=" * 70)

    # Load config
    config = load_dev_config()
    blend_path = config.get("test_blend_path", "")

    if not blend_path or not Path(blend_path).exists():
        print(f"ERROR: test_blend_path not found: {blend_path}")
        sys.exit(1)

    print(f"\n  Blend file: {blend_path}")
    print(f"  Upload type: {config.get('upload_type', 'PROJECT')}")

    # Import our modules using addon package name
    pkg_name = _addon_dir.name.replace("-", "_")

    # Setup the package
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(_addon_dir)]
    sys.modules[pkg_name] = pkg

    diagnostic_report_mod = importlib.import_module(f"{pkg_name}.utils.diagnostic_report")
    DiagnosticReport = diagnostic_report_mod.DiagnosticReport

    bat_utils = importlib.import_module(f"{pkg_name}.utils.bat_utils")
    trace_dependencies = bat_utils.trace_dependencies
    compute_project_root = bat_utils.compute_project_root

    # Create diagnostic report
    reports_dir = _addon_dir / "reports"
    job_id = f"test-{datetime.now().strftime('%H%M%S')}"

    print(f"\n  Creating report with job_id: {job_id}")

    report = DiagnosticReport(
        reports_dir=reports_dir,
        job_id=job_id,
        blend_name=Path(blend_path).stem,
        metadata={
            "source_blend": blend_path,
            "upload_type": config.get("upload_type", "PROJECT"),
            "job_name": f"TEST_{Path(blend_path).stem}",
            "blender_version": "test",
            "addon_version": [0, 0, 0],
            "device_type": "test",
            "start_frame": 1,
            "end_frame": 1,
        },
    )

    print(f"  Report path: {report.get_path()}")

    # Start trace stage
    print("\n  Starting trace stage...")
    report.start_stage("trace")

    # Run trace_dependencies with diagnostic_report
    print("  Tracing dependencies (this may take a while)...")
    try:
        dep_paths, missing_set, unreadable_dict, raw_usages = trace_dependencies(
            Path(blend_path),
            logger=None,  # No visual logging
            hydrate=False,  # Don't hydrate for quick test
            diagnostic_report=report,
        )
        print(f"    Found {len(dep_paths)} dependencies")
        print(f"    Missing: {len(missing_set)}")
        print(f"    Unreadable: {len(unreadable_dict)}")
    except Exception as e:
        print(f"    ERROR during trace: {e}")
        report.set_status("failed")
        report.flush()
        raise

    # Compute project root (excluding missing/unreadable files)
    project_root, same_drive_deps, cross_drive_deps = compute_project_root(
        Path(blend_path), dep_paths,
        missing_files=missing_set,
        unreadable_files=unreadable_dict,
    )
    print(f"    Project root: {project_root}")
    print(f"    Same-drive deps: {len(same_drive_deps)}")
    print(f"    Cross-drive deps: {len(cross_drive_deps)}")

    report.set_metadata("project_root", str(project_root))
    if cross_drive_deps:
        report.add_cross_drive_files([str(p) for p in cross_drive_deps])

    # Complete trace stage
    report.complete_stage("trace")

    # Start pack stage (simulate)
    print("\n  Starting pack stage (simulated)...")
    report.start_stage("pack")

    # Add a few pack entries
    ok_deps = [p for p in dep_paths if p not in missing_set and p not in unreadable_dict]
    for i, dep_path in enumerate(ok_deps[:10]):  # Limit to first 10 for quick test
        try:
            size = dep_path.stat().st_size
        except:
            size = 0
        rel = str(dep_path.relative_to(project_root)) if project_root in dep_path.parents else str(dep_path.name)
        report.add_pack_entry(str(dep_path), rel, file_size=size, status="ok")

    report.complete_stage("pack")

    # Start upload stage (simulated)
    print("\n  Starting upload stage (simulated)...")
    report.start_stage("upload")
    report.start_upload_step(1, 2, "Uploading main .blend")
    report.complete_upload_step(bytes_transferred=1024)
    report.start_upload_step(2, 2, "Uploading dependencies")
    report.complete_upload_step(bytes_transferred=2048)
    report.complete_stage("upload")

    # Finalize
    print("\n  Finalizing report...")
    report.finalize()

    # Read and display the report
    print("\n" + "-" * 70)
    print("  REPORT CONTENTS")
    print("-" * 70)

    with open(report.get_path(), "r", encoding="utf-8") as f:
        report_data = json.load(f)

    print(f"\n  Report version: {report_data.get('report_version')}")
    print(f"  Status: {report_data['metadata']['status']}")
    print(f"  Started: {report_data['metadata']['started_at']}")
    print(f"  Completed: {report_data['metadata']['completed_at']}")

    trace = report_data["stages"]["trace"]
    print(f"\n  Trace stage:")
    print(f"    Started: {trace['started_at']}")
    print(f"    Completed: {trace['completed_at']}")
    print(f"    Entries: {len(trace['entries'])}")
    print(f"    Summary: {trace['summary']}")

    # Show first few trace entries
    if trace["entries"]:
        print(f"\n    First 3 trace entries:")
        for entry in trace["entries"][:3]:
            print(f"      - {entry['block_type']}: {entry['block_name'][:30]}... -> {entry['status']}")

    pack = report_data["stages"]["pack"]
    print(f"\n  Pack stage:")
    print(f"    Entries: {len(pack['entries'])}")
    print(f"    Summary: {pack['summary']}")

    upload = report_data["stages"]["upload"]
    print(f"\n  Upload stage:")
    print(f"    Steps: {len(upload['steps'])}")
    for step in upload["steps"]:
        print(f"      Step {step['step']}/{step['total']}: {step['title']} ({step['bytes_transferred']} bytes)")

    issues = report_data["issues"]
    print(f"\n  Issues:")
    print(f"    Missing files: {len(issues['missing_files'])}")
    print(f"    Unreadable files: {len(issues['unreadable_files'])}")
    print(f"    Cross-drive files: {len(issues['cross_drive_files'])}")

    print("\n" + "=" * 70)
    print(f"  SUCCESS! Report saved to: {report.get_path()}")
    print("=" * 70 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
