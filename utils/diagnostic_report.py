"""
diagnostic_report.py — Continuous diagnostic reporting for Sulu Submit worker.

Writes incremental JSON reports during job submission for customer diagnosis.
Reports are resilient against cancellation via continuous flushing.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Maximum tail_lines stored per upload step in the report JSON.
# rclone_utils keeps up to 160 lines in memory; we only persist the last N
# to avoid bloating the report file.
_MAX_TAIL_LINES = 20


class DiagnosticReport:
    """
    Continuous JSON report writer for submission diagnostics.

    Features:
    - Atomic writes using .tmp + os.replace() pattern
    - Flushes every 50 entries OR at stage transitions for crash resilience
    - JSON schema with version field for future evolution
    """

    REPORT_VERSION = "3.0"
    FLUSH_THRESHOLD = 50  # Flush after this many entries

    def __init__(
        self,
        reports_dir: Path,
        job_id: str,
        blend_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize a new diagnostic report.

        Args:
            reports_dir: Directory to write reports to
            job_id: Unique job identifier
            blend_name: Name of the blend file (without extension)
            metadata: Initial metadata dict
        """
        self._lock = threading.RLock()  # RLock allows re-entrant locking
        self._reports_dir = Path(reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename: report_{timestamp}_{blend_name}.json
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_blend = "".join(c if c.isalnum() or c in "-_" else "_" for c in blend_name[:30])
        self._filename = f"report_{timestamp}_{safe_blend}.json"
        self._path = self._reports_dir / self._filename

        # Initialize report structure
        self._data: Dict[str, Any] = {
            "report_version": self.REPORT_VERSION,
            "metadata": {
                "job_id": job_id,
                "job_name": "",
                "source_blend": "",
                "upload_type": "",
                "project_root": "",
                "project_root_method": "",  # "automatic", "custom", "filesystem_root"
                "blender_version": "",
                "addon_version": [],
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "status": "in_progress",
            },
            "environment": {
                "os": platform.system(),
                "os_version": platform.version(),
                "python_version": platform.python_version(),
                "architecture": platform.machine(),
                "rclone_version": "",
            },
            "preflight": {
                "passed": None,
                "issues": [],
                "user_override": None,  # True if user continued despite issues
            },
            "stages": {
                "trace": {
                    "started_at": None,
                    "completed_at": None,
                    "entries": [],
                    "summary": {
                        "total": 0, "ok": 0, "missing": 0,
                        "unreadable": 0, "packed": 0,
                        "total_size_bytes": 0,
                    },
                },
                "pack": {
                    "started_at": None,
                    "completed_at": None,
                    "entries": [],
                    "summary": {
                        "files_packed": 0,
                        "total_size": 0,
                        "dependency_total_size": 0,
                    },
                },
                "upload": {
                    "started_at": None,
                    "completed_at": None,
                    "steps": [],
                    "summary": {
                        "total_bytes_transferred": 0,
                        "total_checks": 0,
                        "total_transfers": 0,
                        "total_errors": 0,
                        "total_elapsed_seconds": 0.0,
                        "step_count": 0,
                        "has_warnings": False,
                    },
                },
            },
            "user_choices": [],
            "issues": {
                "missing_files": [],
                "unreadable_files": {},
                "cross_drive_files": [],
                "absolute_path_files": [],
            },
        }

        # Merge initial metadata
        if metadata:
            self._data["metadata"].update(metadata)

        # Track entries since last flush
        self._entries_since_flush = 0
        self._current_stage: Optional[str] = None
        self._current_upload_step: Optional[Dict[str, Any]] = None

        # Write initial report
        self.flush()

        # Cleanup old reports (keep only 10 most recent)
        self._cleanup_old_reports()

    def _cleanup_old_reports(self, keep: int = 10) -> None:
        """Remove old diagnostic reports, keeping only the most recent ones."""
        try:
            reports = list(self._reports_dir.glob("report_*.json"))
            # Sort by modification time, newest first
            reports.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            # Remove reports beyond the keep limit
            for old_report in reports[keep:]:
                try:
                    old_report.unlink()
                except Exception:
                    pass  # Best effort cleanup
        except Exception:
            pass  # Don't crash if cleanup fails

    def _atomic_write(self) -> None:
        """Write report atomically using tmp + replace pattern."""
        tmp_path = self._path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            # Best effort - don't crash the worker if report writing fails
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _maybe_flush(self) -> None:
        """Flush if we've accumulated enough entries."""
        if self._entries_since_flush >= self.FLUSH_THRESHOLD:
            self.flush()

    def set_metadata(self, key: str, value: Any) -> None:
        """Set a metadata field (e.g., project_root)."""
        with self._lock:
            self._data["metadata"][key] = value
            self._entries_since_flush += 1
            self._maybe_flush()

    def set_environment(self, key: str, value: Any) -> None:
        """Set an environment field (e.g., rclone_version)."""
        with self._lock:
            self._data["environment"][key] = value
            self._entries_since_flush += 1
            self._maybe_flush()

    def record_preflight(
        self,
        passed: bool,
        issues: List[str],
        user_override: Optional[bool] = None,
    ) -> None:
        """Record preflight check results."""
        with self._lock:
            self._data["preflight"]["passed"] = passed
            self._data["preflight"]["issues"] = issues
            if user_override is not None:
                self._data["preflight"]["user_override"] = user_override
            self._entries_since_flush += 1
            self._maybe_flush()

    def record_user_choice(
        self,
        prompt: str,
        choice: str,
        options: Optional[List[str]] = None,
    ) -> None:
        """Record a user decision point (e.g., continuing despite warnings)."""
        with self._lock:
            entry: Dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "prompt": prompt,
                "choice": choice,
            }
            if options:
                entry["options"] = options
            self._data["user_choices"].append(entry)
            self._entries_since_flush += 1
            self._maybe_flush()

    def start_stage(self, stage: str) -> None:
        """Start a new stage (trace, pack, upload)."""
        with self._lock:
            self._current_stage = stage
            if stage in self._data["stages"]:
                self._data["stages"][stage]["started_at"] = datetime.now().isoformat()
            self.flush()

    def complete_stage(self, stage: str) -> None:
        """Complete a stage."""
        with self._lock:
            if stage in self._data["stages"]:
                self._data["stages"][stage]["completed_at"] = datetime.now().isoformat()

                # Update summary for trace stage
                if stage == "trace":
                    entries = self._data["stages"]["trace"]["entries"]
                    ok = sum(1 for e in entries if e.get("status") == "ok")
                    missing = sum(1 for e in entries if e.get("status") == "missing")
                    unreadable = sum(1 for e in entries if e.get("status") == "unreadable")
                    packed = sum(1 for e in entries if e.get("status") == "packed")
                    absolute_path = sum(1 for e in entries if e.get("status") == "absolute_path")
                    total_size = sum(e.get("file_size", 0) for e in entries)
                    self._data["stages"]["trace"]["summary"] = {
                        "total": len(entries),
                        "ok": ok,
                        "missing": missing,
                        "unreadable": unreadable,
                        "packed": packed,
                        "absolute_path": absolute_path,
                        "total_size_bytes": total_size,
                    }

                    # Populate issues section
                    self._data["issues"]["missing_files"] = [
                        e.get("resolved_path", "") for e in entries if e.get("status") == "missing"
                    ]
                    self._data["issues"]["unreadable_files"] = {
                        e.get("resolved_path", ""): e.get("error_message", "Unknown error")
                        for e in entries if e.get("status") == "unreadable"
                    }
                    self._data["issues"]["absolute_path_files"] = [
                        e.get("resolved_path", "") for e in entries if e.get("status") == "absolute_path"
                    ]

                # Update summary for pack stage
                elif stage == "pack":
                    entries = self._data["stages"]["pack"]["entries"]
                    total_size = sum(e.get("file_size", 0) for e in entries)
                    self._data["stages"]["pack"]["summary"]["files_packed"] = len(entries)
                    self._data["stages"]["pack"]["summary"]["total_size"] = total_size

                # Compute upload summary across all steps
                elif stage == "upload":
                    steps = self._data["stages"]["upload"]["steps"]
                    total_bytes = 0
                    total_checks = 0
                    total_transfers = 0
                    total_errors = 0
                    total_elapsed = 0.0
                    has_warnings = False

                    for step in steps:
                        total_bytes += step.get("bytes_transferred", 0)
                        if step.get("warning"):
                            has_warnings = True
                        total_elapsed += step.get("elapsed_seconds", 0)
                        stats = step.get("rclone_stats")
                        if stats:
                            total_checks += stats.get("checks", 0) or 0
                            total_transfers += stats.get("transfers", 0) or 0
                            total_errors += stats.get("errors", 0) or 0

                    self._data["stages"]["upload"]["summary"] = {
                        "total_bytes_transferred": total_bytes,
                        "total_checks": total_checks,
                        "total_transfers": total_transfers,
                        "total_errors": total_errors,
                        "total_elapsed_seconds": round(total_elapsed, 3),
                        "step_count": len(steps),
                        "has_warnings": has_warnings,
                    }

            self._current_stage = None
            self.flush()

    def add_trace_entry(
        self,
        source_blend: str,
        block_type: str,
        block_name: str,
        resolved_path: str,
        status: str,
        error_msg: Optional[str] = None,
        file_size: int = 0,
    ) -> None:
        """
        Add a trace entry for a dependency.

        Args:
            source_blend: Source .blend file path (converted to absolute)
            block_type: DNA type name (e.g., "Image", "Library")
            block_name: Block name
            resolved_path: Absolute path to the resolved file
            status: "ok", "missing", or "unreadable"
            error_msg: Error message if unreadable
            file_size: File size in bytes if available
        """
        with self._lock:
            entry = {
                "source_blend": os.path.abspath(source_blend),
                "block_type": block_type,
                "block_name": block_name,
                "resolved_path": resolved_path,
                "status": status,
                "error_message": error_msg,
                "file_size": file_size,
            }
            self._data["stages"]["trace"]["entries"].append(entry)
            self._entries_since_flush += 1
            self._maybe_flush()

    def add_pack_entry(
        self,
        src_path: str,
        dest_key: str,
        file_size: int = 0,
        status: str = "ok",
    ) -> None:
        """
        Add a pack/manifest entry.

        Args:
            src_path: Source path on disk
            dest_key: Destination key/path in archive or manifest
            file_size: File size in bytes
            status: "ok" or error status
        """
        with self._lock:
            entry = {
                "src_path": src_path,
                "dest_key": dest_key,
                "file_size": file_size,
                "status": status,
            }
            self._data["stages"]["pack"]["entries"].append(entry)
            self._entries_since_flush += 1
            self._maybe_flush()

    def set_pack_dependency_size(self, size_bytes: int) -> None:
        """Record the total dependency size (excluding main blend) in the pack summary."""
        with self._lock:
            self._data["stages"]["pack"]["summary"]["dependency_total_size"] = size_bytes
            self._entries_since_flush += 1
            self._maybe_flush()

    def start_upload_step(
        self,
        step_num: int,
        total_steps: int,
        title: str,
        manifest_entries: Optional[int] = None,
        expected_bytes: Optional[int] = None,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        verb: Optional[str] = None,
    ) -> None:
        """
        Start an upload step.

        Args:
            step_num: Current step number (1-indexed)
            total_steps: Total number of steps
            title: Step title/description
            manifest_entries: Number of files in the manifest (for dependency uploads)
            expected_bytes: Expected total bytes to transfer
            source: Local source path or file
            destination: Remote destination (S3 key / bucket path)
            verb: rclone verb (copy, move, copyto, moveto)
        """
        with self._lock:
            self._current_upload_step = {
                "step": step_num,
                "total": total_steps,
                "title": title,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "elapsed_seconds": 0,
                "bytes_transferred": 0,
            }
            if manifest_entries is not None:
                self._current_upload_step["manifest_entries"] = manifest_entries
            if expected_bytes is not None:
                self._current_upload_step["expected_bytes"] = expected_bytes
            if source is not None:
                self._current_upload_step["source"] = source
            if destination is not None:
                self._current_upload_step["destination"] = destination
            if verb is not None:
                self._current_upload_step["verb"] = verb
            self._data["stages"]["upload"]["steps"].append(self._current_upload_step)
            self._entries_since_flush += 1
            self._maybe_flush()

    def complete_upload_step(
        self,
        bytes_transferred: int = 0,
        rclone_stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Complete the current upload step.

        Args:
            bytes_transferred: Bytes transferred during this step
            rclone_stats: Full rclone stats dict from run_rclone() return value
        """
        with self._lock:
            if self._current_upload_step is not None:
                now = datetime.now()
                self._current_upload_step["completed_at"] = now.isoformat()
                self._current_upload_step["bytes_transferred"] = bytes_transferred

                # Compute elapsed seconds
                try:
                    started = datetime.fromisoformat(
                        self._current_upload_step["started_at"]
                    )
                    self._current_upload_step["elapsed_seconds"] = round(
                        (now - started).total_seconds(), 3
                    )
                except Exception:
                    pass

                if rclone_stats is not None:
                    # Truncate tail_lines before persisting to keep report lean
                    stats_to_store = dict(rclone_stats)
                    tail = stats_to_store.get("tail_lines")
                    if isinstance(tail, (list, tuple)) and len(tail) > _MAX_TAIL_LINES:
                        stats_to_store["tail_lines"] = list(tail[-_MAX_TAIL_LINES:])
                        stats_to_store["tail_lines_truncated"] = True

                    self._current_upload_step["rclone_stats"] = stats_to_store

                    # --- Generate anomaly warnings (most specific wins) ---
                    checks = rclone_stats.get("checks", 0) or 0
                    transfers = rclone_stats.get("transfers", 0) or 0
                    stats_received = rclone_stats.get("stats_received", True)
                    expected = self._current_upload_step.get("expected_bytes")

                    warning = ""

                    # 1. Most fundamental: rclone emitted no stats at all
                    if not stats_received:
                        warning = (
                            "rclone emitted no transfer stats — "
                            "source path may be invalid or transfer "
                            "completed instantly"
                        )
                    # 2. checks/transfers counters
                    elif checks == 0 and transfers == 0:
                        warning = (
                            "rclone checked 0 files — manifest may be "
                            "empty or source path doesn't match"
                        )
                    elif checks > 0 and transfers == 0:
                        warning = (
                            f"rclone checked {checks} files but "
                            "transferred 0 — destination may already "
                            "have matching files, or PUT permissions "
                            "missing"
                        )

                    # 3. bytes_transferred vs expected_bytes mismatch
                    if expected and expected > 0:
                        if bytes_transferred == 0:
                            mismatch = (
                                f"Expected {expected} bytes but "
                                "transferred 0 — files may not have "
                                "been uploaded"
                            )
                            if warning:
                                warning += "; " + mismatch
                            else:
                                warning = mismatch
                        elif bytes_transferred < expected * 0.5:
                            pct = bytes_transferred * 100 // expected
                            mismatch = (
                                f"Transferred {bytes_transferred} of "
                                f"{expected} expected bytes ({pct}%)"
                            )
                            if warning:
                                warning += "; " + mismatch
                            else:
                                warning = mismatch

                    # 4. Non-zero errors despite exit 0
                    errors = rclone_stats.get("errors", 0) or 0
                    if errors > 0:
                        error_warning = (
                            f"rclone reported {errors} error(s) despite "
                            "exit code 0 — some files may not have uploaded"
                        )
                        warning = (warning + "; " + error_warning) if warning else error_warning

                    if warning:
                        self._current_upload_step["warning"] = warning
                self._current_upload_step = None
            self.flush()

    def add_upload_split_group(
        self,
        group_name: str,
        file_count: int,
        source: str,
        destination: str,
        rclone_stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record details of a single split-upload group within the current upload step.

        Call this during the split-upload loop, before complete_upload_step().
        The groups are stored as a list inside the current upload step.
        """
        with self._lock:
            if self._current_upload_step is None:
                return
            groups = self._current_upload_step.setdefault("split_groups", [])
            entry: Dict[str, Any] = {
                "group_name": group_name,
                "file_count": file_count,
                "source": source,
                "destination": destination,
            }
            if rclone_stats is not None:
                entry["bytes_transferred"] = rclone_stats.get("bytes_transferred", 0)
                entry["checks"] = rclone_stats.get("checks", 0) or 0
                entry["transfers"] = rclone_stats.get("transfers", 0) or 0
                entry["errors"] = rclone_stats.get("errors", 0) or 0
                entry["stats_received"] = rclone_stats.get("stats_received", True)
                if not entry["stats_received"] or entry["transfers"] == 0:
                    entry["warning"] = "group transferred 0 files"
            groups.append(entry)
            self._entries_since_flush += 1
            self._maybe_flush()

    def add_cross_drive_files(self, files: List[str]) -> None:
        """Add cross-drive files to the issues section."""
        with self._lock:
            self._data["issues"]["cross_drive_files"] = files
            self._entries_since_flush += 1
            self._maybe_flush()

    def add_absolute_path_files(self, files: List[str]) -> None:
        """Add absolute path files to the issues section."""
        with self._lock:
            self._data["issues"]["absolute_path_files"] = files
            self._entries_since_flush += 1
            self._maybe_flush()

    def set_status(self, status: str) -> None:
        """
        Set the overall report status.

        Args:
            status: "in_progress", "completed", "failed", or "cancelled"
        """
        with self._lock:
            self._data["metadata"]["status"] = status
            self.flush()

    def flush(self) -> None:
        """Force write to disk."""
        with self._lock:
            self._atomic_write()
            self._entries_since_flush = 0

    def finalize(self) -> None:
        """Final flush with completion timestamp."""
        with self._lock:
            self._data["metadata"]["completed_at"] = datetime.now().isoformat()
            if self._data["metadata"]["status"] == "in_progress":
                self._data["metadata"]["status"] = "completed"
            self._atomic_write()
            self._entries_since_flush = 0

    def get_path(self) -> Path:
        """Get the path to the report file."""
        return self._path

    def get_reports_dir(self) -> Path:
        """Get the reports directory path."""
        return self._reports_dir


def generate_test_report(
    blend_path: str,
    dep_paths: List[Path],
    missing_set: set,
    unreadable_dict: dict,
    project_root: Path,
    same_drive_deps: List[Path],
    cross_drive_deps: List[Path],
    upload_type: str,
    addon_dir: Optional[str] = None,
    job_id: Optional[str] = None,
    mode: str = "test",
    format_size_fn: Optional[Any] = None,
) -> Tuple[dict, Optional[Path]]:
    """
    Generate a diagnostic report and save it to the reports directory.

    This is a standalone report generator for test mode, separate from the
    continuous DiagnosticReport class used during actual submissions.

    Returns: (report_dict, report_path) where report_path is None if saving failed.
    """
    # Use provided format_size or fallback
    def _format_size(size_bytes: int) -> str:
        if format_size_fn:
            return format_size_fn(size_bytes)
        if size_bytes < 1000:
            return f"{size_bytes} B"
        elif size_bytes < 1000 * 1000:
            return f"{size_bytes / 1000:.1f} KB"
        elif size_bytes < 1000 * 1000 * 1000:
            return f"{size_bytes / (1000 * 1000):.1f} MB"
        else:
            return f"{size_bytes / (1000 * 1000 * 1000):.2f} GB"

    # Build report data
    blend_size = 0
    try:
        blend_size = os.path.getsize(blend_path)
    except Exception:
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
            except Exception:
                pass

    report = {
        "report_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "mode": mode,
        "upload_type": upload_type,
        "blend_file": {
            "path": str(blend_path),
            "name": os.path.basename(blend_path),
            "size_bytes": blend_size,
            "size_human": _format_size(blend_size),
        },
        "project_root": str(project_root),
        "dependencies": {
            "total_count": len(dep_paths),
            "total_size_bytes": total_size,
            "total_size_human": _format_size(total_size),
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

    if job_id:
        report["job_id"] = job_id

    report_path = None
    try:
        if addon_dir:
            reports_dir = Path(addon_dir) / "reports"
        else:
            reports_dir = Path(__file__).parent.parent / "reports"

        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        blend_name = Path(blend_path).stem[:30]
        blend_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in blend_name)
        filename = f"submit_report_{timestamp}_{blend_name}.json"

        report_path = reports_dir / filename
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

    except Exception:
        report_path = None

    return report, report_path
