"""
submit_logger.py — Rich-based logging utilities for the Sulu Submit worker.

Design goal: "precision instrument" scrolling transcript.
- Rich-only (no Textual / curses). No fixed-screen dashboard.
- Calm, engineered, consistent: machined steel + dark glass.
- Color is meaning only (accent / ok / warn / err / muted).
- Unicode, but no emoji. Graceful ASCII fallback for legacy terminals.

This module intentionally keeps the API surface that the submit worker expects:
stage_header, trace_start/entry/summary, pack_start/entry/end, upload_*,
zip_* callbacks, version_update, fatal/prompt, etc.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Import shared utilities
from .worker_utils import count as _count, format_size

# Import TUI utilities from logger_utils
from .logger_utils import (
    # Rich library
    Table,
    Panel,
    Text,
    Align,
    box,
    # Glyphs
    ELLIPSIS,
    GLYPH_STAGE,
    GLYPH_OK,
    GLYPH_FAIL,
    GLYPH_WARN,
    GLYPH_INFO,
    GLYPH_ARROW,
    GLYPH_BULLET,
    GLYPH_HEX,
    GLYPH_LINK,
    # Theme and console
    SULU_PANEL_BOX,
    SULU_TABLE_BOX,
    get_logo_mark as _get_logo_mark,
    TranscriptLogger,
    # Data models
    TraceEntry,
    BLOCK_TYPE_NAMES,
)

# Submit logger


class SubmitLogger(TranscriptLogger):
    """
    Rich-based logger for submit worker with a consistently styled, scrolling transcript.

    Falls back to plain text if rich is not available.
    """

    def __init__(
        self,
        log_fn: Optional[Callable[[str], None]] = None,
        input_fn: Optional[Callable[[str, str], str]] = None,
    ):
        super().__init__(log_fn=log_fn, input_fn=input_fn)

        self._trace_entries: List[TraceEntry] = []
        self._pack_entries: List[Dict[str, Any]] = []
        self._zip_entries: List[Dict[str, Any]] = []

        # “last known” artifacts so the success screen can show them
        self._last_report_path: Optional[str] = None
        self._last_job_url: Optional[str] = None

    # Logo marks

    def logo_start(self) -> None:
        if self.console and Text is not None:
            self._print_logo(gradient_bg=True)
        else:
            width = self._get_width()
            logo_str = _get_logo_mark(width)
            self._log_fn("")
            if logo_str:
                self._log_fn(logo_str)
                self._log_fn("")
            self._log_fn("=== SULU SUBMITTER ===")
            self._log_fn("Render farm submission pipeline")

    # Stage headers

    def stage_header(
        self,
        stage_num: int,
        title: str,
        subtitle: str = "",
        details: Optional[List[str]] = None,
    ) -> None:
        if self.console and Text is not None:
            t = Text()
            t.append(f"{GLYPH_STAGE} ", style="sulu.accent")
            t.append("Stage ", style="sulu.dim")
            t.append(str(stage_num), style="sulu.dim")
            t.append(" — ", style="sulu.stroke_subtle")
            t.append(str(title), style="sulu.title")

            body = Text()
            if subtitle:
                body.append(subtitle, style="sulu.muted")
            if details:
                for line in details:
                    if body.plain:
                        body.append("\n")
                    body.append(f"{GLYPH_BULLET} ", style="sulu.dim")
                    body.append(str(line), style="sulu.dim")

            panel = self._panel(
                body if body.plain else "",
                title=t,
                border_style="sulu.stroke",
                style="sulu.panel",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("=" * 70)
            self._log_fn(f"> Stage {stage_num}: {title}")
            if subtitle:
                self._log_fn(f"  {subtitle}")
            if details:
                for line in details:
                    self._log_fn(f"  - {line}")
            self._log_fn("=" * 70)

    # Trace logging

    def trace_start(self, blend_path: str) -> None:
        self._trace_entries = []
        # Table will be printed at trace_summary

    def trace_entry(
        self,
        source_blend: str,
        block_type: str,
        block_name: str,
        found_file: str,
        status: str,
        error_msg: Optional[str] = None,
    ) -> None:
        entry = TraceEntry(
            source_blend, block_type, block_name, found_file, status, error_msg
        )
        self._trace_entries.append(entry)

    def _render_trace_table(self) -> None:
        """Render the accumulated trace entries as a proper Rich table."""
        if not self._trace_entries:
            return

        if self.console and Table is not None and Text is not None:
            table = Table(
                show_header=True,
                header_style="bold #A2A6AF",
                border_style="#3A3E48",
                box=box.ROUNDED if box else None,
                padding=(0, 1),
                expand=True,
            )
            table.add_column("Source file", style="#7E828B", no_wrap=True, ratio=2)
            table.add_column("Data block", style="#D8DEEC", no_wrap=True, ratio=2)
            table.add_column("Found file", style="#D8DEEC", no_wrap=True, ratio=3)
            table.add_column("", justify="center", width=3)

            for entry in self._trace_entries:
                type_name = BLOCK_TYPE_NAMES.get(entry.block_type, entry.block_type)
                block_text = Text()
                block_text.append(f"[{type_name}] ", style="sulu.dim")
                block_text.append(entry.block_name, style="sulu.fg")

                if entry.status == "ok":
                    resolved = Text(entry.found_file, style="sulu.fg")
                    status_icon = Text(GLYPH_OK, style="sulu.ok_b")
                elif entry.status == "missing":
                    resolved = Text(entry.found_file or "—", style="sulu.warn")
                    status_icon = Text(GLYPH_WARN, style="sulu.warn_b")
                else:
                    resolved = Text(entry.found_file or "—", style="sulu.err")
                    status_icon = Text(GLYPH_FAIL, style="sulu.err_b")

                table.add_row(entry.source_blend, block_text, resolved, status_icon)

            self.console.print()
            self.console.print(table)
        else:
            self._log_fn("")
            self._log_fn("Dependencies:")
            self._log_fn("-" * 70)
            for entry in self._trace_entries:
                type_name = BLOCK_TYPE_NAMES.get(entry.block_type, entry.block_type)
                status_str = (
                    GLYPH_OK
                    if entry.status == "ok"
                    else (GLYPH_WARN if entry.status == "missing" else GLYPH_FAIL)
                )
                self._log_fn(
                    f"  {entry.source_blend[:20]:<20} [{type_name}] {entry.block_name[:20]:<20} {entry.found_file[:30]:<30} {status_str}"
                )

    def trace_summary(
        self,
        total: int,
        missing: int,
        unreadable: int,
        project_root: Optional[str] = None,
        cross_drive: int = 0,
        warning_text: Optional[str] = None,
        *,
        cross_drive_excluded: bool = False,
        missing_files: Optional[List[str]] = None,
        unreadable_files: Optional[List[Tuple[str, str]]] = None,
        cross_drive_files: Optional[List[str]] = None,
        absolute_path_files: Optional[List[str]] = None,
        shorten_fn: Optional[Callable[[str], str]] = None,
        automatic_project_path: bool = True,
    ) -> None:
        """
        Print a summary panel after tracing dependencies.

        Args:
            cross_drive: Number of dependencies detected on a different drive.
            cross_drive_excluded: True when those dependencies will not be included
                (Project upload), False when they're still packable (Zip upload).
            missing_files: List of missing file paths.
            unreadable_files: List of (path, error_msg) tuples.
            cross_drive_files: List of cross-drive file paths.
            absolute_path_files: List of files with absolute paths in blend (won't work on farm).
            shorten_fn: Optional function to shorten paths for display.
            automatic_project_path: True if path was auto-detected, False if custom.
        """
        # Render the trace table first
        self._render_trace_table()

        _sh = shorten_fn or (lambda s: s)
        missing_files = missing_files or []
        unreadable_files = unreadable_files or []
        cross_drive_files = cross_drive_files or []
        absolute_path_files = absolute_path_files or []

        has_issues = bool(
            missing > 0 or unreadable > 0 or (cross_drive_excluded and cross_drive > 0) or absolute_path_files
        )

        if self.console and Text is not None and Table is not None:
            # Build the main body
            body = Table.grid(padding=(0, 0))
            body.add_column()

            # Project path (at the top)
            if project_root:
                path_label = (
                    "Detected project root path: "
                    if automatic_project_path
                    else "Using project root path: "
                )
                path_line = Text()
                path_line.append(path_label, style="sulu.muted")
                path_line.append(str(project_root), style="sulu.fg")
                body.add_row(path_line)
                body.add_row(Text(""))  # spacer

            # Found count (always green checkmark)
            found_line = Text()
            found_line.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            found_line.append(f"{_count(total, 'dependency')} found", style="sulu.ok")
            body.add_row(found_line)

            # Issues section with nested boxes
            if has_issues:
                body.add_row(Text(""))  # spacer

                # Missing dependencies
                if missing_files:
                    missing_title = Text()
                    missing_title.append(f"{GLYPH_WARN} ", style="sulu.warn_b")
                    missing_title.append(
                        f"{_count(len(missing_files), 'dependency')} missing",
                        style="sulu.warn",
                    )

                    missing_body = Text()
                    for i, p in enumerate(missing_files[:10]):  # limit to 10
                        if i > 0:
                            missing_body.append("\n")
                        missing_body.append(f"{GLYPH_BULLET} ", style="sulu.dim")
                        missing_body.append(_sh(str(p)), style="sulu.fg")
                    if len(missing_files) > 10:
                        missing_body.append("\n")
                        missing_body.append(
                            f"   {ELLIPSIS} and {len(missing_files) - 10} more",
                            style="sulu.dim",
                        )

                    missing_panel = self._panel(
                        missing_body,
                        title=missing_title,
                        border_style="sulu.warn",
                        style="sulu.well",
                        padding=(0, 1),
                    )
                    body.add_row(missing_panel)

                # Unreadable dependencies
                if unreadable_files:
                    if missing_files:
                        body.add_row(Text(""))  # spacer between boxes

                    unread_title = Text()
                    unread_title.append(f"{GLYPH_FAIL} ", style="sulu.err_b")
                    unread_title.append(
                        f"{_count(len(unreadable_files), 'dependency')} not readable",
                        style="sulu.err",
                    )

                    unread_body = Text()
                    for i, (p, err) in enumerate(unreadable_files[:10]):
                        if i > 0:
                            unread_body.append("\n")
                        unread_body.append(f"{GLYPH_BULLET} ", style="sulu.dim")
                        unread_body.append(_sh(str(p)), style="sulu.fg")
                        unread_body.append(f"\n   {err}", style="sulu.dim")
                    if len(unreadable_files) > 10:
                        unread_body.append("\n")
                        unread_body.append(
                            f"   {ELLIPSIS} and {len(unreadable_files) - 10} more",
                            style="sulu.dim",
                        )

                    unread_panel = self._panel(
                        unread_body,
                        title=unread_title,
                        border_style="sulu.err",
                        style="sulu.well",
                        padding=(0, 1),
                    )
                    body.add_row(unread_panel)

                # Cross-drive dependencies (only show if excluded)
                if cross_drive_excluded and cross_drive_files:
                    if missing_files or unreadable_files:
                        body.add_row(Text(""))  # spacer

                    xdrive_title = Text()
                    xdrive_title.append(f"{GLYPH_INFO} ", style="sulu.accent")
                    xdrive_title.append(
                        f"{_count(len(cross_drive_files), 'dependency')} on another drive (not included)",
                        style="sulu.muted",
                    )

                    xdrive_body = Text()
                    for i, p in enumerate(cross_drive_files[:10]):
                        if i > 0:
                            xdrive_body.append("\n")
                        xdrive_body.append(f"{GLYPH_BULLET} ", style="sulu.dim")
                        xdrive_body.append(_sh(str(p)), style="sulu.fg")
                    if len(cross_drive_files) > 10:
                        xdrive_body.append("\n")
                        xdrive_body.append(
                            f"   {ELLIPSIS} and {len(cross_drive_files) - 10} more",
                            style="sulu.dim",
                        )

                    xdrive_panel = self._panel(
                        xdrive_body,
                        title=xdrive_title,
                        border_style="sulu.stroke",
                        style="sulu.well",
                        padding=(0, 1),
                    )
                    body.add_row(xdrive_panel)

                # Absolute path dependencies (farm can't resolve these)
                if absolute_path_files:
                    if missing_files or unreadable_files or (cross_drive_excluded and cross_drive_files):
                        body.add_row(Text(""))  # spacer

                    abs_title = Text()
                    abs_title.append(f"{GLYPH_WARN} ", style="sulu.warn_b")
                    abs_title.append(
                        f"{_count(len(absolute_path_files), 'dependency')} with absolute paths (excluded)",
                        style="sulu.warn",
                    )

                    abs_body = Text()
                    for i, p in enumerate(absolute_path_files[:10]):
                        if i > 0:
                            abs_body.append("\n")
                        abs_body.append(f"{GLYPH_BULLET} ", style="sulu.dim")
                        abs_body.append(_sh(str(p)), style="sulu.fg")
                    if len(absolute_path_files) > 10:
                        abs_body.append("\n")
                        abs_body.append(
                            f"   {ELLIPSIS} and {len(absolute_path_files) - 10} more",
                            style="sulu.dim",
                        )

                    abs_panel = self._panel(
                        abs_body,
                        title=abs_title,
                        border_style="sulu.warn",
                        style="sulu.well",
                        padding=(0, 1),
                    )
                    body.add_row(abs_panel)

            # Warning/help text
            if warning_text:
                body.add_row(Text(""))  # spacer
                help_line = Text(str(warning_text), style="sulu.muted")
                body.add_row(help_line)

            border = "sulu.ok" if not has_issues else "sulu.warn"
            panel = self._panel(
                body,
                title=Text(f"{GLYPH_HEX}  Trace", style="sulu.dim"),
                border_style=border,
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            # Plain text fallback
            self._log_fn("")
            if project_root:
                path_label = (
                    "Detected project root path"
                    if automatic_project_path
                    else "Using project root path"
                )
                self._log_fn(f"{path_label}: {project_root}")
            self._log_fn(
                f"Trace: {_count(total, 'dependency')} found (missing={missing}, unreadable={unreadable}, other_drives={cross_drive})"
            )
            if missing_files:
                self._log_fn(f"Missing dependencies ({len(missing_files)}):")
                for p in missing_files[:10]:
                    self._log_fn(f"  - {_sh(str(p))}")
                if len(missing_files) > 10:
                    self._log_fn(f"  ... and {len(missing_files) - 10} more")
            if unreadable_files:
                self._log_fn(f"Dependencies not readable ({len(unreadable_files)}):")
                for p, err in unreadable_files[:10]:
                    self._log_fn(f"  - {_sh(str(p))}: {err}")
                if len(unreadable_files) > 10:
                    self._log_fn(f"  ... and {len(unreadable_files) - 10} more")
            if cross_drive_excluded and cross_drive_files:
                self._log_fn(
                    f"Dependencies on other drives ({len(cross_drive_files)}):"
                )
                for p in cross_drive_files[:10]:
                    self._log_fn(f"  - {_sh(str(p))}")
                if len(cross_drive_files) > 10:
                    self._log_fn(f"  ... and {len(cross_drive_files) - 10} more")
            if absolute_path_files:
                self._log_fn(
                    f"Dependencies with absolute paths ({len(absolute_path_files)}) - excluded:"
                )
                for p in absolute_path_files[:10]:
                    self._log_fn(f"  - {_sh(str(p))}")
                if len(absolute_path_files) > 10:
                    self._log_fn(f"  ... and {len(absolute_path_files) - 10} more")
            if warning_text:
                self._log_fn(warning_text)

    # Packing logging

    def pack_start(self) -> None:
        self._pack_entries = []
        # Table will be printed at pack_end

    def pack_entry(
        self,
        index: int,
        filepath: str,
        size: Optional[int] = None,
        status: str = "ok",
    ) -> None:
        self._pack_entries.append(
            {"index": index, "filepath": filepath, "size": size, "status": status}
        )

    def _render_pack_table(self) -> None:
        """Render the accumulated pack entries as a proper Rich table."""
        if not self._pack_entries:
            return

        if self.console and Table is not None and Text is not None:
            table = Table(
                show_header=True,
                header_style="bold #A2A6AF",
                border_style="#3A3E48",
                box=box.ROUNDED if box else None,
                padding=(0, 1),
                expand=True,
            )
            table.add_column("File", style="#D8DEEC", no_wrap=True, ratio=4)
            table.add_column("Size", style="#7E828B", justify="right", width=12)
            table.add_column("", justify="center", width=3)

            for entry in self._pack_entries:
                filename = Path(entry["filepath"]).name
                size_str = format_size(entry["size"]) if entry["size"] else "—"

                if entry["status"] == "ok":
                    file_text = Text(filename, style="sulu.fg")
                    status_icon = Text(GLYPH_OK, style="sulu.ok_b")
                elif entry["status"] == "missing":
                    file_text = Text(filename, style="sulu.warn")
                    status_icon = Text(GLYPH_WARN, style="sulu.warn_b")
                else:
                    file_text = Text(filename, style="sulu.err")
                    status_icon = Text(GLYPH_FAIL, style="sulu.err_b")

                table.add_row(file_text, size_str, status_icon)

            self.console.print()
            self.console.print(table)
        else:
            self._log_fn("")
            self._log_fn("Manifest:")
            self._log_fn("-" * 70)
            for entry in self._pack_entries:
                filename = Path(entry["filepath"]).name
                size_str = format_size(entry["size"]) if entry["size"] else ""
                status_str = (
                    GLYPH_OK
                    if entry["status"] == "ok"
                    else (GLYPH_WARN if entry["status"] == "missing" else GLYPH_FAIL)
                )
                self._log_fn(f"  {filename:<50} {size_str:>10} {status_str:>3}")

    def pack_end(
        self,
        ok_count: int,
        total_size: int = 0,
        title: str = "Manifest complete",
    ) -> None:
        # Render the pack table first
        self._render_pack_table()

        if self.console and Text is not None:
            body = Text()
            body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            body.append(_count(ok_count, "file"), style="sulu.fg")
            body.append("  ·  ", style="sulu.stroke_subtle")
            body.append(f"{format_size(total_size)}", style="sulu.muted")

            panel = self._panel(
                body,
                title=Text(f"{GLYPH_HEX}  {title}", style="sulu.dim"),
                border_style="sulu.ok",
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(
                f"{title}: {_count(ok_count, 'file')}, {format_size(total_size)}"
            )

    # ZIP callbacks (BAT)

    def zip_start(self, total_files: int, total_bytes: int) -> None:
        self._zip_entries: List[Dict[str, Any]] = []
        # Table will be printed at zip_done

    def zip_entry(
        self, index: int, total: int, arcname: str, size: int, method: str
    ) -> None:
        self._zip_entries.append(
            {
                "arcname": arcname,
                "size": size,
                "method": method,
            }
        )

    def _render_zip_table(self) -> None:
        """Render the accumulated zip entries as a proper Rich table."""
        if not hasattr(self, "_zip_entries") or not self._zip_entries:
            return

        if self.console and Table is not None and Text is not None:
            table = Table(
                show_header=True,
                header_style="bold #A2A6AF",
                border_style="#3A3E48",
                box=box.ROUNDED if box else None,
                padding=(0, 1),
                expand=True,
            )
            table.add_column("File", style="#D8DEEC", no_wrap=True, ratio=4)
            table.add_column("Size", style="#7E828B", justify="right", width=12)
            table.add_column("Mode", style="#A2A6AF", justify="right", width=16)

            for entry in self._zip_entries:
                size_str = format_size(entry["size"]) if entry["size"] else "—"
                table.add_row(entry["arcname"], size_str, entry["method"])

            self.console.print()
            self.console.print(table)
        else:
            self._log_fn("")
            self._log_fn("Archive:")
            self._log_fn("-" * 70)
            for entry in self._zip_entries:
                size_str = format_size(entry["size"]) if entry["size"] else ""
                self._log_fn(
                    f"  {entry['arcname']:<42} {size_str:>10} {entry['method']:>16}"
                )

    def zip_done(
        self, zippath: str, total_files: int, total_bytes: int, elapsed: float
    ) -> None:
        # Render the zip table first
        self._render_zip_table()

        if self.console and Text is not None:
            body = Text()
            body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            body.append(_count(total_files, "file"), style="sulu.fg")
            body.append("  ·  ", style="sulu.stroke_subtle")
            body.append(f"{format_size(total_bytes)}", style="sulu.muted")
            body.append("  ·  ", style="sulu.stroke_subtle")
            body.append(f"{elapsed:.1f}s", style="sulu.muted")

            panel = self._panel(
                body,
                title=Text(f"{GLYPH_HEX}  Archive ready", style="sulu.dim"),
                border_style="sulu.ok",
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(
                f"Archive ready: {_count(total_files, 'file')}, {format_size(total_bytes)}, {elapsed:.1f}s"
            )

    # Upload and transfer

    def upload_start(self, total: int) -> None:
        self._last_progress_time = 0.0
        self._progress_bar_width = 0
        self._inline_progress_active = False
        self._stop_live_progress()

    def upload_step(
        self, step: int, total_steps: int, title: str, detail: str = ""
    ) -> None:
        self._stop_live_progress()

        self._transfer_cur = 0
        self._transfer_total = 0
        self._progress_bar_width = self._compute_progress_bar_width()
        self._last_progress_time = 0.0

        if self.console and Text is not None:
            self.console.print()
            step_str = f"[{step}/{total_steps}]"
            header = Text()
            header.append(f"  {step_str} ", style="sulu.accent")
            header.append(title, style="sulu.title")
            if detail:
                header.append("  ", style="sulu.stroke_subtle")
                header.append(detail, style="sulu.dim")
            self.console.print(header)
        else:
            self._log_fn(f"\n[{step}/{total_steps}] {title} {detail}")

    def upload_complete(self, title: str) -> None:
        if self.console and Text is not None:
            self._stop_live_progress()

            body = Text()
            body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            body.append(title, style="sulu.fg")
            if self._transfer_total > 0:
                body.append("  ", style="sulu.stroke_subtle")
                body.append(f"{format_size(self._transfer_total)}", style="sulu.dim")

            panel = self._panel(
                body,
                border_style="sulu.ok",
                style="sulu.well",
                padding=(0, 1),
            )
            self.console.print(panel)
        else:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._log_fn(f"  {GLYPH_OK} {title}")

    # General messages

    def report_info(self, report_path: str) -> None:
        """Display the diagnostic report location (and remember it for the success screen)."""
        self._last_report_path = report_path
        if self.console:
            self.console.print(
                f"[sulu.dim]{GLYPH_INFO}[/] [sulu.muted]Diagnostic report: {report_path}[/]"
            )
        else:
            self._log_fn(f"Diagnostic report: {report_path}")

    # Success screen and prompt

    def _success_action_block(self, *, have_job: bool, have_report: bool) -> Any:
        """
        Build the action options that live INSIDE the success panel.
        """
        if Text is None or Table is None:
            return ""

        # Chip styles
        chip_primary = "bold #15171E on #1EA138"  # green
        chip_accent = "bold #15171E on #5250FF"  # sulu accent blue
        chip_neutral = "bold #D8DEEC on #24272E"  # control surface

        def chip(label: str, style: str) -> Text:
            t = Text(f" {label} ", style=style)
            t.no_wrap = True
            t.overflow = "crop"
            return t

        row = Text()
        row.justify = "center"

        first = True
        if have_job:
            row.append_text(chip("J", chip_primary))
            row.append(" Job page", style="sulu.fg")
            first = False

        if have_report:
            if not first:
                row.append("   ", style="sulu.dim")
            row.append_text(chip("R", chip_accent))
            row.append(" Diagnostic reports", style="sulu.fg")
            first = False

        if not first:
            row.append("   ", style="sulu.dim")
        row.append_text(chip("ENTER", chip_neutral))
        row.append(" Close", style="sulu.muted")

        return row

    def logo_end(
        self,
        job_id: Optional[str] = None,
        elapsed: Optional[float] = None,
        job_url: Optional[str] = None,
        report_path: Optional[str] = None,
    ) -> str:
        """
        Success screen with logo and action options.

        Returns:
            "j" (open job page), "r" (open diagnostic report), or "c" (close).
        """
        # Ensure we don't leave any live progress region running
        self._stop_live_progress()

        # Prefer the latest known values if not provided
        if job_url:
            self._last_job_url = job_url
        job_url = job_url or self._last_job_url

        if report_path:
            self._last_report_path = report_path
        report_path = report_path or self._last_report_path

        have_job = bool(job_url)
        have_report = bool(report_path)

        if (
            self.console
            and Text is not None
            and Panel is not None
            and Table is not None
            and Align is not None
        ):
            self.console.print()

            logo_renderable = self._centered_logo_grid(_get_logo_mark)

            headline = Text("Submission complete", style="sulu.ok_b")
            headline.justify = "center"

            subtitle = Text(
                "Your job is queued. Rendering begins shortly.",
                style="sulu.muted",
            )
            subtitle.justify = "center"

            action_block = self._success_action_block(
                have_job=have_job, have_report=have_report
            )

            body = Table.grid(padding=(0, 0))
            body.expand = True
            body.add_column(justify="center")

            if logo_renderable is not None:
                body.add_row(logo_renderable)

            body.add_row(Text(""))
            body.add_row(headline)
            body.add_row(subtitle)
            body.add_row(Text(""))
            body.add_row(action_block)

            panel = self._panel(
                body,
                border_style="sulu.ok",
                style="sulu.panel",
                padding=(1, 2),
            )
            self.console.print(panel)

            if not self._can_prompt():
                return "c"

            prompt = Text()
            prompt.append("  ❯ ", style="sulu.ok_b")
            self.console.print(prompt, end="")

            try:
                raw = self._input_fn("", "")
            except (EOFError, KeyboardInterrupt):
                return "c"
            except Exception:
                return "c"

            s = (raw or "").strip().lower()
            if not s:
                return "c"

            # Alias handling
            if s in ("j", "job", "o", "open"):
                return "j" if have_job else "c"
            if s in ("r", "report", "reports", "diagnostic"):
                return "r" if have_report else "c"
            if s in ("c", "close", "q", "quit", "x"):
                return "c"

            return "c"

        # Plain text fallback
        self._log_fn("")
        self._log_fn("Submission complete")
        self._log_fn("Your job is queued. Rendering begins shortly.")
        self._log_fn("")
        if have_job:
            self._log_fn("  [J] Job page")
        if have_report:
            self._log_fn("  [R] Diagnostic reports")
        self._log_fn("  [Enter] Close")

        if not self._can_prompt():
            return "c"

        try:
            raw = self._input_fn("> ", "")
        except (EOFError, KeyboardInterrupt):
            return "c"
        except Exception:
            return "c"

        s = (raw or "").strip().lower()
        if not s:
            return "c"
        if s in ("j", "job", "o", "open"):
            return "j" if have_job else "c"
        if s in ("r", "report", "reports", "diagnostic"):
            return "r" if have_report else "c"
        return "c"

    # Chat-style prompts

    def ask_choice(
        self,
        question: str,
        options: List[Tuple[str, str, str]],
        default: str = "",
    ) -> str:
        if self.console and Text is not None and Panel is not None:
            self.console.print()

            body = Text()
            body.append(question, style="sulu.fg")
            body.append("\n")

            for i, (key, label, desc) in enumerate(options):
                is_default = key.lower() == default.lower()
                key_style = (
                    "bold #5250FF on #2C2F36"
                    if is_default
                    else "bold #A2A6AF on #24272E"
                )

                body.append(f" {key.upper()} ", style=key_style)
                body.append(" ", style="sulu.dim")
                body.append(label, style="sulu.fg bold" if is_default else "sulu.muted")
                if i < len(options) - 1:
                    body.append("   ", style="sulu.dim")

            sender = Text()
            sender.append("SU", style="bold #5250FF")
            sender.append("⡾", style="#757EFF")
            sender.append("LU", style="bold #5250FF")

            panel = Panel(
                body,
                title=sender,
                title_align="left",
                border_style="sulu.accent",
                padding=(0, 1),
                box=SULU_PANEL_BOX,
                style="sulu.panel",
            )
            self.console.print(panel)

            prompt_text = Text()
            prompt_text.append(" ❯ ", style="sulu.accent")
            if default:
                prompt_text.append(f"[{default}] ", style="sulu.dim")
            self.console.print(prompt_text, end="")

            try:
                answer = self._input_fn("", default)
                answer = answer.strip().lower() if answer.strip() else default.lower()
            except (EOFError, KeyboardInterrupt):
                answer = default.lower()

            return answer
        else:
            self._log_fn("")
            self._log_fn(f"[SU⡾LU] {question}")
            opts = "  ".join(f"[{k}] {lbl}" for k, lbl, _ in options)
            self._log_fn(f"  {opts}")

            prompt_str = f"[{default}] " if default else ""
            try:
                answer = self._input_fn(f" > {prompt_str}", default)
                answer = answer.strip().lower() if answer.strip() else default.lower()
            except (EOFError, KeyboardInterrupt):
                answer = default.lower()

            return answer

    # Prompt and exit

    def prompt(self, question: str, default: str = "") -> str:
        if self.console and Text is not None and Panel is not None:
            self.console.print()

            body = Text(question, style="sulu.fg")

            sender = Text()
            sender.append("SU", style="bold #5250FF")
            sender.append("⡾", style="#757EFF")
            sender.append("LU", style="bold #5250FF")

            panel = Panel(
                body,
                title=sender,
                title_align="left",
                border_style="sulu.accent",
                padding=(0, 2),
                box=SULU_PANEL_BOX,
                style="sulu.panel",
            )
            self.console.print(panel)

            prompt_text = Text()
            prompt_text.append("  ❯ ", style="sulu.accent")
            self.console.print(prompt_text, end="")

            return self._input_fn("", default)
        else:
            self._log_fn(f"[SU⡾LU] {question}")
            return self._input_fn("", default)

    def info_exit(self, message: str) -> None:
        if self.console and Panel is not None and Text is not None:
            panel = self._panel(
                Text(str(message), style="sulu.fg"),
                title=Text(f"{GLYPH_INFO}  Info", style="sulu.muted"),
                border_style="sulu.accent",
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn(f"[i] {message}")
        try:
            self._input_fn("\nPress Enter to close.", "")
        except Exception:
            pass
        sys.exit(0)

    def version_update(
        self,
        url: str,
        instructions: List[str],
        prompt: Optional[str] = None,
        options: Optional[List[Tuple[str, str, str]]] = None,
        default: str = "n",
    ) -> str:
        """
        Show update available panel with optional integrated prompt.

        Returns the selected option key, or empty string if no prompt.
        """
        if (
            self.console
            and Panel is not None
            and Text is not None
            and Table is not None
        ):
            body = Table.grid(padding=(0, 0))
            body.add_column()

            # Instructions
            for line in instructions:
                instr = Text()
                instr.append(f"{GLYPH_BULLET} ", style="sulu.dim")
                instr.append(str(line), style="sulu.fg")
                body.add_row(instr)

            body.add_row(Text(""))

            # URL on its own line
            url_line = Text()
            url_line.append(f"{GLYPH_ARROW} ", style="sulu.dim")
            url_line.append(str(url), style="sulu.accent")
            body.add_row(url_line)

            # Prompt and options if provided
            if prompt and options:
                body.add_row(Text(""))

                prompt_text = Text(str(prompt), style="sulu.title")
                body.add_row(prompt_text)
                body.add_row(Text(""))

                # Chip styles
                chip_primary = "bold #15171E on #5250FF"
                chip_neutral = "bold #D8DEEC on #24272E"

                row = Text()
                for i, (key, label, desc) in enumerate(options):
                    is_default = key.lower() == default.lower()
                    style = chip_primary if is_default else chip_neutral
                    if i > 0:
                        row.append("   ", style="sulu.dim")
                    row.append(f" {key.upper()} ", style=style)
                    row.append(
                        f" {label}", style="sulu.fg" if is_default else "sulu.muted"
                    )
                body.add_row(row)

            panel = self._panel(
                body,
                title=Text(f"{GLYPH_INFO}  Update available", style="sulu.accent"),
                border_style="sulu.accent",
                style="sulu.panel",
            )
            self.console.print(panel)

            # Get input if prompt was provided
            if prompt and options:
                prompt_cursor = Text()
                prompt_cursor.append("  ❯ ", style="sulu.accent")
                if default:
                    prompt_cursor.append(f"[{default}] ", style="sulu.dim")
                self.console.print(prompt_cursor, end="")

                try:
                    answer = self._input_fn("", default)
                    answer = (
                        answer.strip().lower() if answer.strip() else default.lower()
                    )
                except (EOFError, KeyboardInterrupt):
                    answer = default.lower()
                return answer

            return ""
        else:
            self._log_fn(f"Update available: {url}")
            for line in instructions:
                self._log_fn(f" - {line}")

            if prompt and options:
                self._log_fn("")
                self._log_fn(prompt)
                opts = "  ".join(f"[{k}] {lbl}" for k, lbl, _ in options)
                self._log_fn(f"  {opts}")
                try:
                    answer = self._input_fn(f" > [{default}] ", default)
                    answer = (
                        answer.strip().lower() if answer.strip() else default.lower()
                    )
                except (EOFError, KeyboardInterrupt):
                    answer = default.lower()
                return answer

            return ""

    # Job completion

    def job_complete(self, web_url: str) -> None:
        """Log that the job page was opened in the browser (and remember it)."""
        self._last_job_url = web_url
        if self.console and Panel is not None and Text is not None:
            body = Text()
            body.append(str(web_url), style="sulu.link")
            panel = self._panel(
                body,
                title=Text(f"{GLYPH_LINK}  Opened in browser", style="sulu.muted"),
                border_style="sulu.ok",
                style="sulu.panel",
            )
            self.console.print(panel)
        else:
            self._log_fn(f"Opened in browser: {web_url}")

    # Test and no-submit reports

    def test_report(
        self,
        blend_path: str,
        dep_count: int,
        project_root: str,
        same_drive: int,
        cross_drive: int,
        by_ext: Dict[str, int],
        total_size: int,
        missing: List[str],
        unreadable: List[Tuple[str, str]],
        cross_drive_files: List[str],
        upload_type: str,
        report_path: Optional[str] = None,
        shorten_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        _sh = shorten_fn or (lambda s: s)
        blend_size = 0
        try:
            blend_size = os.path.getsize(blend_path)
        except Exception:
            pass

        if self.console and Panel is not None and Text is not None:
            panel = self._panel(
                Text(f"Upload type: {upload_type}", style="sulu.fg"),
                title=Text(f"{GLYPH_INFO}  Test mode", style="sulu.muted"),
                border_style="sulu.warn",
                style="sulu.panel",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn(f"TEST MODE — {upload_type}")

        self.info(f"Blend: {Path(blend_path).name} ({format_size(blend_size)})")
        self.info(f"Dependencies: {dep_count}")
        self.info(f"Project path: {_sh(project_root)}")
        self.info(f"Same drive: {same_drive}  ·  Other drives: {cross_drive}")

        if self.console and Table is not None:
            table = Table(
                title="Dependency breakdown",
                show_header=True,
                header_style="sulu.muted",
                border_style="sulu.stroke_subtle",
                box=SULU_TABLE_BOX,
                padding=(0, 1),
                show_edge=False,
                expand=False,
            )
            table.add_column("Ext", style="sulu.fg", no_wrap=True)
            table.add_column("Count", justify="right", style="sulu.muted", no_wrap=True)
            for ext, cnt in sorted(by_ext.items(), key=lambda x: -x[1]):
                table.add_row(ext, str(cnt))
            table.add_row("", "")
            table.add_row("Total", format_size(total_size))
            self.console.print()
            self.console.print(table)
        else:
            self._log_fn("Dependency breakdown:")
            for ext, cnt in sorted(by_ext.items(), key=lambda x: -x[1]):
                self._log_fn(f"  {ext:12} : {cnt:4} dependencies")
            self._log_fn(f"  Total size: {format_size(total_size)}")

        has_issues = bool(missing or unreadable or cross_drive_files)
        if has_issues:
            lines: List[str] = []
            if missing:
                lines.append(f"Missing ({len(missing)}):")
                for p in missing:
                    lines.append(f"  - {_sh(p)}")
            if unreadable:
                if lines:
                    lines.append("")
                lines.append(f"Not readable ({len(unreadable)}):")
                for p, err in unreadable:
                    lines.append(f"  - {_sh(p)}")
                    lines.append(f"    {err}")
            if cross_drive_files:
                if lines:
                    lines.append("")
                lines.append(f"Other drives ({len(cross_drive_files)}):")
                for p in cross_drive_files:
                    lines.append(f"  - {_sh(p)}")

            self.warn_block("\n".join(lines), severity="warning")

        if report_path:
            self.report_info(report_path)

        self.warn_block(
            "Test mode. No upload or job registration.",
            severity="warning",
        )

    def no_submit_report(
        self,
        upload_type: str,
        common_path: str = "",
        rel_manifest_count: int = 0,
        main_blend_s3: str = "",
        zip_file: str = "",
        zip_size: int = 0,
        required_storage: int = 0,
    ) -> None:
        lines: List[str] = [
            "Packing complete.",
            f"Upload type: {upload_type}",
        ]
        if upload_type == "PROJECT":
            lines.append(f"Project path: {common_path}")
            lines.append(f"Dependencies: {rel_manifest_count}")
            lines.append(f"Main blend key: {main_blend_s3}")
        else:
            lines.append(f"Archive: {zip_file}")
            if zip_size:
                lines.append(f"Archive size: {format_size(zip_size)}")
        lines.append(f"Storage estimate: {format_size(required_storage)}")
        lines.append("")
        lines.append("Upload and job registration skipped.")

        if self.console and Panel is not None and Text is not None:
            panel = self._panel(
                Text("\n".join(lines), style="sulu.fg"),
                title=Text(f"{GLYPH_INFO}  No-submit mode", style="sulu.muted"),
                border_style="sulu.warn",
                style="sulu.panel",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("NO-SUBMIT MODE")
            for line in lines:
                self._log_fn(f"  {line}")


# Factory


def create_logger(
    log_fn: Optional[Callable[[str], None]] = None,
    input_fn: Optional[Callable[[str, str], str]] = None,
) -> SubmitLogger:
    return SubmitLogger(log_fn, input_fn=input_fn)
