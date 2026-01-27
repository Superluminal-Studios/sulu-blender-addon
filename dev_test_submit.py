#!/usr/bin/env python3
"""
dev_test_submit.py - CLI test mode for the submission pipeline.

Run dependency tracing and project root computation WITHOUT Blender or actual submission.
Useful for quickly iterating on the packing logic.

Usage:
    python dev_test_submit.py                      # Uses dev_config.json
    python dev_test_submit.py path/to/file.blend   # Override blend path
    python dev_test_submit.py --help

Requirements:
    - Python 3.9+
    - No Blender required (uses BAT directly)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Add the addon directory to path so we can import modules
ADDON_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ADDON_DIR.parent))

# Import BAT modules directly
from blender_asset_tracer import trace
from blender_asset_tracer.pack import Packer
from blender_asset_tracer.pack import zipped


# ─── Drive detection helpers (copied from bat_utils to avoid bpy dependency) ──

import re

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]+")


def _is_win_drive_path(p: str) -> bool:
    return bool(_WIN_DRIVE_RE.match(str(p)))


def _drive(path: str) -> str:
    p = str(path).replace("\\", "/")
    if _is_win_drive_path(p):
        return (p[:2]).upper()
    if p.startswith("//") or p.startswith("\\\\"):
        return "UNC"
    if os.name == "nt":
        return os.path.splitdrive(p)[0].upper()
    return ""


def _norm_path(path: str) -> str:
    p = str(path).replace("\\", "/")
    if _is_win_drive_path(p) or p.startswith("//") or p.startswith("\\\\"):
        return p
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/")


# ─── Core functions ───────────────────────────────────────────────────────────


def trace_dependencies(blend_path: Path) -> Tuple[List[Path], Set[Path], Dict[Path, str]]:
    """Lightweight dependency trace using BAT's trace.deps()."""
    deps: List[Path] = []
    missing: Set[Path] = set()
    unreadable: Dict[Path, str] = {}

    for usage in trace.deps(blend_path):
        abs_path = usage.abspath
        deps.append(abs_path)

        if not abs_path.exists():
            missing.add(abs_path)
        else:
            try:
                if abs_path.is_file():
                    with abs_path.open("rb") as f:
                        f.read(1)
            except (PermissionError, OSError) as e:
                unreadable[abs_path] = str(e)
            except Exception as e:
                unreadable[abs_path] = f"{type(e).__name__}: {e}"

    return deps, missing, unreadable


def compute_project_root(
    blend_path: Path,
    dependency_paths: List[Path],
    custom_project_path: Optional[Path] = None,
) -> Tuple[Path, List[Path], List[Path]]:
    """Compute optimal project root from blend file and its dependencies."""
    blend_abs = _norm_path(str(blend_path))
    blend_drive = _drive(blend_abs)
    blend_dir = Path(blend_path).parent.resolve()

    same_drive_paths: List[Path] = []
    cross_drive_paths: List[Path] = []

    for dep in dependency_paths:
        dep_norm = _norm_path(str(dep))
        dep_drive = _drive(dep_norm)
        if dep_drive == blend_drive:
            same_drive_paths.append(dep)
        else:
            cross_drive_paths.append(dep)

    if custom_project_path is not None:
        custom_abs = Path(custom_project_path).resolve()
        if custom_abs.is_file():
            custom_abs = custom_abs.parent
        if custom_abs.is_dir():
            return custom_abs, same_drive_paths, cross_drive_paths

    if not same_drive_paths:
        return blend_dir, same_drive_paths, cross_drive_paths

    all_same_drive = [str(blend_path.resolve())] + [str(p.resolve()) for p in same_drive_paths]

    try:
        common = os.path.commonpath(all_same_drive)
        common_path = Path(common)
        if common_path.is_file():
            common_path = common_path.parent
        if common_path.is_dir():
            return common_path, same_drive_paths, cross_drive_paths
    except (ValueError, OSError):
        pass

    return blend_dir, same_drive_paths, cross_drive_paths


def shorten_path(path: str, max_len: int = 80) -> str:
    """Shorten long paths for display."""
    p = str(path).replace("\\", "/")
    if len(p) <= max_len:
        return p
    return "..." + p[-(max_len - 3):]


def format_size(size_bytes: int) -> str:
    """Format bytes as human readable."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def generate_report(
    blend_path: Path,
    dep_paths: List[Path],
    missing_set: Set[Path],
    unreadable_dict: Dict[Path, str],
    project_root: Path,
    same_drive_deps: List[Path],
    cross_drive_deps: List[Path],
    upload_type: str,
) -> Tuple[dict, Optional[Path]]:
    """
    Generate a diagnostic report and save it to the reports directory.
    Returns: (report_dict, report_path)
    """
    from datetime import datetime

    # Build report data
    blend_size = 0
    try:
        blend_size = blend_path.stat().st_size
    except:
        pass

    # Classify by extension
    by_ext: Dict[str, int] = {}
    total_size = 0
    for dep in dep_paths:
        ext = dep.suffix.lower() if dep.suffix else "(no ext)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
        if dep.exists() and dep.is_file():
            try:
                total_size += dep.stat().st_size
            except:
                pass

    report = {
        "report_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "mode": "cli_test",
        "upload_type": upload_type,
        "blend_file": {
            "path": str(blend_path),
            "name": blend_path.name,
            "size_bytes": blend_size,
            "size_human": format_size(blend_size),
        },
        "project_root": str(project_root),
        "dependencies": {
            "total_count": len(dep_paths),
            "total_size_bytes": total_size,
            "total_size_human": format_size(total_size),
            "by_extension": dict(sorted(by_ext.items(), key=lambda x: -x[1])),
            "same_drive_count": len(same_drive_deps),
            "cross_drive_count": len(cross_drive_deps),
        },
        "issues": {
            "missing_count": len(missing_set),
            "missing_files": [str(p) for p in sorted(missing_set)],
            "unreadable_count": len(unreadable_dict),
            "unreadable_files": {str(k): v for k, v in sorted(unreadable_dict.items())},
            "cross_drive_count": len(cross_drive_deps),
            "cross_drive_files": [str(p) for p in sorted(cross_drive_deps)],
        },
        "all_dependencies": [str(p) for p in sorted(dep_paths)],
    }

    # Save report to file
    report_path = None
    try:
        reports_dir = ADDON_DIR / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        blend_name = blend_path.stem[:30]
        blend_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in blend_name)
        filename = f"submit_report_{timestamp}_{blend_name}.json"

        report_path = reports_dir / filename
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

    except Exception as e:
        print(f"Warning: Could not save report: {e}")
        report_path = None

    return report, report_path


# ─── Test runner ──────────────────────────────────────────────────────────────


def run_test(
    blend_path: Path,
    upload_type: str = "PROJECT",
    automatic_project_path: bool = True,
    custom_project_path: Optional[str] = None,
    dry_run: bool = True,
    verbose: bool = False,
) -> dict:
    """
    Run the submission pipeline in test mode.

    Returns a dict with all the computed information for inspection.
    """
    results = {
        "blend_path": str(blend_path),
        "upload_type": upload_type,
        "success": False,
        "error": None,
    }

    print("\n" + "=" * 70)
    print(f"  SUBMISSION TEST MODE - {upload_type}")
    print("=" * 70)

    # Validate blend file
    if not blend_path.exists():
        results["error"] = f"Blend file not found: {blend_path}"
        print(f"\n[ERROR] {results['error']}")
        return results

    if not blend_path.suffix.lower() == ".blend":
        results["error"] = f"Not a .blend file: {blend_path}"
        print(f"\n[ERROR] {results['error']}")
        return results

    print(f"\n[1/6] Blend file: {blend_path}")
    print(f"      Size: {format_size(blend_path.stat().st_size)}")

    # Step 1: Trace dependencies
    print("\n[2/6] Tracing dependencies...")
    try:
        dep_paths, missing_set, unreadable_dict = trace_dependencies(blend_path)
    except Exception as e:
        results["error"] = f"Dependency trace failed: {e}"
        print(f"\n[ERROR] {results['error']}")
        return results

    results["total_dependencies"] = len(dep_paths)
    results["missing_count"] = len(missing_set)
    results["unreadable_count"] = len(unreadable_dict)

    print(f"      Found {len(dep_paths)} dependencies")

    # Step 2: Compute project root
    print("\n[3/6] Computing project root...")
    custom_root = Path(custom_project_path) if (not automatic_project_path and custom_project_path) else None

    project_root, same_drive_deps, cross_drive_deps = compute_project_root(
        blend_path, dep_paths, custom_root
    )

    results["project_root"] = str(project_root)
    results["same_drive_count"] = len(same_drive_deps)
    results["cross_drive_count"] = len(cross_drive_deps)

    print(f"      Project root: {project_root}")
    print(f"      Same-drive deps: {len(same_drive_deps)}")
    print(f"      Cross-drive deps: {len(cross_drive_deps)}")

    # Step 3: Show dependency breakdown
    print("\n[4/6] Dependency breakdown:")

    # Classify by type
    by_type: Dict[str, List[Path]] = {}
    total_size = 0

    for dep in dep_paths:
        ext = dep.suffix.lower() if dep.suffix else "(no ext)"
        by_type.setdefault(ext, []).append(dep)
        if dep.exists() and dep.is_file():
            try:
                total_size += dep.stat().st_size
            except:
                pass

    results["total_size"] = total_size
    results["by_extension"] = {k: len(v) for k, v in sorted(by_type.items())}

    print(f"\n      By extension:")
    for ext, paths in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"        {ext:12} : {len(paths):4} files")

    print(f"\n      Total size: {format_size(total_size)}")

    # Step 4: Show issues
    print("\n[5/6] Issues:")

    if missing_set:
        results["missing_files"] = [str(p) for p in sorted(missing_set)]
        print(f"\n      MISSING ({len(missing_set)}):")
        for p in sorted(missing_set)[:10]:
            print(f"        - {shorten_path(str(p))}")
        if len(missing_set) > 10:
            print(f"        ... and {len(missing_set) - 10} more")
    else:
        print(f"      No missing files")

    if unreadable_dict:
        results["unreadable_files"] = {str(k): v for k, v in unreadable_dict.items()}
        print(f"\n      UNREADABLE ({len(unreadable_dict)}):")
        for p, err in sorted(unreadable_dict.items())[:10]:
            print(f"        - {shorten_path(str(p))}")
            print(f"          {err}")
        if len(unreadable_dict) > 10:
            print(f"        ... and {len(unreadable_dict) - 10} more")
    else:
        print(f"      No unreadable files")

    if cross_drive_deps:
        results["cross_drive_files"] = [str(p) for p in cross_drive_deps]
        print(f"\n      CROSS-DRIVE ({len(cross_drive_deps)}):")
        for p in cross_drive_deps[:10]:
            print(f"        - {shorten_path(str(p))}")
        if len(cross_drive_deps) > 10:
            print(f"        ... and {len(cross_drive_deps) - 10} more")
    else:
        print(f"      No cross-drive files")

    # Verbose mode: show all dependencies
    if verbose:
        print("\n" + "-" * 70)
        print("  ALL DEPENDENCIES (verbose mode)")
        print("-" * 70)
        for i, dep in enumerate(sorted(dep_paths), 1):
            status = "OK"
            if dep in missing_set:
                status = "MISSING"
            elif dep in unreadable_dict:
                status = "UNREADABLE"
            elif dep in cross_drive_deps:
                status = "CROSS-DRIVE"
            size_str = ""
            if dep.exists() and dep.is_file():
                try:
                    size_str = f" ({format_size(dep.stat().st_size)})"
                except:
                    pass
            print(f"  [{i:4}] [{status:11}] {dep}{size_str}")

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    issues = len(missing_set) + len(unreadable_dict) + len(cross_drive_deps)
    if issues == 0:
        print("\n  [OK] No issues detected. Ready for submission.")
        results["success"] = True
    else:
        print(f"\n  [WARNING] {issues} issue(s) detected:")
        if missing_set:
            print(f"    - {len(missing_set)} missing file(s)")
        if unreadable_dict:
            print(f"    - {len(unreadable_dict)} unreadable file(s)")
        if cross_drive_deps and upload_type == "PROJECT":
            print(f"    - {len(cross_drive_deps)} cross-drive file(s) (will be excluded in PROJECT mode)")
        results["success"] = True  # Still "success" since we completed the analysis

    if dry_run:
        print("\n  [DRY RUN] No actual submission will be performed.")
    else:
        print("\n  [LIVE] Would proceed with submission...")

    # Generate report
    print("\n[6/6] Generating report...")
    report, report_path = generate_report(
        blend_path=blend_path,
        dep_paths=dep_paths,
        missing_set=missing_set,
        unreadable_dict=unreadable_dict,
        project_root=project_root,
        same_drive_deps=same_drive_deps,
        cross_drive_deps=cross_drive_deps,
        upload_type=upload_type,
    )

    if report_path:
        print(f"      Report saved: {report_path}")
        results["report_path"] = str(report_path)
    else:
        print(f"      Report could not be saved to file")

    print("=" * 70 + "\n")

    return results


def load_config() -> dict:
    """Load dev_config.json if it exists."""
    config_path = ADDON_DIR / "dev_config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load dev_config.json: {e}")
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Test the submission pipeline without Blender or actual submission.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dev_test_submit.py                           # Use dev_config.json
  python dev_test_submit.py my_scene.blend            # Test specific file
  python dev_test_submit.py my_scene.blend --verbose  # Show all dependencies
  python dev_test_submit.py my_scene.blend --zip      # Test ZIP mode
        """,
    )

    parser.add_argument(
        "blend_path",
        nargs="?",
        help="Path to .blend file (overrides dev_config.json)",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Test ZIP upload mode (default: PROJECT)",
    )
    parser.add_argument(
        "--project-path",
        type=str,
        help="Custom project path (disables automatic)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show all dependencies in output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (for scripting)",
    )

    args = parser.parse_args()

    # Load config
    config = load_config()

    # Determine blend path
    blend_path_str = args.blend_path or config.get("test_blend_path")
    if not blend_path_str:
        print("Error: No blend file specified.")
        print("Either:")
        print("  1. Pass a blend file as argument: python dev_test_submit.py path/to/file.blend")
        print("  2. Create dev_config.json with 'test_blend_path' set")
        print("\nSee dev_config.example.json for template.")
        sys.exit(1)

    blend_path = Path(blend_path_str).resolve()

    # Determine settings
    upload_type = "ZIP" if args.zip else config.get("upload_type", "PROJECT")
    automatic_project_path = config.get("automatic_project_path", True)
    custom_project_path = args.project_path or config.get("custom_project_path")

    if args.project_path:
        automatic_project_path = False

    dry_run = config.get("dry_run", True)

    # Run test
    results = run_test(
        blend_path=blend_path,
        upload_type=upload_type,
        automatic_project_path=automatic_project_path,
        custom_project_path=custom_project_path,
        dry_run=dry_run,
        verbose=args.verbose,
    )

    if args.json:
        print("\n--- JSON Output ---")
        print(json.dumps(results, indent=2, default=str))

    sys.exit(0 if results.get("success") else 1)


if __name__ == "__main__":
    main()
