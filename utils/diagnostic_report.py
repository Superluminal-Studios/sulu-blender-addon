"""
diagnostic_report.py — Continuous diagnostic reporting for Sulu Submit worker.

Writes incremental JSON reports during job submission for customer diagnosis.
Reports are resilient against cancellation via continuous flushing.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class DiagnosticReport:
    """
    Continuous JSON report writer for submission diagnostics.

    Features:
    - Atomic writes using .tmp + os.replace() pattern
    - Flushes every 50 entries OR at stage transitions for crash resilience
    - JSON schema with version field for future evolution
    """

    REPORT_VERSION = "2.0"
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
                "blender_version": "",
                "addon_version": [],
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "status": "in_progress",
            },
            "stages": {
                "trace": {
                    "started_at": None,
                    "completed_at": None,
                    "entries": [],
                    "summary": {"total": 0, "ok": 0, "missing": 0, "unreadable": 0},
                },
                "pack": {
                    "started_at": None,
                    "completed_at": None,
                    "entries": [],
                    "summary": {"files_packed": 0, "total_size": 0},
                },
                "upload": {
                    "started_at": None,
                    "completed_at": None,
                    "steps": [],
                },
            },
            "issues": {
                "missing_files": [],
                "unreadable_files": {},
                "cross_drive_files": [],
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
                    self._data["stages"]["trace"]["summary"] = {
                        "total": len(entries),
                        "ok": ok,
                        "missing": missing,
                        "unreadable": unreadable,
                    }

                    # Populate issues section
                    self._data["issues"]["missing_files"] = [
                        e.get("resolved_path", "") for e in entries if e.get("status") == "missing"
                    ]
                    self._data["issues"]["unreadable_files"] = {
                        e.get("resolved_path", ""): e.get("error_message", "Unknown error")
                        for e in entries if e.get("status") == "unreadable"
                    }

                # Update summary for pack stage
                elif stage == "pack":
                    entries = self._data["stages"]["pack"]["entries"]
                    total_size = sum(e.get("file_size", 0) for e in entries)
                    self._data["stages"]["pack"]["summary"] = {
                        "files_packed": len(entries),
                        "total_size": total_size,
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

    def start_upload_step(
        self,
        step_num: int,
        total_steps: int,
        title: str,
    ) -> None:
        """
        Start an upload step.

        Args:
            step_num: Current step number (1-indexed)
            total_steps: Total number of steps
            title: Step title/description
        """
        with self._lock:
            self._current_upload_step = {
                "step": step_num,
                "total": total_steps,
                "title": title,
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "bytes_transferred": 0,
            }
            self._data["stages"]["upload"]["steps"].append(self._current_upload_step)
            self._entries_since_flush += 1
            self._maybe_flush()

    def complete_upload_step(self, bytes_transferred: int = 0) -> None:
        """Complete the current upload step."""
        with self._lock:
            if self._current_upload_step is not None:
                self._current_upload_step["completed_at"] = datetime.now().isoformat()
                self._current_upload_step["bytes_transferred"] = bytes_transferred
                self._current_upload_step = None
            self.flush()

    def add_cross_drive_files(self, files: List[str]) -> None:
        """Add cross-drive files to the issues section."""
        with self._lock:
            self._data["issues"]["cross_drive_files"] = files
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
