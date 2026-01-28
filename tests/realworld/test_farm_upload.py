#!/usr/bin/env python3
"""
Real-world farm upload tests.

IMPORTANT: These tests actually upload to the Superluminal render farm!
They use your session.json credentials and will create real jobs.

Usage:
    python tests/realworld/test_farm_upload.py --dry-run    # Validate without uploading
    python tests/realworld/test_farm_upload.py              # Actually upload (creates jobs!)
    python tests/realworld/test_farm_upload.py --report     # Write detailed report

What to check on the farm after running:
1. Job appears in the job list with correct name
2. All files uploaded (no missing textures/dependencies)
3. Path structure is correct (no drive letters, no temp dirs)
4. Renders start without errors
5. Output matches expected format

Test scenarios:
- Simple single-file upload
- Project with textures
- Project with Unicode paths
- Project with linked libraries
- Large cache files
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add addon dir to path
_tests_dir = Path(__file__).parent.parent
_addon_dir = _tests_dir.parent
sys.path.insert(0, str(_addon_dir))

from tests.reporting import TestReporter, TestStatus
from tests.utils import (
    get_drive,
    s3key_clean,
    is_s3_safe,
    validate_s3_key,
    nfc,
)

# Import storage for credentials
from storage import Storage
from constants import POCKETBASE_URL, FARM_IP


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FarmTestConfig:
    """Configuration for farm upload tests."""
    dry_run: bool = True
    write_report: bool = True
    report_dir: str = "tests/reports"
    test_blend_dir: str = "tests/bat/blendfiles"

    # Job settings for test uploads
    test_job_prefix: str = "SULU_TEST_"
    frame_start: int = 1
    frame_end: int = 1  # Single frame for quick tests
    device_type: str = "GPU"
    blender_version: str = "blender42"  # Format: "blender{major}{minor}" lowercase

    # Timeout for waiting on uploads (seconds)
    upload_timeout: int = 300


@dataclass
class UploadResult:
    """Result of an upload test."""
    success: bool
    job_id: str = ""
    job_name: str = ""
    files_uploaded: int = 0
    upload_time_sec: float = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    s3_keys: List[str] = field(default_factory=list)
    manifest: Dict[str, Any] = field(default_factory=dict)

    # What to verify on farm
    farm_verification: Dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# CREDENTIAL AND AUTH CHECKS
# ═══════════════════════════════════════════════════════════════════════════════


def load_credentials() -> Tuple[bool, str, Dict]:
    """
    Load credentials from session.json.

    Returns: (success, error_message, credentials_dict)
    """
    try:
        Storage.load()

        token = Storage.data.get("user_token", "")
        org_id = Storage.data.get("org_id", "")
        user_key = Storage.data.get("user_key", "")
        projects = Storage.data.get("projects", [])

        if not token:
            return False, "No user_token in session.json - please log in first", {}

        if not org_id:
            return False, "No org_id in session.json - please log in first", {}

        if not projects:
            return False, "No projects in session.json - please fetch projects first", {}

        return True, "", {
            "token": token,
            "org_id": org_id,
            "user_key": user_key,
            "projects": projects,
        }

    except Exception as e:
        return False, f"Failed to load session.json: {e}", {}


def verify_auth(credentials: Dict) -> Tuple[bool, str]:
    """
    Verify credentials are valid by making a test API call.

    Returns: (success, error_message)
    """
    try:
        # Direct API call since pocketbase_auth uses relative imports
        # that don't work outside the addon package context
        import requests

        token = credentials.get("token", "")
        if not token:
            return False, "No token in credentials"

        headers = {"Authorization": token}
        response = requests.get(
            f"{POCKETBASE_URL}/api/collections/projects/records",
            headers=headers,
            timeout=30
        )

        if response.status_code == 401:
            return False, "Authentication failed - token may be expired, please re-login"

        if response.status_code != 200:
            return False, f"API error: {response.status_code}"

        return True, ""

    except Exception as e:
        return False, f"Auth verification failed: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST BLEND FILE CREATION
# ═══════════════════════════════════════════════════════════════════════════════


def find_test_blend_files(config: FarmTestConfig) -> List[Path]:
    """Find available test .blend files."""
    blend_dir = _addon_dir / config.test_blend_dir
    if not blend_dir.exists():
        return []

    blends = list(blend_dir.glob("*.blend"))
    # Filter out compressed ones that need zstandard
    return [b for b in blends if "compressed" not in b.name.lower()]


def get_test_scenarios(config: FarmTestConfig) -> List[Dict]:
    """
    Get test scenarios to run.

    Each scenario defines:
    - name: Test name
    - blend_file: Path to blend file (or None to create temp)
    - expected_deps: Expected dependency patterns
    - farm_checks: What to verify on the farm
    """
    blendfiles = _addon_dir / config.test_blend_dir

    scenarios = []

    # Scenario 1: Simple file (no dependencies)
    basic_blend = blendfiles / "basic_file.blend"
    if basic_blend.exists():
        scenarios.append({
            "name": "simple_no_deps",
            "description": "Simple .blend with no external dependencies",
            "blend_file": basic_blend,
            "expected_deps": [],
            "farm_checks": {
                "job_appears": "Job should appear in job list",
                "no_missing_files": "No missing file errors in logs",
                "render_starts": "Render should start without errors",
            }
        })

    # Scenario 2: Material textures
    tex_blend = blendfiles / "material_textures.blend"
    if tex_blend.exists():
        scenarios.append({
            "name": "with_textures",
            "description": "Scene with external texture images",
            "blend_file": tex_blend,
            "expected_deps": ["textures/Bricks/*.jpg"],
            "farm_checks": {
                "job_appears": "Job should appear in job list",
                "textures_uploaded": "Texture files should be in S3",
                "textures_found": "Render should find all textures (no pink materials)",
                "render_completes": "Render should complete without texture errors",
            }
        })

    # Scenario 3: Linked libraries
    linked_blend = blendfiles / "doubly_linked.blend"
    if linked_blend.exists():
        scenarios.append({
            "name": "linked_libraries",
            "description": "Scene with linked .blend libraries",
            "blend_file": linked_blend,
            "expected_deps": ["linked_cube.blend", "basic_file.blend", "material_textures.blend"],
            "farm_checks": {
                "job_appears": "Job should appear in job list",
                "libs_uploaded": "All linked .blend files should be uploaded",
                "libs_resolved": "Library links should resolve correctly on farm",
                "render_completes": "Render should complete with all linked data",
            }
        })

    # Scenario 4: Unicode filename
    unicode_blend = blendfiles / "basic_file_ñønæščii.blend"
    if unicode_blend.exists():
        scenarios.append({
            "name": "unicode_filename",
            "description": "File with Unicode characters in name",
            "blend_file": unicode_blend,
            "expected_deps": [],
            "farm_checks": {
                "job_appears": "Job should appear with correct name",
                "filename_preserved": "Unicode filename should be preserved",
                "render_completes": "Render should work despite Unicode name",
            }
        })

    # Scenario 5: Image sequences (if sequencer blend exists)
    seq_blend = blendfiles / "image_sequencer.blend"
    if seq_blend.exists():
        scenarios.append({
            "name": "image_sequence",
            "description": "Scene with image sequence in VSE",
            "blend_file": seq_blend,
            "expected_deps": ["imgseq/*.png"],
            "farm_checks": {
                "job_appears": "Job should appear",
                "sequence_uploaded": "All sequence frames should be uploaded",
                "sequence_plays": "VSE should play sequence correctly",
            }
        })

    return scenarios


# ═══════════════════════════════════════════════════════════════════════════════
# UPLOAD SIMULATION (DRY RUN)
# ═══════════════════════════════════════════════════════════════════════════════


def simulate_upload(
    blend_path: Path,
    config: FarmTestConfig,
    credentials: Dict,
) -> UploadResult:
    """
    Simulate upload without actually uploading.

    Validates:
    - Path resolution
    - S3 key generation
    - Dependency discovery
    """
    result = UploadResult(success=True)
    result.job_id = str(uuid.uuid4())[:8]
    result.job_name = f"{config.test_job_prefix}{blend_path.stem}"

    try:
        # Import BAT for dependency tracing
        from blender_asset_tracer import trace

        # Trace dependencies
        deps = list(trace.deps(blend_path))
        result.files_uploaded = len(deps) + 1  # deps + main blend

        # Generate S3 keys
        project_root = blend_path.parent
        main_key = s3key_clean(blend_path.name)
        result.s3_keys.append(main_key)

        # Validate main key
        issues = validate_s3_key(main_key)
        if issues:
            result.warnings.append(f"Main blend key issues: {issues}")

        # Process dependencies
        for dep in deps:
            try:
                dep_path = dep.abspath
                rel_path = dep_path.relative_to(project_root)
                dep_key = s3key_clean(str(rel_path))

                # Validate dep key
                dep_issues = validate_s3_key(dep_key)
                if dep_issues:
                    result.warnings.append(f"Dep {dep_path.name} key issues: {dep_issues}")
                else:
                    result.s3_keys.append(dep_key)

            except ValueError:
                # Outside project root
                result.warnings.append(f"Dep outside project: {dep.asset_path}")

        # Build manifest preview
        result.manifest = {
            "job_id": result.job_id,
            "job_name": result.job_name,
            "blend_file": main_key,
            "dependencies": result.s3_keys[1:],
            "total_files": result.files_uploaded,
        }

        # Verification checklist
        result.farm_verification = {
            "1_job_created": f"Job '{result.job_name}' should appear in job list",
            "2_files_count": f"Should have {result.files_uploaded} files uploaded",
            "3_no_absolute": "No S3 keys should have absolute paths or drive letters",
            "4_no_temp": "No S3 keys should contain temp directory paths",
        }

    except Exception as e:
        result.success = False
        result.errors.append(str(e))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ACTUAL UPLOAD (REAL RUN)
# ═══════════════════════════════════════════════════════════════════════════════


def perform_upload(
    blend_path: Path,
    config: FarmTestConfig,
    credentials: Dict,
) -> UploadResult:
    """
    Actually perform upload to the farm.

    WARNING: This creates real jobs on the farm!
    """
    result = UploadResult(success=True)
    result.job_id = str(uuid.uuid4())
    result.job_name = f"{config.test_job_prefix}{blend_path.stem}_{result.job_id[:8]}"

    start_time = time.time()

    try:
        # Select first project
        project = credentials["projects"][0] if credentials["projects"] else {}
        project_name = project.get("name", "Test")

        # Build handoff JSON (similar to submit_operator.py)
        handoff = {
            "addon_dir": str(_addon_dir),
            "addon_version": (0, 0, 0),  # Tuple format expected by worker
            "packed_addons_path": tempfile.mkdtemp(prefix="test_addons_"),
            "packed_addons": [],
            "job_id": result.job_id,
            "device_type": config.device_type,
            "blend_path": str(blend_path).replace("\\", "/"),
            "temp_blend_path": str(Path(tempfile.gettempdir()) / blend_path.name),
            "use_project_upload": True,  # Use PROJECT mode for testing
            "automatic_project_path": True,
            "custom_project_path": "",
            "job_name": result.job_name,
            "image_format": "PNG",
            "use_scene_image_format": False,
            "start_frame": config.frame_start,
            "end_frame": config.frame_end,
            "frame_stepping_size": 1,
            "render_engine": "CYCLES",
            "blender_version": config.blender_version,
            "ignore_errors": True,  # Skip prompts for missing files in automated tests
            "pocketbase_url": POCKETBASE_URL,
            "user_token": credentials["token"],
            "project": project,
            "use_bserver": False,
            "use_async_upload": True,
            "farm_url": f"{FARM_IP}/farm/{credentials['org_id']}/api/",
        }

        # Write handoff
        tmp_json = Path(tempfile.gettempdir()) / f"sulu_test_{result.job_id}.json"
        tmp_json.write_text(json.dumps(handoff), encoding="utf-8")

        # Run submit worker
        worker = _addon_dir / "transfers" / "submit" / "submit_worker.py"
        cmd = [sys.executable, "-u", str(worker), str(tmp_json)]

        # Pipe "n\n" to stdin to auto-answer "Open job in browser?" prompt
        proc = subprocess.run(
            cmd,
            input="n\n",  # Auto-answer browser prompt with "no"
            capture_output=True,
            text=True,
            timeout=config.upload_timeout,
        )

        result.upload_time_sec = time.time() - start_time

        if proc.returncode != 0:
            result.success = False
            result.errors.append(f"Worker failed with code {proc.returncode}")
            result.errors.append(proc.stderr[-2000:] if proc.stderr else "No stderr")
        else:
            # Parse output for upload info
            output = proc.stdout
            if "Upload complete" in output or "SUCCESS" in output:
                result.success = True
            else:
                result.warnings.append("Could not confirm upload success in output")

        # Set verification checklist
        result.farm_verification = {
            "1_check_job_list": f"Go to farm dashboard, verify job '{result.job_name}' appears",
            "2_check_status": "Job status should be 'queued' or 'rendering'",
            "3_check_files": "Click job to verify all files uploaded correctly",
            "4_check_render": f"Wait for frame {config.frame_start} to render",
            "5_check_output": "Verify output image looks correct (no pink textures, no missing objects)",
        }

    except subprocess.TimeoutExpired:
        result.success = False
        result.errors.append(f"Upload timed out after {config.upload_timeout}s")

    except Exception as e:
        result.success = False
        result.errors.append(str(e))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════════


def run_tests(config: FarmTestConfig) -> TestReporter:
    """Run all farm upload tests."""
    reporter = TestReporter("Farm Upload Tests")
    reporter.start()

    # Check credentials
    with reporter.test("check_credentials", category="setup") as t:
        success, error, credentials = load_credentials()
        if not success:
            t.fail(error)
            t.add_metadata("hint", "Run the Blender addon and log in first")
            reporter.finish()
            return reporter
        t.add_metadata("org_id", credentials.get("org_id", "")[:8] + "...")
        t.add_metadata("projects_count", len(credentials.get("projects", [])))

    # Verify auth (skip in dry run to avoid unnecessary API calls)
    if not config.dry_run:
        with reporter.test("verify_auth", category="setup") as t:
            success, error = verify_auth(credentials)
            if not success:
                t.fail(error)

    # Get test scenarios
    scenarios = get_test_scenarios(config)

    if not scenarios:
        with reporter.test("find_test_files", category="setup") as t:
            t.fail("No test .blend files found", f"Checked: {config.test_blend_dir}")
        reporter.finish()
        return reporter

    # Run each scenario
    for scenario in scenarios:
        test_name = f"upload_{scenario['name']}"

        with reporter.test(test_name, category="upload", tags=["farm"]) as t:
            t.add_metadata("description", scenario["description"])
            t.add_metadata("blend_file", str(scenario["blend_file"]))
            t.add_metadata("dry_run", config.dry_run)

            if config.dry_run:
                result = simulate_upload(scenario["blend_file"], config, credentials)
            else:
                result = perform_upload(scenario["blend_file"], config, credentials)

            t.add_metadata("job_id", result.job_id)
            t.add_metadata("job_name", result.job_name)
            t.add_metadata("files_count", result.files_uploaded)
            t.add_metadata("s3_keys_sample", result.s3_keys[:5])
            t.add_metadata("farm_verification", result.farm_verification)

            if result.errors:
                t.fail("; ".join(result.errors))
            elif result.warnings:
                t.passed(f"Completed with warnings: {'; '.join(result.warnings)}")
            else:
                t.passed(f"Uploaded {result.files_uploaded} files")

    reporter.finish()
    return reporter


def main():
    parser = argparse.ArgumentParser(
        description="Real-world farm upload tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
IMPORTANT: Without --dry-run, this will actually upload to the farm!

Examples:
    python tests/realworld/test_farm_upload.py --dry-run    # Safe: validate only
    python tests/realworld/test_farm_upload.py              # Actually upload!
    python tests/realworld/test_farm_upload.py --report     # Save detailed report

After running (without --dry-run), check the farm dashboard:
1. Job should appear with name starting with 'SULU_TEST_'
2. All files should be uploaded (no missing)
3. Render should start without errors
4. Output image should look correct
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without actually uploading (safe mode)"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Write detailed report to tests/reports/"
    )
    parser.add_argument(
        "--report-dir",
        default="tests/reports",
        help="Directory for reports"
    )

    args = parser.parse_args()

    config = FarmTestConfig(
        dry_run=args.dry_run,
        write_report=args.report,
        report_dir=args.report_dir,
    )

    print("\n" + "=" * 70)
    print("  FARM UPLOAD TESTS")
    print("=" * 70)
    print(f"  Mode: {'DRY RUN (validation only)' if config.dry_run else 'REAL UPLOAD (!)'}")
    print("=" * 70 + "\n")

    if not config.dry_run:
        print("  WARNING: This will create real jobs on the farm!")
        print("  Press Ctrl+C within 5 seconds to cancel...")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n  Cancelled.")
            sys.exit(0)
        print()

    reporter = run_tests(config)
    reporter.print_summary()

    if config.write_report:
        report_dir = _addon_dir / config.report_dir
        paths = reporter.write_reports(str(report_dir))
        print(f"\n  Reports written to:")
        for fmt, path in paths.items():
            print(f"    {fmt}: {path}")

    # Print farm verification checklist
    print("\n" + "=" * 70)
    print("  FARM VERIFICATION CHECKLIST")
    print("=" * 70)

    if config.dry_run:
        print("""
  Since this was a DRY RUN, no jobs were created.

  To actually test uploads:
    python tests/realworld/test_farm_upload.py

  Then verify on the farm dashboard that:
  1. Jobs appear with names starting with 'SULU_TEST_'
  2. File counts match expected
  3. No missing texture/library errors
  4. Renders complete successfully
        """)
    else:
        print("""
  Jobs have been submitted to the farm!

  Go to the farm dashboard and verify:

  [1] JOBS APPEAR
    - Look for jobs starting with 'SULU_TEST_'
    - Each test scenario creates one job

  [2] FILES UPLOADED
    - Click on a job to see uploaded files
    - Verify texture paths don't have drive letters (C:/)
    - Verify no paths contain 'Temp' or 'bat_packroot'

  [3] RENDERING WORKS
    - Jobs should start rendering without errors
    - Check job logs for any 'file not found' errors

  [4] OUTPUT CORRECT
    - Download rendered frame
    - Verify no pink/missing textures
    - Verify linked objects appear correctly
        """)

    sys.exit(0 if reporter.report.failed == 0 else 1)


if __name__ == "__main__":
    main()
