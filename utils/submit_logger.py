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
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Import vendored rich library (local to addon) with fallbacks.
RICH_AVAILABLE = False
Console = None
Table = None
Panel = None
Text = None
Style = None
Rule = None
Theme = None
Align = None
Live = None
box = None


def _try_import_rich() -> None:
    """Try to import rich from various locations."""
    global RICH_AVAILABLE, Console, Table, Panel, Text, Style, Rule, Theme, Align, Live, box

    # Method 1: Relative import (works when imported as part of package)
    try:
        from ..rich.console import Console as _Console
        from ..rich.panel import Panel as _Panel
        from ..rich.table import Table as _Table
        from ..rich.text import Text as _Text
        from ..rich.style import Style as _Style
        from ..rich.rule import Rule as _Rule
        from ..rich.theme import Theme as _Theme
        from ..rich.align import Align as _Align
        from ..rich.live import Live as _Live
        from ..rich import box as _box

        Console = _Console
        Panel = _Panel
        Table = _Table
        Text = _Text
        Style = _Style
        Rule = _Rule
        Theme = _Theme
        Align = _Align
        Live = _Live
        box = _box
        RICH_AVAILABLE = True
        return
    except (ImportError, ValueError):
        pass

    # Method 2: Try importing from addon's rich directory directly
    try:
        addon_dir = Path(__file__).parent.parent
        rich_dir = addon_dir / "rich"
        if rich_dir.exists() and str(addon_dir) not in sys.path:
            sys.path.insert(0, str(addon_dir))

        import rich.console
        import rich.panel
        import rich.table
        import rich.text
        import rich.style
        import rich.rule
        import rich.theme
        import rich.align
        import rich.live
        import rich.box

        Console = rich.console.Console
        Panel = rich.panel.Panel
        Table = rich.table.Table
        Text = rich.text.Text
        Style = rich.style.Style
        Rule = rich.rule.Rule
        Theme = rich.theme.Theme
        Align = rich.align.Align
        Live = rich.live.Live
        box = rich.box
        RICH_AVAILABLE = True
        return
    except ImportError:
        pass

    # Method 3: System rich as last resort
    try:
        from rich.console import Console as _Console
        from rich.panel import Panel as _Panel
        from rich.table import Table as _Table
        from rich.text import Text as _Text
        from rich.style import Style as _Style
        from rich.rule import Rule as _Rule
        from rich.theme import Theme as _Theme
        from rich.align import Align as _Align
        from rich.live import Live as _Live
        from rich import box as _box

        Console = _Console
        Panel = _Panel
        Table = _Table
        Text = _Text
        Style = _Style
        Rule = _Rule
        Theme = _Theme
        Align = _Align
        Live = _Live
        box = _box
        RICH_AVAILABLE = True
        return
    except ImportError:
        pass


_try_import_rich()

# ─────────────────────────── Unicode + glyphs ───────────────────────────

def _supports_unicode() -> bool:
    """Best-effort check whether we should emit Unicode glyphs."""
    try:
        encoding = sys.stdout.encoding or ""
        if "utf" in encoding.lower():
            return True
    except Exception:
        pass

    # Explicit override
    if "utf" in os.environ.get("PYTHONIOENCODING", "").lower():
        return True

    # Windows: allow Unicode in modern terminals (Windows Terminal, VSCode terminal, etc.)
    if sys.platform == "win32":
        if os.environ.get("WT_SESSION"):
            return True
        if os.environ.get("TERM_PROGRAM", "").lower() in ("vscode",):
            return True
        # legacy console: stay conservative
        return False

    return True


_UNICODE = _supports_unicode()

# No emoji. Unicode symbols only (with ASCII-ish fallback).
GLYPH_STAGE = "▸" if _UNICODE else ">"
GLYPH_OK = "✓" if _UNICODE else "OK"
GLYPH_FAIL = "✕" if _UNICODE else "X"
GLYPH_WARN = "!"  # ASCII is fine and universally safe
GLYPH_INFO = "ⓘ" if _UNICODE else "i"
GLYPH_ARROW = "→" if _UNICODE else "->"
GLYPH_BULLET = "•" if _UNICODE else "-"
GLYPH_SEAM = "┆" if _UNICODE else "|"
GLYPH_DASH = "┄" if _UNICODE else "-"

# Small “hardware-ish” marks for panels
GLYPH_HEX = "⬡" if _UNICODE else "#"
GLYPH_LINK = "⟐" if _UNICODE else "*"


# ─────────────────────────── Sulu terminal theme ───────────────────────────

def _build_sulu_theme():
    if Theme is None:
        return None
    # These are terminal-appropriate matches of the CSS semantic theme.
    return Theme(
        {
            # Text roles
            "sulu.fg": "#D8DEEC",
            "sulu.muted": "#A2A6AF",
            "sulu.dim": "#7E828B",

            # Meaning colors (color = meaning only)
            "sulu.accent": "#5250FF",
            "sulu.ring": "#757EFF",
            "sulu.ok": "#1EA138",
            "sulu.warn": "#E17100",
            "sulu.err": "#FF2056",

            # Strokes / seams
            "sulu.stroke": "#454A56",
            "sulu.stroke_subtle": "#3A3E48",
            "sulu.stroke_strong": "#545A69",

            # Surfaces (used sparingly for panels)
            "sulu.panel": "on #1E2027",
            "sulu.well": "on #21232B",
            "sulu.control": "on #24272E",
            "sulu.overlay": "on #2C2F36",

            # Composite helpers
            "sulu.title": "bold #D8DEEC",
            "sulu.stage": "bold #5250FF",
            "sulu.ok_b": "bold #1EA138",
            "sulu.warn_b": "bold #E17100",
            "sulu.err_b": "bold #FF2056",
            "sulu.link": "underline #5250FF",

            # Pills / tags
            "sulu.pill": "#A2A6AF on #24272E",

        }
    )


SULU_TUI_THEME = _build_sulu_theme()

# Geometry (machined: square, minimal)
SULU_PANEL_BOX = getattr(box, "SQUARE", None) if box is not None else None
SULU_TABLE_BOX = getattr(box, "SIMPLE_HEAD", None) if box is not None else None

# Consistent padding across all panels
PANEL_PADDING = (0, 2)


# ─────────────────────────── Console setup ───────────────────────────

def get_console() -> Any:
    """Get a rich Console instance or a fallback (None)."""
    if not (RICH_AVAILABLE and Console is not None):
        return None

    theme = SULU_TUI_THEME
    kwargs = dict(
        force_terminal=True,
        highlight=False,
        legacy_windows=True,
        color_system="auto",
    )
    if theme is not None:
        kwargs["theme"] = theme

    # emoji=False is available on modern Rich; keep compatibility.
    try:
        return Console(**kwargs, emoji=False)
    except TypeError:
        return Console(**kwargs)


# ─────────────────────────── Size formatting ───────────────────────────

def format_size(size_bytes: int) -> str:
    """Format bytes as human readable."""
    try:
        size_bytes = int(size_bytes)
    except Exception:
        return "unknown"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ─────────────────────────── Trace entry model ───────────────────────────

class TraceEntry:
    """Represents a single traced dependency for display."""

    def __init__(
        self,
        source_blend: str,
        block_type: str,
        block_name: str,
        found_file: str,
        status: str,  # "ok", "missing", "unreadable"
        error_msg: Optional[str] = None,
    ):
        self.source_blend = source_blend
        self.block_type = block_type
        self.block_name = block_name
        self.found_file = found_file
        self.status = status
        self.error_msg = error_msg


# Human-readable block type names (kept, but we no longer rainbow-color them)
BLOCK_TYPE_NAMES = {
    "Library": "Library",
    "Image": "Image",
    "MovieClip": "Movie",
    "Sound": "Sound",
    "VFont": "Font",
    "FreestyleLineStyle": "LineStyle",
    "PointCache": "Cache",
    "Modifier": "Modifier",
    "ParticleSettings": "Particles",
    "Sequence": "Sequence",
    "bNodeTree": "NodeTree",
    "Object": "Object",
    "Mesh": "Mesh",
    "Material": "Material",
    "Scene": "Scene",
    "World": "World",
    "Light": "Light",
    "Camera": "Camera",
    "Armature": "Armature",
    "Action": "Action",
    "bGPdata": "GPencil",
    "GreasePencil": "GPencil",
    "Curves": "Curves",
    "Volume": "Volume",
}


# ─────────────────────────── Submit Logger ───────────────────────────

class SubmitLogger:
    """
    Rich-based logger for submit worker with a consistently styled, scrolling transcript.

    Falls back to plain text if rich is not available.
    """

    def __init__(
        self,
        log_fn: Optional[Callable[[str], None]] = None,
        input_fn: Optional[Callable[[str, str], str]] = None,
    ):
        self.console = get_console() if RICH_AVAILABLE else None
        self._log_fn = log_fn or print
        self._input_fn = input_fn or (lambda prompt, default="": input(prompt))

        self._trace_entries: List[TraceEntry] = []
        self._trace_cols = self._compute_cols()

        self._pack_entries: List[Dict[str, Any]] = []

        # Upload/transfer state
        self._upload_total = 0
        self._upload_step = 0
        self._transfer_active = False
        self._transfer_title = ""
        self._transfer_detail = ""
        self._transfer_cur = 0
        self._transfer_total = 0
        self._transfer_last_line_count = 0
        self._live = None  # Rich Live context for flicker-free progress
        self._last_progress_time = 0.0  # For rate limiting updates

    # ───────────────────── internal helpers ─────────────────────

    def _compute_cols(self) -> Dict[str, int]:
        """Compute column widths based on console width."""
        width = 80
        if self.console:
            try:
                width = int(self.console.width or 80)
            except Exception:
                width = 80

        # status column is a single glyph + 2 spaces; keep a tiny fixed width
        status_w = 3
        gaps = 3  # spaces between main columns
        lead = 2  # leading indent
        usable = max(30, width - lead - gaps - status_w)
        col_w = max(10, usable // 3)
        return {"col": col_w, "status": status_w, "total": width}

    def _print(self, msg: str = "") -> None:
        if self.console:
            self.console.print(msg)
        else:
            self._log_fn(msg)

    def _print_rich(self, *args, **kwargs) -> None:
        if self.console:
            self.console.print(*args, **kwargs)
        else:
            self._log_fn(" ".join(str(a) for a in args))

    def _rule(self, title: str = "") -> None:
        """Subtle divider."""
        if self.console and Rule is not None:
            if title:
                self.console.print(Rule(f"[sulu.muted]{title}[/]", style="sulu.stroke_subtle"))
            else:
                self.console.print(Rule(style="sulu.stroke_subtle"))
        else:
            self._log_fn("-" * 70)

    def _panel(
        self,
        body: Any,
        *,
        title: Optional[Any] = None,
        border_style: str = "sulu.stroke",
        style: str = "sulu.panel",
        box_style: Any = None,
        padding: Tuple[int, int] = PANEL_PADDING,
    ) -> Any:
        """Create a consistently styled Panel (rich only)."""
        if Panel is None:
            return body
        return Panel(
            body,
            title=title,
            title_align="left",
            border_style=border_style,
            padding=padding,
            box=box_style or SULU_PANEL_BOX,
            style=style,
        )

    def _trunc(self, val: str, mx: int) -> str:
        s = str(val or "")
        if mx <= 0:
            return ""
        if len(s) <= mx:
            return s
        # Keep last char as ellipsis-ish dot to reduce visual noise
        ell = "…" if _UNICODE else "."
        return s[: mx - 1] + ell

    # ───────────────────── logo marks ─────────────────────

    def logo_start(self) -> None:
        """Text logomark at the beginning of a submission."""
        if self.console and Text is not None and Align is not None:
            title = Text()
            title.append("SUPERLUMINAL", style="sulu.title")
            title.append("  ·  ", style="sulu.stroke_subtle")
            title.append("SULU SUBMITTER", style="sulu.stage")

            sub = Text("Render farm submission pipeline", style="sulu.muted")

            body = Text()
            body.append(title)
            body.append("\n")
            body.append(sub)

            panel = self._panel(
                Align.center(body),
                title=Text(f"{GLYPH_HEX}  SESSION START", style="sulu.dim"),
                border_style="sulu.stroke_subtle",
                style="sulu.panel",
                padding=(1, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("=== SUPERLUMINAL · SULU SUBMITTER ===")

    def logo_end(self, job_id: Optional[str] = None, elapsed: Optional[float] = None) -> None:
        """Text logomark at the end of submission (after job registration)."""
        if self.console and Text is not None and Align is not None:
            body = Text()
            body.append("SUBMISSION COMPLETE", style="sulu.ok_b")
            if job_id:
                body.append("\n")
                body.append("Job ID: ", style="sulu.muted")
                body.append(str(job_id), style="sulu.fg")
            if elapsed is not None:
                body.append("\n")
                body.append("Elapsed: ", style="sulu.muted")
                body.append(f"{elapsed:.1f}s", style="sulu.fg")

            panel = self._panel(
                Align.center(body),
                title=Text(f"{GLYPH_HEX}  SESSION END", style="sulu.dim"),
                border_style="sulu.ok",
                style="sulu.panel",
                padding=(1, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("=== SUBMISSION COMPLETE ===")

    # ───────────────────── stage headers ─────────────────────

    def stage_header(
        self,
        stage_num: int,
        title: str,
        subtitle: str = "",
        details: Optional[List[str]] = None,
    ) -> None:
        """Print a consistent stage header panel."""
        if self.console and Text is not None:
            t = Text()
            t.append(f"{GLYPH_STAGE} ", style="sulu.accent")
            t.append("STAGE ", style="sulu.dim")
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
            self._log_fn(f"> STAGE {stage_num}: {title}")
            if subtitle:
                self._log_fn(f"  {subtitle}")
            if details:
                for line in details:
                    self._log_fn(f"  - {line}")
            self._log_fn("=" * 70)

    # ───────────────────── trace logging ─────────────────────

    def trace_start(self, blend_path: str) -> None:
        """Begin a trace section."""
        self._trace_entries = []
        if self.console and Text is not None:
            self.console.print()
            self._rule("Dependencies")
            c = self._trace_cols["col"]
            s = self._trace_cols["status"]
            header = Text("  ")
            header.append(f"{'Source':<{c}} ", style="sulu.muted")
            header.append(f"{'Block':<{c}} ", style="sulu.muted")
            header.append(f"{'Resolved':<{c}} ", style="sulu.muted")
            header.append(f"{'':>{s}}", style="sulu.muted")
            self.console.print(header)
            self.console.print(Text("  " + (GLYPH_DASH * (max(0, self._trace_cols['total'] - 2))), style="sulu.stroke_subtle"))
        else:
            self._log_fn("")
            self._log_fn("Dependencies:")
            self._log_fn("-" * 70)

    def trace_entry(
        self,
        source_blend: str,
        block_type: str,
        block_name: str,
        found_file: str,
        status: str,
        error_msg: Optional[str] = None,
    ) -> None:
        """Log a single traced dependency (prints immediately)."""
        entry = TraceEntry(source_blend, block_type, block_name, found_file, status, error_msg)
        self._trace_entries.append(entry)

        type_name = BLOCK_TYPE_NAMES.get(block_type, block_type)
        c = self._trace_cols["col"]
        s = self._trace_cols["status"]

        src_t = self._trunc(source_blend, c)
        file_t = self._trunc(found_file, c)

        # Block column: [Type] name
        type_part = f"[{type_name}]"
        name_max = max(0, c - len(type_part) - 1)
        name_t = self._trunc(block_name, name_max)

        if self.console and Text is not None:
            line = Text("  ")

            # Source
            line.append(f"{src_t:<{c}} ", style="sulu.dim")

            # Block tag (as a machined “pill”)
            tag = Text(type_part, style="sulu.pill")
            line.append(tag)
            line.append(" ", style="sulu.dim")
            line.append(f"{name_t:<{name_max}} ", style="sulu.fg")

            # Resolved
            if status == "ok":
                line.append(f"{file_t:<{c}} ", style="sulu.fg")
                line.append(f"{GLYPH_OK:>{s}}", style="sulu.ok_b")
            elif status == "missing":
                line.append(f"{file_t:<{c}} ", style="sulu.warn")
                line.append(f"{GLYPH_WARN:>{s}}", style="sulu.warn_b")
            else:
                line.append(f"{file_t:<{c}} ", style="sulu.err")
                line.append(f"{GLYPH_FAIL:>{s}}", style="sulu.err_b")

            self.console.print(line)

            # Optional error detail line
            if error_msg and status == "unreadable":
                msg = self._trunc(error_msg, max(20, self._trace_cols["total"] - 8))
                self.console.print(
                    Text(f"  {GLYPH_SEAM} {GLYPH_ARROW} {msg}", style="sulu.dim")
                )
        else:
            status_str = GLYPH_OK if status == "ok" else (GLYPH_WARN if status == "missing" else GLYPH_FAIL)
            block_str = f"[{type_name}] {block_name}"
            self._log_fn(f"  {src_t:<{c}} {block_str:<{c}} {file_t:<{c}} {status_str:>{s}}")
            if error_msg:
                self._log_fn(f"    {GLYPH_ARROW} {error_msg}")

    def trace_summary(
        self,
        total: int,
        missing: int,
        unreadable: int,
        project_root: Optional[str] = None,
        cross_drive: int = 0,
        warning_text: Optional[str] = None,
    ) -> None:
        """Print trace summary as a styled panel (with optional warnings)."""
        has_issues = missing > 0 or unreadable > 0 or cross_drive > 0
        if self.console and Text is not None:
            body = Text()
            if not has_issues:
                body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
                body.append(f"{total} dependencies found", style="sulu.fg")
            else:
                body.append(f"{GLYPH_WARN} ", style="sulu.warn_b")
                body.append(f"{total} dependencies found", style="sulu.fg")

            if project_root:
                body.append("\n")
                body.append("Project root: ", style="sulu.muted")
                body.append(str(project_root), style="sulu.fg")

            # Inline issue summary
            if has_issues:
                body.append("\n")
                parts = []
                if cross_drive:
                    parts.append(f"{cross_drive} cross-drive excluded")
                if missing:
                    parts.append(f"{missing} missing")
                if unreadable:
                    parts.append(f"{unreadable} unreadable")
                body.append("Issues: ", style="sulu.muted")
                body.append(", ".join(parts), style="sulu.warn")

            if warning_text:
                body.append("\n\n")
                body.append(str(warning_text), style="sulu.warn")

            border = "sulu.ok" if not has_issues else "sulu.warn"
            panel = self._panel(
                body,
                title=Text(f"{GLYPH_HEX}  TRACE", style="sulu.dim"),
                border_style=border,
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"Trace: {total} dependencies (missing={missing}, unreadable={unreadable}, cross_drive={cross_drive})")
            if project_root:
                self._log_fn(f"Project root: {project_root}")
            if warning_text:
                self._log_fn(warning_text)

    # ───────────────────── packing logging ─────────────────────

    def pack_start(self) -> None:
        """Begin a manifest/pack listing."""
        self._pack_entries = []
        if self.console and Text is not None:
            self.console.print()
            self._rule("Manifest")
            w = self._trace_cols["total"]
            file_w = max(20, w - 24)

            header = Text("  ")
            header.append(f"{'File':<{file_w}} ", style="sulu.muted")
            header.append(f"{'Size':>10} ", style="sulu.muted")
            header.append(f"{'':>3}", style="sulu.muted")
            self.console.print(header)
            self.console.print(Text("  " + (GLYPH_DASH * (max(0, w - 2))), style="sulu.stroke_subtle"))
        else:
            self._log_fn("")
            self._log_fn("Manifest:")
            self._log_fn("-" * 70)

    def pack_entry(
        self,
        index: int,
        filepath: str,
        size: Optional[int] = None,
        status: str = "ok",
    ) -> None:
        """Log a single manifest entry row in real-time."""
        self._pack_entries.append({"index": index, "filepath": filepath, "size": size, "status": status})
        filename = Path(filepath).name
        size_str = format_size(size) if size else ""
        w = self._trace_cols["total"]
        file_w = max(20, w - 24)

        name_t = self._trunc(filename, file_w)

        if self.console and Text is not None:
            line = Text("  ")
            if status == "ok":
                line.append(f"{name_t:<{file_w}} ", style="sulu.fg")
                line.append(f"{size_str:>10} ", style="sulu.dim")
                line.append(f"{GLYPH_OK:>3}", style="sulu.ok_b")
            elif status == "missing":
                line.append(f"{name_t:<{file_w}} ", style="sulu.warn")
                line.append(f"{'':>10} ", style="sulu.dim")
                line.append(f"{GLYPH_WARN:>3}", style="sulu.warn_b")
            else:
                line.append(f"{name_t:<{file_w}} ", style="sulu.err")
                line.append(f"{'':>10} ", style="sulu.dim")
                line.append(f"{GLYPH_FAIL:>3}", style="sulu.err_b")
            self.console.print(line)
        else:
            status_str = GLYPH_OK if status == "ok" else (GLYPH_WARN if status == "missing" else GLYPH_FAIL)
            self._log_fn(f"  {name_t:<50} {size_str:>10} {status_str:>3}")

    def pack_end(
        self,
        ok_count: int,
        total_size: int = 0,
        title: str = "Manifest complete",
    ) -> None:
        """Print manifest summary as a styled panel."""
        if self.console and Text is not None:
            body = Text()
            body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            body.append(f"{ok_count} file(s)", style="sulu.fg")
            body.append("  ·  ", style="sulu.stroke_subtle")
            body.append(f"{format_size(total_size)}", style="sulu.muted")

            panel = self._panel(
                body,
                title=Text(f"{GLYPH_HEX}  {title.upper()}", style="sulu.dim"),
                border_style="sulu.ok",
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"{title}: {ok_count} files, {format_size(total_size)}")

    # ───────────────────── zip callbacks (BAT) ─────────────────────

    def zip_start(self, total_files: int, total_bytes: int) -> None:
        """Begin zip progress listing (structured callbacks from packer)."""
        self._zip_total = total_files
        if self.console and Text is not None:
            self.console.print()
            self._rule("Archive")
            w = self._trace_cols["total"]
            file_w = max(20, w - 30)

            header = Text("  ")
            header.append(f"{'File':<{file_w}} ", style="sulu.muted")
            header.append(f"{'Size':>10} ", style="sulu.muted")
            header.append(f"{'Mode':>16}", style="sulu.muted")
            self.console.print(header)
            self.console.print(Text("  " + (GLYPH_DASH * (max(0, w - 2))), style="sulu.stroke_subtle"))
        else:
            self._log_fn("")
            self._log_fn("Archive:")
            self._log_fn("-" * 70)

    def zip_entry(self, index: int, total: int, arcname: str, size: int, method: str) -> None:
        """Log a single file being zipped (structured callback)."""
        w = self._trace_cols["total"]
        file_w = max(20, w - 30)
        name_t = self._trunc(arcname, file_w)
        size_str = format_size(size) if size else ""

        if self.console and Text is not None:
            line = Text("  ")
            line.append(f"{name_t:<{file_w}} ", style="sulu.fg")
            line.append(f"{size_str:>10} ", style="sulu.dim")
            line.append(f"{method:>16}", style="sulu.muted")
            self.console.print(line)
        else:
            self._log_fn(f"  {name_t:<42} {size_str:>10} {method:>16}")

    def zip_done(self, zippath: str, total_files: int, total_bytes: int, elapsed: float) -> None:
        """Print zip completion summary."""
        if self.console and Text is not None:
            body = Text()
            body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            body.append(f"{total_files} file(s)", style="sulu.fg")
            body.append("  ·  ", style="sulu.stroke_subtle")
            body.append(f"{format_size(total_bytes)}", style="sulu.muted")
            body.append("  ·  ", style="sulu.stroke_subtle")
            body.append(f"{elapsed:.1f}s", style="sulu.muted")

            panel = self._panel(
                body,
                title=Text(f"{GLYPH_HEX}  ARCHIVE READY", style="sulu.dim"),
                border_style="sulu.ok",
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"Archive ready: {total_files} files, {format_size(total_bytes)}, {elapsed:.1f}s")

    # ───────────────────── upload / transfer ─────────────────────

    def upload_start(self, total: int) -> None:
        """Begin the upload phase."""
        self._upload_total = total
        self._upload_step = 0
        self._transfer_active = False
        self._transfer_last_line_count = 0
        self._last_progress_time = 0.0

    def upload_step(
        self,
        step: int,
        total_steps: int,
        title: str,
        detail: str = "",
    ) -> None:
        """Start a transfer substage - shows title and prepares for progress bar."""
        self._upload_step = step
        self._transfer_title = title
        self._transfer_detail = detail
        self._transfer_active = True
        self._transfer_cur = 0
        self._transfer_total = 0

        if self.console and Text is not None:
            self.console.print()
            # Substage header
            step_str = f"[{step}/{total_steps}]"
            header = Text()
            header.append(f"  {step_str} ", style="sulu.accent")
            header.append(title, style="sulu.title")
            if detail:
                header.append("  ", style="sulu.stroke_subtle")
                header.append(detail, style="sulu.dim")
            self.console.print(header)

            # Reset progress state
            self._transfer_last_line_count = 0
            self._last_progress_time = 0.0
        else:
            self._log_fn(f"\n[{step}/{total_steps}] {title} {detail}")

    def _build_progress_panel(self, cur: int, total: int) -> Any:
        """Build a progress bar panel renderable."""
        if not self.console or Text is None:
            return ""

        width = 80
        try:
            width = int(self.console.width or 80)
        except Exception:
            width = 80

        # Calculate bar width (account for panel borders and padding)
        bar_width = max(20, width - 8)

        if total > 0:
            pct = cur / max(total, 1)
            filled = int(bar_width * pct)
            empty = bar_width - filled

            # Build the progress bar with blue fill
            bar = Text()
            bar.append("█" * filled, style="sulu.accent")
            bar.append("░" * empty, style="sulu.stroke_subtle")

            # Stats line
            stats = Text()
            stats.append(f"{pct * 100:5.1f}%", style="sulu.accent")
            stats.append("  ", style="sulu.stroke_subtle")
            stats.append(f"{format_size(cur)}", style="sulu.fg")
            stats.append(" / ", style="sulu.dim")
            stats.append(f"{format_size(total)}", style="sulu.muted")
        else:
            # Indeterminate - pulsing effect
            bar = Text("░" * bar_width, style="sulu.stroke_subtle")
            stats = Text()
            stats.append(f"{format_size(cur)}", style="sulu.fg")
            stats.append(" transferred", style="sulu.dim")

        # Combine bar and stats
        body = Text()
        body.append(bar)
        body.append("\n")
        body.append(stats)

        return self._panel(
            body,
            border_style="sulu.accent",
            style="sulu.well",
            padding=(0, 1),
        )

    def transfer_progress(self, cur: int, total: int) -> None:
        """Update the transfer progress bar."""
        self._transfer_cur = cur
        self._transfer_total = total

        if self.console and Text is not None:
            self._render_progress_bar(cur, total)
        else:
            # Plain text fallback
            if total > 0:
                pct = (cur / max(total, 1)) * 100
                sys.stderr.write(f"\r  {format_size(cur)} / {format_size(total)} ({pct:.1f}%) ")
                sys.stderr.flush()

    def _render_progress_bar(self, cur: int, total: int) -> None:
        """Render/update the progress bar panel with rate limiting to reduce flicker."""
        if not self.console or Text is None:
            return

        # Rate limit: only update ~10 times per second to reduce flicker
        now = time.time()
        if self._transfer_last_line_count > 0 and (now - self._last_progress_time) < 0.1:
            return
        self._last_progress_time = now

        panel = self._build_progress_panel(cur, total)

        # Clear previous lines and render
        if self._transfer_last_line_count > 0:
            # Hide cursor, move up, clear, print, show cursor - all in one write
            self.console.file.write(f"\033[?25l\033[{self._transfer_last_line_count}A\033[J")
            self.console.file.flush()

        self.console.print(panel)

        # Show cursor again
        self.console.file.write("\033[?25h")
        self.console.file.flush()

        self._transfer_last_line_count = 4

    def upload_complete(self, title: str) -> None:
        """Mark current transfer substage as complete."""
        self._transfer_active = False

        if self.console and Text is not None:
            # Clear the progress bar
            if self._transfer_last_line_count > 0:
                self.console.file.write(f"\033[{self._transfer_last_line_count}A\033[J")
                self.console.file.flush()
                self._transfer_last_line_count = 0

            # Show completion with stats
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

    def upload_end(self, elapsed: float) -> None:
        """Final upload completion message."""
        if self.console and Text is not None:
            self.console.print()
            body = Text()
            body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            body.append("Transfer complete", style="sulu.title")
            body.append("  ·  ", style="sulu.stroke_subtle")
            body.append(f"{elapsed:.1f}s", style="sulu.muted")

            panel = self._panel(
                body,
                title=Text(f"{GLYPH_HEX}  UPLOAD", style="sulu.dim"),
                border_style="sulu.ok",
                style="sulu.well",
            )
            self.console.print(panel)
        else:
            self._log_fn(f"\nTransfer complete in {elapsed:.1f}s")

    # ───────────────────── general messages ─────────────────────

    def info(self, msg: str) -> None:
        if self.console:
            self.console.print(f"[sulu.dim]{GLYPH_INFO}[/] [sulu.muted]{msg}[/]")
        else:
            self._log_fn(f"[i] {msg}")

    def success(self, msg: str) -> None:
        if self.console:
            self.console.print(f"[sulu.ok_b]{GLYPH_OK}[/] [sulu.fg]{msg}[/]")
        else:
            self._log_fn(f"{GLYPH_OK} {msg}")

    def warning(self, msg: str) -> None:
        if self.console:
            self.console.print(f"[sulu.warn_b]{GLYPH_WARN}[/] [sulu.warn]{msg}[/]")
        else:
            self._log_fn(f"! {msg}")

    def error(self, msg: str) -> None:
        if self.console:
            self.console.print(f"[sulu.err_b]{GLYPH_FAIL}[/] [sulu.err]{msg}[/]")
        else:
            self._log_fn(f"X {msg}")

    def log(self, msg: str) -> None:
        self._print(msg)

    # ───────────────────── warn / prompt / fatal ─────────────────────

    def warn_block(self, message: str, severity: str = "warning") -> None:
        """Render a styled Panel for warnings/errors. Does NOT exit."""
        if not self.console or Panel is None or Text is None:
            tag = "WARNING" if severity == "warning" else "ERROR"
            self._log_fn(f"{tag}: {message}")
            return

        border = "sulu.warn" if severity == "warning" else "sulu.err"
        glyph = GLYPH_WARN if severity == "warning" else GLYPH_FAIL
        title = Text(f"{glyph}  {severity.upper()}", style="sulu.muted")
        panel = self._panel(
            Text(str(message), style="sulu.fg"),
            title=title,
            border_style=border,
            style="sulu.well",
        )
        self.console.print()
        self.console.print(panel)

    def prompt(self, question: str, default: str = "") -> str:
        """Styled input prompt. Returns the user's answer."""
        if self.console:
            # Render question once; avoid duplicate prompt from input()
            self.console.print(f"[sulu.dim]{GLYPH_INFO}[/] [sulu.fg]{question}[/]", end="")
        else:
            self._log_fn(question)
        return self._input_fn("", default)

    def fatal(self, message: str) -> None:
        """Print error, prompt to close, then exit."""
        # Use a block for fatal errors
        self.warn_block(message, severity="error")
        try:
            self._input_fn("\nPress ENTER to close this window...", "")
        except Exception:
            pass
        sys.exit(1)

    def version_update(self, url: str, instructions: List[str]) -> None:
        """Panel with URL + steps for addon updates."""
        if self.console and Panel is not None and Text is not None:
            body = Text()
            body.append(str(url), style="sulu.link")
            for line in instructions:
                body.append("\n")
                body.append(f"{GLYPH_BULLET} ", style="sulu.dim")
                body.append(str(line), style="sulu.fg")

            panel = self._panel(
                body,
                title=Text(f"{GLYPH_INFO}  UPDATE AVAILABLE", style="sulu.muted"),
                border_style="sulu.accent",
                style="sulu.panel",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn(f"Update available: {url}")
            for line in instructions:
                self._log_fn(f" - {line}")

    # ───────────────────── storage connection ─────────────────────

    def storage_connect(self, status: str = "connecting") -> None:
        """Log storage connection status."""
        if status == "connecting":
            self.info("Connecting to storage…")
        else:
            if self.console:
                self.console.print(f"[sulu.ok_b]{GLYPH_OK}[/] [sulu.fg]Storage connected[/]")
            else:
                self._log_fn("Storage connected")

    # ───────────────────── job complete ─────────────────────

    def job_complete(self, web_url: str) -> None:
        """Log that the job page was opened in the browser."""
        if self.console and Panel is not None and Text is not None:
            body = Text()
            body.append(str(web_url), style="sulu.link")
            panel = self._panel(
                body,
                title=Text(f"{GLYPH_LINK}  OPENED IN BROWSER", style="sulu.muted"),
                border_style="sulu.ok",
                style="sulu.panel",
            )
            self.console.print(panel)
        else:
            self._log_fn(f"Opened in browser: {web_url}")

    # ───────────────────── reports (test / no-submit) ─────────────────────

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
        """Render the full test-mode report (kept for compatibility)."""
        _sh = shorten_fn or (lambda s: s)
        blend_size = 0
        try:
            blend_size = os.path.getsize(blend_path)
        except Exception:
            pass

        if self.console and Panel is not None and Text is not None:
            panel = self._panel(
                Text(f"Upload type: {upload_type}", style="sulu.fg"),
                title=Text(f"{GLYPH_INFO}  TEST MODE", style="sulu.muted"),
                border_style="sulu.warn",
                style="sulu.panel",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn(f"TEST MODE — {upload_type}")

        self.info(f"Blend: {Path(blend_path).name} ({format_size(blend_size)})")
        self.info(f"Dependencies: {dep_count}")
        self.info(f"Project root: {_sh(project_root)}")
        self.info(f"Same-drive: {same_drive}  ·  Cross-drive: {cross_drive}")

        # Breakdown table (minimal)
        if self.console and Table is not None:
            table = Table(
                title="Dependency breakdown",
                show_header=True,
                header_style="sulu.muted",
                border_style="sulu.stroke_subtle",
                box=SULU_TABLE_BOX,
                padding=(0, 1),
                show_edge=False,
                expand=True,
            )
            table.add_column("Ext", style="sulu.fg")
            table.add_column("Count", justify="right", style="sulu.muted")
            for ext, cnt in sorted(by_ext.items(), key=lambda x: -x[1]):
                table.add_row(ext, str(cnt))
            table.add_row("", "")
            table.add_row("Total", format_size(total_size))
            self.console.print()
            self.console.print(table)
        else:
            self._log_fn("Dependency breakdown:")
            for ext, cnt in sorted(by_ext.items(), key=lambda x: -x[1]):
                self._log_fn(f"  {ext:12} : {cnt:4} files")
            self._log_fn(f"  Total size: {format_size(total_size)}")

        # Issues block
        has_issues = bool(missing or unreadable or cross_drive_files)
        if has_issues:
            lines: List[str] = []
            if missing:
                lines.append(f"MISSING ({len(missing)}):")
                for p in missing:
                    lines.append(f"  - {_sh(p)}")
            if unreadable:
                if lines:
                    lines.append("")
                lines.append(f"UNREADABLE ({len(unreadable)}):")
                for p, err in unreadable:
                    lines.append(f"  - {_sh(p)}")
                    lines.append(f"    {err}")
            if cross_drive_files:
                if lines:
                    lines.append("")
                lines.append(f"CROSS-DRIVE ({len(cross_drive_files)}):")
                for p in cross_drive_files:
                    lines.append(f"  - {_sh(p)}")

            self.warn_block("\n".join(lines), severity="warning")

        if report_path:
            self.info(f"Report saved: {report_path}")

        self.warn_block("TEST MODE — no upload or job registration performed.", severity="warning")

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
        """Render the no-submit summary panel."""
        lines: List[str] = [
            "Packing completed successfully.",
            f"Upload type: {upload_type}",
        ]
        if upload_type == "PROJECT":
            lines.append(f"Project root: {common_path}")
            lines.append(f"Dependencies: {rel_manifest_count}")
            lines.append(f"Main blend key: {main_blend_s3}")
        else:
            lines.append(f"Archive: {zip_file}")
            if zip_size:
                lines.append(f"Archive size: {format_size(zip_size)}")
        lines.append(f"Storage estimate: {format_size(required_storage)}")
        lines.append("")
        lines.append("Skipping upload and job registration.")

        if self.console and Panel is not None and Text is not None:
            panel = self._panel(
                Text("\n".join(lines), style="sulu.fg"),
                title=Text(f"{GLYPH_INFO}  NO-SUBMIT MODE", style="sulu.muted"),
                border_style="sulu.warn",
                style="sulu.panel",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("NO-SUBMIT MODE")
            for line in lines:
                self._log_fn(f"  {line}")

    # Compatibility aliases (older names)
    def pack_file(self, index: int, total: int, filepath: str, size: Optional[int] = None, status: str = "ok") -> None:
        self.pack_entry(index, filepath, size=size, status=status)

    def pack_summary(
        self,
        ok_count: int,
        missing_count: int = 0,
        unreadable_count: int = 0,
        cross_drive_count: int = 0,
        total_size: int = 0,
    ) -> None:
        # Keep old behavior: print as a warning block if issues exist
        if missing_count or unreadable_count or cross_drive_count:
            parts = []
            if cross_drive_count:
                parts.append(f"{cross_drive_count} cross-drive excluded")
            if missing_count:
                parts.append(f"{missing_count} missing")
            if unreadable_count:
                parts.append(f"{unreadable_count} unreadable")
            self.warn_block("Issues: " + ", ".join(parts), severity="warning")
        self.pack_end(ok_count=ok_count, total_size=total_size, title="Packing complete")


# ─────────────────────────── Factory ───────────────────────────

def create_logger(
    log_fn: Optional[Callable[[str], None]] = None,
    input_fn: Optional[Callable[[str, str], str]] = None,
) -> SubmitLogger:
    return SubmitLogger(log_fn, input_fn=input_fn)
