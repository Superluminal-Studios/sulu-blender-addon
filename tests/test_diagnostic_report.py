#!/usr/bin/env python3
"""
Quick test script for the diagnostic report feature.

Uses dev_config.json to run the submit worker in test mode and verify
that the diagnostic report is generated correctly.

Usage:
    python tests/test_diagnostic_report.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# Add addon dir to path
_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent
sys.path.insert(0, str(_addon_dir))


def load_dev_config() -> dict:
    """Load dev_config.json."""
    config_path = _addon_dir / "dev_config.json"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        print("Copy dev_config.example.json to dev_config.json and fill in your paths.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("\n" + "=" * 70)
    print("  DIAGNOSTIC REPORT TEST")
    print("=" * 70)

    # Load config
    config = load_dev_config()
    blend_path = config.get("test_blend_path", "")

    if not blend_path or not Path(blend_path).exists():
        print(f"ERROR: test_blend_path not found: {blend_path}")
        sys.exit(1)

    print(f"\n  Blend file: {blend_path}")
    print(f"  Upload type: {config.get('upload_type', 'PROJECT')}")
    print(f"  Test mode: {config.get('dry_run', True)}")
    print(f"  No submit: {config.get('no_submit', True)}")

    # Load credentials from session.json
    from storage import Storage
    Storage.load()

    token = Storage.data.get("user_token", "")
    if not token:
        print("\nERROR: No user_token in session.json - please log in first")
        sys.exit(1)

    projects = Storage.data.get("projects", [])
    if not projects:
        print("\nERROR: No projects in session.json - please fetch projects first")
        sys.exit(1)

    project = projects[0]
    org_id = Storage.data.get("org_id", "")

    from constants import POCKETBASE_URL, FARM_IP

    # Build handoff JSON
    job_id = str(uuid.uuid4())
    handoff = {
        "addon_dir": str(_addon_dir),
        "addon_version": [0, 0, 0],
        "packed_addons_path": "",
        "packed_addons": [],
        "job_id": job_id,
        "device_type": "GPU",
        "blend_path": str(blend_path).replace("\\", "/"),
        "temp_blend_path": str(Path(tempfile.gettempdir()) / Path(blend_path).name),
        "use_project_upload": config.get("upload_type", "PROJECT") == "PROJECT",
        "automatic_project_path": config.get("automatic_project_path", True),
        "custom_project_path": config.get("custom_project_path", ""),
        "job_name": f"DIAG_TEST_{Path(blend_path).stem}",
        "image_format": "PNG",
        "use_scene_image_format": False,
        "start_frame": 1,
        "end_frame": 1,
        "frame_stepping_size": 1,
        "render_engine": "CYCLES",
        "blender_version": "blender42",
        "ignore_errors": False,
        "pocketbase_url": POCKETBASE_URL,
        "user_token": token,
        "project": project,
        "use_bserver": False,
        "use_async_upload": True,
        "farm_url": f"{FARM_IP}/farm/{org_id}/api/",
        # Test mode flags
        "test_mode": config.get("dry_run", True),
        "no_submit": config.get("no_submit", True),
    }

    # Write handoff
    tmp_json = Path(tempfile.gettempdir()) / f"sulu_diag_test_{job_id[:8]}.json"
    tmp_json.write_text(json.dumps(handoff, indent=2), encoding="utf-8")

    print(f"\n  Handoff: {tmp_json}")
    print(f"  Job ID: {job_id}")

    # Run submit worker
    worker = _addon_dir / "transfers" / "submit" / "submit_worker.py"

    print("\n" + "-" * 70)
    print("  Running submit worker...")
    print("-" * 70 + "\n")

    # Run interactively so user can see output and respond to prompts
    result = subprocess.run(
        [sys.executable, "-u", str(worker), str(tmp_json)],
        cwd=str(_addon_dir),
    )

    print("\n" + "-" * 70)

    # Check for report
    reports_dir = _addon_dir / "reports"
    if reports_dir.exists():
        reports = sorted(reports_dir.glob("report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if reports:
            latest = reports[0]
            print(f"\n  Latest report: {latest}")
            print(f"  Report size: {latest.stat().st_size} bytes")

            # Show report summary
            with open(latest, "r", encoding="utf-8") as f:
                report_data = json.load(f)

            print(f"\n  Report version: {report_data.get('report_version', 'unknown')}")
            print(f"  Status: {report_data.get('metadata', {}).get('status', 'unknown')}")

            stages = report_data.get("stages", {})
            trace = stages.get("trace", {})
            pack = stages.get("pack", {})

            trace_summary = trace.get("summary", {})
            print(f"\n  Trace summary:")
            print(f"    Total: {trace_summary.get('total', 0)}")
            print(f"    OK: {trace_summary.get('ok', 0)}")
            print(f"    Missing: {trace_summary.get('missing', 0)}")
            print(f"    Unreadable: {trace_summary.get('unreadable', 0)}")

            pack_summary = pack.get("summary", {})
            print(f"\n  Pack summary:")
            print(f"    Files packed: {pack_summary.get('files_packed', 0)}")
            print(f"    Total size: {pack_summary.get('total_size', 0)} bytes")

            issues = report_data.get("issues", {})
            print(f"\n  Issues:")
            print(f"    Missing files: {len(issues.get('missing_files', []))}")
            print(f"    Unreadable files: {len(issues.get('unreadable_files', {}))}")
            print(f"    Cross-drive files: {len(issues.get('cross_drive_files', []))}")

        else:
            print("\n  No reports found in reports/")
    else:
        print("\n  reports/ directory not created")

    print("\n" + "=" * 70)
    print(f"  Worker exit code: {result.returncode}")
    print("=" * 70 + "\n")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
