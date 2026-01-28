"""
Rich-based logging utilities for submit worker.

Provides beautiful, colorful console output with:
- Stage headers with borders
- Trace tables showing dependency chains
- Progress indicators with status colors
- File size formatting
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Import vendored rich library (local to addon)
# We try multiple import paths to handle both direct execution and package imports
RICH_AVAILABLE = False
Console = None
Table = None
Panel = None
Text = None
Style = None
box = None


def _try_import_rich():
    """Try to import rich from various locations."""
    global RICH_AVAILABLE, Console, Table, Panel, Text, Style, box

    # Method 1: Try relative import (works when imported as part of package)
    try:
        from ..rich.console import Console as _Console
        from ..rich.panel import Panel as _Panel
        from ..rich.table import Table as _Table
        from ..rich.text import Text as _Text
        from ..rich.style import Style as _Style
        from ..rich import box as _box

        Console = _Console
        Panel = _Panel
        Table = _Table
        Text = _Text
        Style = _Style
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

        # Import as top-level 'rich' module
        import rich.console
        import rich.panel
        import rich.table
        import rich.text
        import rich.style
        import rich.box

        Console = rich.console.Console
        Panel = rich.panel.Panel
        Table = rich.table.Table
        Text = rich.text.Text
        Style = rich.style.Style
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
        from rich import box as _box

        Console = _Console
        Panel = _Panel
        Table = _Table
        Text = _Text
        Style = _Style
        box = _box
        RICH_AVAILABLE = True
        return
    except ImportError:
        pass


# Try importing rich at module load time
_try_import_rich()


# ─── Icons (ASCII fallback for Windows) ───────────────────────────────────────

def _supports_unicode() -> bool:
    """Check if the terminal supports Unicode output."""
    # Check for UTF-8 encoding
    try:
        encoding = sys.stdout.encoding or ""
        if "utf" in encoding.lower():
            return True
    except Exception:
        pass
    # Check PYTHONIOENCODING
    if "utf" in os.environ.get("PYTHONIOENCODING", "").lower():
        return True
    # Windows legacy console typically doesn't support Unicode
    if sys.platform == "win32":
        # Check if running in Windows Terminal or modern console
        if os.environ.get("WT_SESSION"):
            return True
        return False
    return True


# Icons with ASCII fallbacks
_UNICODE = _supports_unicode()

ICON_FOLDER = "📂" if _UNICODE else "[DIR]"
ICON_FILE = "📄" if _UNICODE else "[FILE]"
ICON_PACKAGE = "📦" if _UNICODE else "[PKG]"
ICON_CHECK = "✓" if _UNICODE else "[OK]"
ICON_CROSS = "✗" if _UNICODE else "[X]"
ICON_WARN = "⚠" if _UNICODE else "[!]"
ICON_ARROW = "→" if _UNICODE else "->"
ICON_SEARCH = "🔍" if _UNICODE else "[?]"
ICON_CHART = "📊" if _UNICODE else "[#]"
ICON_ROCKET = "🚀" if _UNICODE else "[>]"
ICON_KEY = "🔑" if _UNICODE else "[K]"
ICON_INFO = "ℹ" if _UNICODE else "[i]"
ICON_SUCCESS = "✅" if _UNICODE else "[OK]"
ICON_ERROR = "❌" if _UNICODE else "[ERR]"


# ─── Styles ───────────────────────────────────────────────────────────────────

STYLE_OK = "green"
STYLE_MISSING = "yellow"
STYLE_UNREADABLE = "red"
STYLE_INFO = "cyan"
STYLE_DIM = "dim"
STYLE_HEADER = "bold white"

# Block type colors
BLOCK_TYPE_STYLES = {
    "Library": "bright_blue",
    "Image": "bright_magenta",
    "Sound": "bright_cyan",
    "MovieClip": "bright_cyan",
    "VFont": "bright_yellow",
    "PointCache": "orange3",
    "Modifier": "orange3",
    "Sequence": "bright_cyan",
    "bNodeTree": "bright_green",
    "Volume": "purple",
}


# ─── Human-readable block type names ──────────────────────────────────────────

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


# ─── Console setup ────────────────────────────────────────────────────────────

def get_console() -> Any:
    """Get a rich Console instance or a fallback."""
    if RICH_AVAILABLE and Console is not None:
        try:
            # Create console with explicit settings for cross-platform color support
            # force_terminal=True ensures colors even when output is piped
            # legacy_windows=True enables colors on older Windows consoles
            console = Console(
                force_terminal=True,
                highlight=False,
                legacy_windows=True,
                color_system="auto",
            )
            return console
        except Exception:
            pass
    return None


# ─── Size formatting ──────────────────────────────────────────────────────────

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


# ─── Trace entry class ────────────────────────────────────────────────────────

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


# ─── Submit Logger class ──────────────────────────────────────────────────────

class SubmitLogger:
    """
    Rich-based logger for submit worker with beautiful formatting.

    Falls back to plain text if rich is not available.
    """

    def __init__(
        self,
        log_fn: Optional[Callable[[str], None]] = None,
        input_fn: Optional[Callable[[str, str], str]] = None,
    ):
        """
        Initialize the logger.

        Args:
            log_fn: Optional fallback logging function for plain text mode.
            input_fn: Optional input function matching _safe_input(prompt, default) signature.
        """
        self.console = get_console() if RICH_AVAILABLE else None
        self._log_fn = log_fn or print
        self._input_fn = input_fn or (lambda prompt, default="": input(prompt))
        self._trace_entries: List[TraceEntry] = []
        self._trace_cols = self._compute_trace_cols()
        self._pack_entries: List[Dict[str, Any]] = []
        self._upload_entries: List[Dict[str, Any]] = []

    def _compute_trace_cols(self) -> Dict[str, int]:
        """Compute trace table column widths based on console width."""
        width = 80
        if self.console:
            try:
                width = self.console.width or 80
            except Exception:
                pass
        # Reserve: 1 leading space + 3 column gaps (1 each) + status col (7)
        status_w = 7
        usable = width - 1 - 3 - status_w  # space for the 3 data columns
        # Split equally among the 3 data columns
        col_w = max(10, usable // 3)
        return {"col": col_w, "status": status_w, "total": width}

    def _print(self, msg: str = "") -> None:
        """Print a message using the appropriate method."""
        if self.console:
            self.console.print(msg)
        else:
            self._log_fn(msg)

    def _print_rich(self, *args, **kwargs) -> None:
        """Print using rich console if available."""
        if self.console:
            self.console.print(*args, **kwargs)
        else:
            # Fallback: extract text content
            text = " ".join(str(a) for a in args)
            self._log_fn(text)

    # ─── Stage headers ────────────────────────────────────────────────────────

    def stage_header(
        self,
        stage_num: int,
        title: str,
        subtitle: str = "",
        details: Optional[List[str]] = None,
    ) -> None:
        """Print a beautiful stage header with optional detail lines inside the panel."""
        if self.console:
            header_text = f"STAGE {stage_num}: {title}"
            body = Text()
            if subtitle:
                body.append(subtitle, style="dim")
            if details:
                for line in details:
                    if body.plain:
                        body.append("\n")
                    body.append(line)
            panel = Panel(
                body if body.plain else "",
                title=f"[bold white]{header_text}[/]",
                border_style="bright_blue",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("=" * 70)
            self._log_fn(f"  STAGE {stage_num}: {title}")
            if subtitle:
                self._log_fn(f"  {subtitle}")
            if details:
                for line in details:
                    self._log_fn(f"  {line}")
            self._log_fn("=" * 70)

    # ─── Trace logging ────────────────────────────────────────────────────────

    def trace_start(self, blend_path: str) -> None:
        """Start tracing - emit table header only.

        "Main file" and "Scanning" info should be passed via
        ``stage_header(..., details=[...])`` so they appear inside the
        stage panel.
        """
        self._trace_entries = []
        if self.console:
            self.console.print()
            c = self._trace_cols["col"]
            s = self._trace_cols["status"]
            w = self._trace_cols["total"]
            self.console.print(f"[bold cyan] {'Block File':<{c}} {'Block':<{c}} {'Found File':<{c}} {'Status':>{s}}[/]")
            self.console.print(f"[dim]{'-' * w}[/]")
        else:
            self._log_fn("")
            c = self._trace_cols["col"]
            s = self._trace_cols["status"]
            w = self._trace_cols["total"]
            self._log_fn(f" {'Block File':<{c}} {'Block':<{c}} {'Found File':<{c}} {'Status':>{s}}")
            self._log_fn("-" * w)

    def trace_entry(
        self,
        source_blend: str,
        block_type: str,
        block_name: str,
        found_file: str,
        status: str,
        error_msg: Optional[str] = None,
    ) -> None:
        """Log a single trace entry - prints immediately for real-time feedback."""
        entry = TraceEntry(source_blend, block_type, block_name, found_file, status, error_msg)
        self._trace_entries.append(entry)

        # Print immediately for real-time feedback (table row format)
        type_name = BLOCK_TYPE_NAMES.get(block_type, block_type)
        type_style = BLOCK_TYPE_STYLES.get(block_type, "white")
        c = self._trace_cols["col"]
        s = self._trace_cols["status"]

        # Truncate helper
        def _trunc(val: str, w: int) -> str:
            return (val[:w-1] + ".") if len(val) > w else val

        src_trunc = _trunc(source_blend, c)
        file_trunc = _trunc(found_file, c)

        if self.console and Text is not None:
            line = Text(" ")

            # Block File column (dim)
            line.append(f"{src_trunc:<{c}} ", style="dim")

            # Block column (type colored + name)
            type_part = f"[{type_name}]"
            name_max = c - len(type_part) - 1
            name_trunc = _trunc(block_name, name_max) if name_max > 0 else ""
            line.append(type_part, style=type_style)
            padded_name = f" {name_trunc}"
            line.append(f"{padded_name:<{c - len(type_part)}} ", style="white")

            # Found File column
            if status == "ok":
                line.append(f"{file_trunc:<{c}} ", style="bright_white")
            elif status == "missing":
                line.append(f"{file_trunc:<{c}} ", style="yellow")
            else:
                line.append(f"{file_trunc:<{c}} ", style="red")

            # Status column
            if status == "ok":
                line.append(f"{ICON_CHECK:>{s}}", style="green")
            elif status == "missing":
                line.append(f"{'MISS':>{s}}", style="yellow bold")
            else:
                line.append(f"{'ERR':>{s}}", style="red bold")

            self.console.print(line)

            # Print error message on next line if present
            if error_msg and status == "unreadable":
                self.console.print(f"[red dim]  {' '*c} {ICON_ARROW} {error_msg}[/]")
        else:
            # Plain text fallback
            block_str = f"[{type_name}] {block_name}"
            block_trunc = _trunc(block_str, c)
            status_str = ICON_CHECK if status == "ok" else ("MISS" if status == "missing" else "ERR")
            self._log_fn(f" {src_trunc:<{c}} {block_trunc:<{c}} {file_trunc:<{c}} {status_str:>{s}}")
            if error_msg:
                self._log_fn(f"  {' '*c} {ICON_ARROW} {error_msg}")

    def _render_trace_table(self) -> None:
        """Render collected trace entries as a beautiful table."""
        if not self._trace_entries:
            return

        if self.console and Table is not None:
            # Create a rich Table with minimal styling for clean look
            table = Table(
                show_header=True,
                header_style="bold cyan",
                border_style="bright_blue",
                box=box.SIMPLE_HEAD if box else None,
                expand=True,
                padding=(0, 1),
                show_edge=False,
            )

            # Add columns: Block File, Block (with type), Found File, Status
            # First 3 columns have equal width (ratio=1) and truncate with ellipsis
            table.add_column("Block File", style="dim", overflow="ellipsis", ratio=1, no_wrap=True)
            table.add_column("Block", style="white", overflow="ellipsis", ratio=1, no_wrap=True)
            table.add_column("Found File", style="white", overflow="ellipsis", ratio=1, no_wrap=True)
            table.add_column("", justify="center", no_wrap=True, width=7)

            # Add rows
            for entry in self._trace_entries:
                type_name = BLOCK_TYPE_NAMES.get(entry.block_type, entry.block_type)
                type_style = BLOCK_TYPE_STYLES.get(entry.block_type, "white")

                # Status cell with color and icon
                if entry.status == "ok":
                    status_cell = Text(ICON_CHECK, style="green")
                elif entry.status == "missing":
                    status_cell = Text("MISSING", style="yellow bold")
                else:
                    status_cell = Text("ERROR", style="red bold")

                # Block cell: [Type] name
                block_text = f"[{type_name}] {entry.block_name}"
                block_cell = Text()
                block_cell.append(f"[{type_name}]", style=type_style)
                block_cell.append(f" {entry.block_name}", style="white")

                # Found file cell (error shown in status tooltip or separate)
                if entry.status == "ok":
                    file_cell = Text(entry.found_file, style="white")
                elif entry.status == "missing":
                    file_cell = Text(entry.found_file, style="yellow")
                else:
                    file_cell = Text(entry.found_file, style="red")

                table.add_row(
                    entry.source_blend,
                    block_cell,
                    file_cell,
                    status_cell,
                )

            self.console.print(table)
        else:
            # Plain text fallback - print each entry
            for entry in self._trace_entries:
                type_name = BLOCK_TYPE_NAMES.get(entry.block_type, entry.block_type)
                status_icon = ICON_CHECK if entry.status == "ok" else (f"{ICON_WARN} MISSING" if entry.status == "missing" else f"{ICON_CROSS} UNREADABLE")
                self._log_fn(f"  {entry.source_blend:20} [{type_name:10}] {entry.block_name:20} {ICON_ARROW} {entry.found_file}  {status_icon}")
                if entry.error_msg:
                    self._log_fn(f"                       {ICON_ARROW} {entry.error_msg}")

    def trace_summary(
        self,
        total: int,
        missing: int,
        unreadable: int,
        project_root: Optional[str] = None,
        cross_drive: int = 0,
        warning_text: Optional[str] = None,
    ) -> None:
        """Print trace summary as a styled Panel, optionally with warnings included."""
        has_issues = missing > 0 or unreadable > 0 or cross_drive > 0
        if self.console and Panel is not None and Text is not None:
            body = Text()
            body.append(f"{ICON_CHECK} {total} dependencies found", style="bold green" if not has_issues else "bold")
            if project_root:
                body.append(f"\n{ICON_FOLDER} Project root: ", style="cyan")
                body.append(project_root, style="white")
            if warning_text:
                body.append(f"\n\n{warning_text}", style="yellow")

            border = "green" if not has_issues else "yellow"
            panel = Panel(
                body,
                title=f"[bold white]{ICON_CHART} Trace Complete[/]",
                border_style=border,
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_CHART}  Trace complete: {total} dependencies found")
            if project_root:
                self._log_fn(f"  {ICON_FOLDER}  Project root: {project_root}")
            if warning_text:
                self._log_fn(f"  {ICON_WARN}  {warning_text}")
            elif has_issues:
                if missing > 0:
                    self._log_fn(f"  {ICON_WARN}  {missing} missing file(s)")
                if unreadable > 0:
                    self._log_fn(f"  {ICON_ERROR}  {unreadable} unreadable file(s)")
                if cross_drive > 0:
                    self._log_fn(f"  {ICON_WARN}  {cross_drive} on different drive (excluded)")

    # ─── Packing logging ──────────────────────────────────────────────────────

    def pack_file(
        self,
        index: int,
        total: int,
        filepath: str,
        size: Optional[int] = None,
        status: str = "ok",
    ) -> None:
        """Log a file being added to pack."""
        size_str = f"({format_size(size)})" if size else ""
        filename = Path(filepath).name

        if self.console:
            if status == "ok":
                self.console.print(f"    [green]{ICON_CHECK}[/] [{index}/{total}] {filename}  [dim]{size_str}[/]")
            elif status == "missing":
                self.console.print(f"    [yellow]{ICON_WARN}[/] [{index}/{total}] {filename}  [yellow]MISSING[/]")
            else:
                self.console.print(f"    [red]{ICON_ERROR}[/] [{index}/{total}] {filename}  [red]UNREADABLE[/]")
        else:
            status_icon = ICON_CHECK if status == "ok" else (ICON_WARN if status == "missing" else ICON_ERROR)
            self._log_fn(f"    {status_icon} [{index}/{total}] {filename}  {size_str}")

    def pack_summary(
        self,
        ok_count: int,
        missing_count: int = 0,
        unreadable_count: int = 0,
        cross_drive_count: int = 0,
        total_size: int = 0,
    ) -> None:
        """Print packing summary."""
        if self.console:
            self.console.print()
            self.console.print(f"[bold]{ICON_CHART} Packing complete:[/]")
            self.console.print(f"    [green]{ICON_CHECK} {ok_count} files added to manifest[/]")
            self.console.print(f"    [cyan]+ 1 main .blend file[/]")
            if cross_drive_count > 0:
                self.console.print(f"    [yellow]{ICON_WARN} {cross_drive_count} excluded (different drive)[/]")
            if missing_count > 0:
                self.console.print(f"    [yellow]{ICON_WARN} {missing_count} missing[/]")
            if unreadable_count > 0:
                self.console.print(f"    [red]{ICON_ERROR} {unreadable_count} unreadable[/]")
            self.console.print(f"    [cyan]{ICON_FOLDER} Total size: {format_size(total_size)}[/]")
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_CHART}  Packing complete:")
            self._log_fn(f"    {ICON_CHECK} {ok_count} files added to manifest")
            self._log_fn(f"    + 1 main .blend file")
            if cross_drive_count > 0:
                self._log_fn(f"    {ICON_WARN} {cross_drive_count} excluded (different drive)")
            if missing_count > 0:
                self._log_fn(f"    {ICON_WARN} {missing_count} missing")
            if unreadable_count > 0:
                self._log_fn(f"    {ICON_ERROR} {unreadable_count} unreadable")
            self._log_fn(f"    {ICON_FOLDER} Total size: {format_size(total_size)}")

    # ─── Upload logging ───────────────────────────────────────────────────────

    def upload_step(
        self,
        step: int,
        total_steps: int,
        title: str,
        detail: str = "",
    ) -> None:
        """Log an upload step starting (table row style)."""
        w = self._trace_cols["total"]
        title_w = w - 30
        step_str = f"[{step}/{total_steps}]"

        def _trunc(val: str, mx: int) -> str:
            return (val[:mx - 1] + ".") if len(val) > mx else val

        title_t = _trunc(title, title_w)
        det_t = _trunc(detail, 18) if detail else ""

        if self.console and Text is not None:
            line = Text(" ")
            line.append(f"{step_str:<8}", style="cyan bold")
            line.append(f"{title_t:<{title_w}} ", style="white")
            line.append(f"{det_t:<18} ", style="dim")
            line.append(f"{ICON_ARROW:>4}", style="cyan")
            self.console.print(line)
        else:
            self._log_fn(f" {step_str:<8} {title_t:<40} {det_t:<18} {ICON_ARROW}")

    def upload_complete(self, title: str) -> None:
        """Log an upload step completed."""
        if self.console:
            self.console.print(f"    [green]{ICON_CHECK} {title}[/]")
        else:
            self._log_fn(f"    {ICON_CHECK} {title}")

    # ─── General messages ─────────────────────────────────────────────────────

    def info(self, msg: str) -> None:
        """Print an info message."""
        if self.console:
            self.console.print(f"[cyan]{ICON_INFO}  {msg}[/]")
        else:
            self._log_fn(f"{ICON_INFO}  {msg}")

    def success(self, msg: str) -> None:
        """Print a success message."""
        if self.console:
            self.console.print(f"[bold green]{ICON_SUCCESS} {msg}[/]")
        else:
            self._log_fn(f"{ICON_SUCCESS}  {msg}")

    def warning(self, msg: str) -> None:
        """Print a warning message."""
        if self.console:
            self.console.print(f"[yellow]{ICON_WARN}  {msg}[/]")
        else:
            self._log_fn(f"{ICON_WARN}  {msg}")

    def error(self, msg: str) -> None:
        """Print an error message."""
        if self.console:
            self.console.print(f"[bold red]{ICON_ERROR} {msg}[/]")
        else:
            self._log_fn(f"{ICON_ERROR}  {msg}")

    def log(self, msg: str) -> None:
        """Print a plain message."""
        self._print(msg)

    # ─── Warn / prompt / fatal ───────────────────────────────────────────────

    def warn_block(self, message: str, severity: str = "warning") -> None:
        """Render a styled Panel for warnings/errors. Does NOT exit."""
        border = "yellow" if severity == "warning" else "red"
        icon = ICON_WARN if severity == "warning" else ICON_ERROR
        label = "WARNING" if severity == "warning" else "ERROR"
        if self.console and Panel is not None:
            panel = Panel(
                message,
                title=f"[bold {border}]{icon} {label}[/]",
                border_style=border,
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"{icon}  {label}: {message}")

    def prompt(self, question: str, default: str = "") -> str:
        """Styled input prompt. Returns the user's answer.

        The question is rendered once via rich (or log_fn) and then
        ``_input_fn`` is called with an empty visible prompt so the
        text is not duplicated on screen.
        """
        if self.console:
            self.console.print(f"[bold cyan]{ICON_INFO}  {question}[/]", end="")
        else:
            self._log_fn(f"{ICON_INFO}  {question}")
        # Pass empty string as the visible prompt to _input_fn so the
        # question isn't printed a second time by input().
        return self._input_fn("", default)

    def fatal(self, message: str) -> None:
        """Print error, prompt to close, then ``sys.exit(1)``."""
        self.error(message)
        try:
            self._input_fn("\nPress ENTER to close this window...", "")
        except Exception:
            pass
        sys.exit(1)

    def version_update(self, url: str, instructions: List[str]) -> None:
        """Info Panel with URL and bulleted instructions for addon updates."""
        if self.console and Panel is not None:
            body = Text()
            body.append(url, style="bold cyan underline")
            for line in instructions:
                body.append(f"\n  - {line}")
            panel = Panel(
                body,
                title=f"[bold cyan]{ICON_INFO} Update Available[/]",
                border_style="cyan",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_INFO}  Update Available")
            self._log_fn(f"  {url}")
            for line in instructions:
                self._log_fn(f"  - {line}")

    # ─── Pack table ──────────────────────────────────────────────────────────

    def pack_start(self) -> None:
        """Begin a new pack table (resets entries)."""
        self._pack_entries = []
        if self.console:
            self.console.print()
            w = self._trace_cols["total"]
            self.console.print(f"[bold cyan] {'File':<{w - 24}} {'Size':>10} {'Status':>10}[/]")
            self.console.print(f"[dim]{'-' * w}[/]")
        else:
            self._log_fn("")
            self._log_fn(f" {'File':<50} {'Size':>10} {'Status':>10}")
            self._log_fn("-" * 70)

    def pack_entry(
        self,
        index: int,
        filepath: str,
        size: Optional[int] = None,
        status: str = "ok",
    ) -> None:
        """Log a single pack entry row in real-time."""
        self._pack_entries.append({"index": index, "filepath": filepath, "size": size, "status": status})
        filename = Path(filepath).name
        size_str = format_size(size) if size else ""
        w = self._trace_cols["total"]
        file_w = w - 24

        def _trunc(val: str, mx: int) -> str:
            return (val[:mx - 1] + ".") if len(val) > mx else val

        name_t = _trunc(filename, file_w)

        if self.console and Text is not None:
            line = Text(" ")
            if status == "ok":
                line.append(f"{name_t:<{file_w}} ", style="white")
                line.append(f"{size_str:>10} ", style="dim")
                line.append(f"{ICON_CHECK:>10}", style="green")
            elif status == "missing":
                line.append(f"{name_t:<{file_w}} ", style="yellow")
                line.append(f"{'':>10} ", style="dim")
                line.append(f"{'MISS':>10}", style="yellow bold")
            else:
                line.append(f"{name_t:<{file_w}} ", style="red")
                line.append(f"{'':>10} ", style="dim")
                line.append(f"{'ERR':>10}", style="red bold")
            self.console.print(line)
        else:
            status_str = ICON_CHECK if status == "ok" else ("MISS" if status == "missing" else "ERR")
            self._log_fn(f" {name_t:<50} {size_str:>10} {status_str:>10}")

    def pack_end(
        self,
        ok_count: int,
        total_size: int = 0,
        title: str = "Pack Complete",
    ) -> None:
        """Print packing summary as a styled Panel."""
        if self.console and Panel is not None and Text is not None:
            body = Text()
            body.append(f"{ICON_CHECK} {ok_count} files", style="bold green")
            body.append(f"  |  {format_size(total_size)}", style="cyan")

            panel = Panel(
                body,
                title=f"[bold white]{ICON_PACKAGE} {title}[/]",
                border_style="green",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_PACKAGE}  {title}: {ok_count} files, {format_size(total_size)}")

    # ─── Zip table (structured callbacks from BAT ZipTransferrer) ───────────

    def zip_start(self, total_files: int, total_bytes: int) -> None:
        """Begin zip progress table."""
        self._zip_total = total_files
        if self.console:
            self.console.print()
            w = self._trace_cols["total"]
            self.console.print(
                f"[bold cyan] {'File':<{w - 30}} {'Size':>10} {'Method':>16}[/]"
            )
            self.console.print(f"[dim]{'-' * w}[/]")
        else:
            self._log_fn("")
            self._log_fn(f" {'File':<42} {'Size':>10} {'Method':>16}")
            self._log_fn("-" * 70)

    def zip_entry(self, index: int, total: int, arcname: str, size: int, method: str) -> None:
        """Log a single file being zipped (structured callback from BAT)."""
        w = self._trace_cols["total"]
        file_w = w - 30

        def _trunc(val: str, mx: int) -> str:
            return (val[:mx - 1] + ".") if len(val) > mx else val

        name_t = _trunc(arcname, file_w)
        size_str = format_size(size) if size else ""

        # Choose icon based on method
        is_store = method.lower().startswith("store")
        icon = ICON_CHECK if is_store else ICON_PACKAGE

        if self.console and Text is not None:
            line = Text(" ")
            line.append(f"{name_t:<{file_w}} ", style="white")
            line.append(f"{size_str:>10} ", style="dim")
            line.append(f"{icon} {method:>13}", style="green" if is_store else "cyan")
            self.console.print(line)
        else:
            self._log_fn(f" {name_t:<42} {size_str:>10} {icon} {method:>13}")

    def zip_done(self, zippath: str, total_files: int, total_bytes: int, elapsed: float) -> None:
        """Print zip completion summary."""
        if self.console and Panel is not None:
            body = (
                f"{ICON_CHECK} {total_files} file(s)  |  "
                f"{format_size(total_bytes)}  |  "
                f"{elapsed:.1f}s"
            )
            panel = Panel(
                body,
                title=f"[bold green]{ICON_SUCCESS} Zip Complete[/]",
                border_style="green",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(
                f"{ICON_SUCCESS}  Zip complete: {total_files} files, "
                f"{format_size(total_bytes)}, {elapsed:.1f}s"
            )

    # ─── Upload table ────────────────────────────────────────────────────────

    def upload_start(self, total: int) -> None:
        """Begin a new upload table."""
        self._upload_entries = []
        self._upload_total = total
        if self.console:
            self.console.print()
            w = self._trace_cols["total"]
            self.console.print(f"[bold cyan] {'Step':<8} {'Action':<{w - 30}} {'Detail':<18} {'':>4}[/]")
            self.console.print(f"[dim]{'-' * w}[/]")
        else:
            self._log_fn("")
            self._log_fn(f" {'Step':<8} {'Action':<40} {'Detail':<18}")
            self._log_fn("-" * 70)

    def upload_entry(
        self,
        step: int,
        action: str,
        detail: str = "",
        status: str = "ok",
    ) -> None:
        """Log a single upload entry row."""
        self._upload_entries.append({"step": step, "action": action, "detail": detail, "status": status})
        total = getattr(self, "_upload_total", step)
        step_str = f"[{step}/{total}]"
        w = self._trace_cols["total"]
        act_w = w - 30

        def _trunc(val: str, mx: int) -> str:
            return (val[:mx - 1] + ".") if len(val) > mx else val

        act_t = _trunc(action, act_w)
        det_t = _trunc(detail, 18)

        if self.console and Text is not None:
            line = Text(" ")
            line.append(f"{step_str:<8}", style="cyan bold")
            line.append(f"{act_t:<{act_w}} ", style="white")
            line.append(f"{det_t:<18} ", style="dim")
            if status == "ok":
                line.append(f"{ICON_CHECK:>4}", style="green")
            elif status == "in_progress":
                line.append(f"{ICON_ARROW:>4}", style="cyan")
            else:
                line.append(f"{ICON_ERROR:>4}", style="red bold")
            self.console.print(line)
        else:
            status_str = ICON_CHECK if status == "ok" else (ICON_ARROW if status == "in_progress" else ICON_ERROR)
            self._log_fn(f" {step_str:<8} {act_t:<40} {det_t:<18} {status_str}")

    def upload_end(self, elapsed: float) -> None:
        """Print upload completion as a styled Panel."""
        if self.console and Panel is not None:
            panel = Panel(
                f"{ICON_CHECK} All files transferred  |  {elapsed:.1f}s",
                title=f"[bold green]{ICON_SUCCESS} Upload Complete[/]",
                border_style="green",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_SUCCESS}  Upload complete in {elapsed:.1f}s")

    # ─── Test report ─────────────────────────────────────────────────────────

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
        """Render the full test-mode report."""
        _sh = shorten_fn or str
        blend_size = 0
        try:
            blend_size = os.path.getsize(blend_path)
        except Exception:
            pass

        # Header
        if self.console and Panel is not None:
            panel = Panel(
                f"Upload type: {upload_type}",
                title=f"[bold yellow]{ICON_SEARCH} SUBMISSION TEST MODE[/]",
                border_style="yellow",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("=" * 70)
            self._log_fn(f"  SUBMISSION TEST MODE - {upload_type}")
            self._log_fn("=" * 70)

        # Info lines
        self.info(f"Blend file: {Path(blend_path).name}  ({format_size(blend_size)})")
        self.info(f"Dependencies traced: {dep_count}")
        self.info(f"Project root: {_sh(project_root)}")
        self.info(f"Same-drive: {same_drive}  |  Cross-drive: {cross_drive}")

        # Breakdown table
        if self.console and Table is not None:
            table = Table(
                title="Dependency Breakdown",
                show_header=True,
                header_style="bold cyan",
                border_style="dim",
                box=box.SIMPLE_HEAD if box else None,
                padding=(0, 1),
                show_edge=False,
            )
            table.add_column("Extension", style="white")
            table.add_column("Count", justify="right", style="cyan")
            for ext, cnt in sorted(by_ext.items(), key=lambda x: -x[1]):
                table.add_row(ext, str(cnt))
            table.add_row("", "")
            table.add_row("Total size", format_size(total_size), style="bold")
            self.console.print()
            self.console.print(table)
        else:
            self._log_fn("")
            self._log_fn("  Dependency breakdown:")
            for ext, cnt in sorted(by_ext.items(), key=lambda x: -x[1]):
                self._log_fn(f"    {ext:12} : {cnt:4} files")
            self._log_fn(f"    Total size: {format_size(total_size)}")

        # Issues
        has_issues = bool(missing or unreadable or cross_drive_files)
        if has_issues:
            issues_lines: List[str] = []
            if missing:
                issues_lines.append(f"MISSING ({len(missing)}):")
                for p in missing:
                    issues_lines.append(f"  - {_sh(p)}")
            if unreadable:
                issues_lines.append(f"UNREADABLE ({len(unreadable)}):")
                for p, err in unreadable:
                    issues_lines.append(f"  - {_sh(p)}")
                    issues_lines.append(f"    {err}")
            if cross_drive_files:
                issues_lines.append(f"CROSS-DRIVE ({len(cross_drive_files)}):")
                for p in cross_drive_files:
                    issues_lines.append(f"  - {_sh(p)}")
            if self.console and Panel is not None:
                panel = Panel(
                    "\n".join(issues_lines),
                    title=f"[bold yellow]{ICON_WARN} Issues[/]",
                    border_style="yellow",
                    padding=(0, 2),
                )
                self.console.print()
                self.console.print(panel)
            else:
                self._log_fn("")
                self._log_fn(f"{ICON_WARN}  Issues:")
                for line in issues_lines:
                    self._log_fn(f"  {line}")

        # Report path
        if report_path:
            self.info(f"Report saved: {report_path}")

        # Summary
        total_issues = len(missing) + len(unreadable) + len(cross_drive_files)
        if self.console and Panel is not None:
            if total_issues == 0:
                body = f"[green]{ICON_CHECK} No issues detected. Ready for submission.[/]"
            else:
                parts = []
                if missing:
                    parts.append(f"{len(missing)} missing")
                if unreadable:
                    parts.append(f"{len(unreadable)} unreadable")
                if cross_drive_files and upload_type == "PROJECT":
                    parts.append(f"{len(cross_drive_files)} cross-drive (excluded)")
                body = f"[yellow]{ICON_WARN} {total_issues} issue(s): {', '.join(parts)}[/]"
            body += f"\n[dim]TEST MODE - No actual submission performed.[/]"
            panel = Panel(
                body,
                title="[bold white]SUMMARY[/]",
                border_style="bright_blue",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("=" * 70)
            self._log_fn("  SUMMARY")
            self._log_fn("=" * 70)
            if total_issues == 0:
                self._log_fn(f"  {ICON_CHECK} No issues detected. Ready for submission.")
            else:
                self._log_fn(f"  {ICON_WARN} {total_issues} issue(s) to review")
            self._log_fn("  [TEST MODE] No actual submission performed.")
            self._log_fn("=" * 70)

    # ─── No-submit report ────────────────────────────────────────────────────

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
            lines.append(f"Main blend S3 key: {main_blend_s3}")
        else:
            lines.append(f"Zip file: {zip_file}")
            if zip_size:
                lines.append(f"Zip size: {format_size(zip_size)}")
        lines.append(f"Storage estimate: {format_size(required_storage)}")
        lines.append("")
        lines.append("Skipping upload and job registration.")

        if self.console and Panel is not None:
            panel = Panel(
                "\n".join(lines),
                title=f"[bold yellow]{ICON_INFO} NO-SUBMIT MODE[/]",
                border_style="yellow",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("=" * 70)
            self._log_fn("  NO-SUBMIT MODE")
            self._log_fn("=" * 70)
            for line in lines:
                self._log_fn(f"  {line}")
            self._log_fn("=" * 70)

    # ─── Missing/unreadable summary ──────────────────────────────────────────

    def missing_unreadable_summary(
        self,
        missing: List[str],
        unreadable: List[Tuple[str, str]],
        header: str = "Dependency check",
        mac_permission_help: Optional[str] = None,
    ) -> None:
        """Styled Panel listing missing/unreadable issues."""
        if not missing and not unreadable:
            return

        lines: List[str] = []
        if missing:
            lines.append(f"Missing files: {len(missing)}")
            for p in missing:
                lines.append(f"  - {p}")
        if unreadable:
            if lines:
                lines.append("")
            lines.append(f"Unreadable files: {len(unreadable)}")
            for p, err in unreadable:
                lines.append(f"  - {p}")
                lines.append(f"    {err}")
        if mac_permission_help:
            lines.append("")
            lines.append(mac_permission_help)

        if self.console and Panel is not None:
            panel = Panel(
                "\n".join(lines),
                title=f"[bold yellow]{ICON_WARN} {header}[/]",
                border_style="yellow",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_WARN}  {header}: issues detected")
            for line in lines:
                self._log_fn(f"  {line}")

    # ─── Storage connection ──────────────────────────────────────────────────

    def storage_connect(self, status: str = "connecting") -> None:
        """Log storage connection status with a key icon."""
        if status == "connecting":
            if self.console and Text is not None:
                line = Text()
                line.append(f" {ICON_KEY} ", style="yellow")
                line.append("Connecting to storage...", style="dim")
                self.console.print(line)
            else:
                self._log_fn(f" {ICON_KEY}  Connecting to storage...")
        else:
            if self.console and Text is not None:
                line = Text()
                line.append(f" {ICON_KEY} ", style="green")
                line.append("Connected to storage", style="green")
                self.console.print(line)
            else:
                self._log_fn(f" {ICON_KEY}  Connected to storage")

    # ─── Job complete ────────────────────────────────────────────────────────

    def job_complete(self, web_url: str) -> None:
        """Log that the job page was opened in the browser."""
        if self.console and Panel is not None:
            panel = Panel(
                f"[cyan]{web_url}[/]",
                title=f"[bold green]{ICON_CHECK} Opened in Browser[/]",
                border_style="green",
                padding=(0, 2),
            )
            self.console.print(panel)
        else:
            self._log_fn(f"{ICON_CHECK}  Opened {web_url} in your browser.")


# ─── Factory function ─────────────────────────────────────────────────────────

def create_logger(
    log_fn: Optional[Callable[[str], None]] = None,
    input_fn: Optional[Callable[[str, str], str]] = None,
) -> SubmitLogger:
    """Create a SubmitLogger instance."""
    return SubmitLogger(log_fn, input_fn=input_fn)
