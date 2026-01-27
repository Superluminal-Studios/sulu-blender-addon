"""
tui_rclone.py - rclone wrapper with TUI progress reporting.

Wraps run_rclone() to feed upload progress to the TUI.
"""
from __future__ import annotations

import subprocess
import sys
import json
from collections import deque
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .submit_tui import SubmitTUI


def run_rclone_with_tui(
    base: List[str],
    verb: str,
    src: str,
    dst: str,
    extra: Optional[List[str]],
    tui: "SubmitTUI",
    phase: str = "upload",
    file_count: int = 1,
    logger=None,
) -> None:
    """
    Run rclone while feeding progress to the TUI.

    Args:
        base: Base rclone command (exe path + auth flags)
        verb: rclone verb (copy, move, copyto, moveto, etc.)
        src: Source path
        dst: Destination path
        extra: Extra flags
        tui: The TUI instance
        phase: Phase label for TUI ("blend", "deps", "manifest", "addons")
        file_count: Expected number of files
        logger: Optional logger function

    Raises:
        RuntimeError: If rclone fails
    """
    import os
    import re
    import tempfile
    import shutil

    # Try to import from the transfers module
    try:
        from ..transfers.rclone import (
            _rclone_supports_flag,
            _classify_failure,
            _log_or_print,
        )
    except ImportError:
        # Fallback definitions
        def _rclone_supports_flag(exe, flag):
            return False

        def _classify_failure(verb, src, dst, code, lines):
            return ("unknown", f"rclone failed (exit code {code})")

        def _log_or_print(logger, msg):
            if logger:
                logger(msg)
            else:
                print(msg)

    extra = list(extra or [])
    src = str(src).replace("\\", "/")
    dst = str(dst).replace("\\", "/")

    if not isinstance(base, (list, tuple)) or not base:
        raise RuntimeError("Invalid rclone base command.")

    rclone_exe = str(base[0])

    # Auto-upgrade --files-from to --files-from-raw if supported
    if "--files-from" in extra and _rclone_supports_flag(rclone_exe, "--files-from-raw"):
        upgraded = []
        i = 0
        while i < len(extra):
            if extra[i] == "--files-from":
                upgraded.append("--files-from-raw")
                if i + 1 < len(extra):
                    upgraded.append(extra[i + 1])
                    i += 2
                    continue
            upgraded.append(extra[i])
            i += 1
        extra = upgraded

    # Add local unicode normalization if supported
    if _rclone_supports_flag(rclone_exe, "--local-unicode-normalization"):
        if "--local-unicode-normalization" not in extra:
            extra = ["--local-unicode-normalization"] + extra

    cmd = [
        base[0],
        verb,
        src,
        dst,
        *extra,
        "--stats=0.1s",
        "--use-json-log",
        "--stats-log-level",
        "NOTICE",
        *base[1:],
    ]

    # Estimate initial file size
    initial_size = 0
    try:
        if os.path.isfile(src):
            initial_size = os.path.getsize(src)
        elif os.path.isdir(src):
            for root, dirs, files in os.walk(src):
                for f in files:
                    try:
                        initial_size += os.path.getsize(os.path.join(root, f))
                    except:
                        pass
    except:
        pass

    # Start upload phase in TUI
    tui.upload_start(phase=phase, total_bytes=initial_size, total_files=file_count)

    # Keep tail of error lines
    tail = deque(maxlen=120)

    def _remember_line(s: str) -> None:
        s = str(s or "").strip()
        if s:
            tail.append(s)

    # Extract bytes from rclone JSON stats
    def _bytes_from_stats(obj):
        s = obj.get("stats")
        if not s:
            return None
        cur = s.get("bytes")
        tot = s.get("totalBytes") or 0
        if cur is None:
            return None
        return int(cur), int(tot)

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        last_bytes = 0
        real_total = initial_size

        for raw in proc.stdout:
            fragments = raw.rstrip("\n").split("\r")
            for frag in fragments:
                line = frag.strip()
                if not line:
                    continue

                obj = None
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    _remember_line(line)
                    continue

                if obj is not None and isinstance(obj, dict):
                    out = _bytes_from_stats(obj)
                    if out is not None:
                        cur, tot = out

                        # Update real total when known
                        if tot > 0 and tot > real_total:
                            real_total = tot

                        # Update TUI
                        tui.upload_progress(
                            bytes_transferred=cur,
                            bytes_total=real_total,
                        )
                        last_bytes = cur
                    else:
                        # Non-stats JSON line
                        _remember_line(line)
                else:
                    _remember_line(line)

        proc.wait()
        exit_code = proc.returncode

    if exit_code != 0:
        cat, msg = _classify_failure(verb, src, dst, exit_code, list(tail))
        raise RuntimeError(msg)

    # Mark file and phase as done
    tui.upload_file_done()
    tui.upload_phase_done(phase)


def create_rclone_runner(tui: "SubmitTUI"):
    """
    Create a run_rclone wrapper that feeds the TUI.

    Returns a function with the same signature as run_rclone.
    """

    def run_rclone(
        base,
        verb,
        src,
        dst,
        extra=None,
        logger=None,
        file_count=None,
    ):
        # Determine phase from verb/src/dst
        src_lower = str(src).lower()
        dst_lower = str(dst).lower()

        # Addons upload
        if "addons" in dst_lower:
            phase = "addons"
        # ZIP mode: moving a .zip file
        elif src_lower.endswith(".zip") and verb in ("move", "moveto"):
            phase = "zip"
        # PROJECT mode: main blend file
        elif verb in ("copyto", "moveto") and ".blend" in src_lower:
            phase = "blend"
        # PROJECT mode: dependencies (copy with --files-from)
        elif verb == "copy" and extra and any("--files-from" in str(e) for e in extra):
            phase = "deps"
        # Fallback: use first available phase
        else:
            # Check what phases are available in the TUI
            available = list(tui.state.upload.phase_order)
            phase = available[0] if available else "upload"

        return run_rclone_with_tui(
            base=base,
            verb=verb,
            src=src,
            dst=dst,
            extra=extra,
            tui=tui,
            phase=phase,
            file_count=file_count or 1,
            logger=logger,
        )

    return run_rclone
