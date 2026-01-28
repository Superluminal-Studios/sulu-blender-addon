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
HAS_RICH = False
Console = None
Table = None
Panel = None
Text = None
Style = None
box = None

def _try_import_rich():
    """Try to import rich from various locations."""
    global HAS_RICH, Console, Table, Panel, Text, Style, box

    # Try relative import first (when imported as part of package)
    try:
        from ..rich.console import Console as _Console
        from ..rich.table import Table as _Table
        from ..rich.panel import Panel as _Panel
        from ..rich.text import Text as _Text
        from ..rich.style import Style as _Style
        from ..rich import box as _box
        Console = _Console
        Table = _Table
        Panel = _Panel
        Text = _Text
        Style = _Style
        box = _box
        HAS_RICH = True
        return True
    except ImportError:
        pass

    # Try absolute import with package name (when running as subprocess)
    try:
        import importlib
        import sys
        # Find the addon package name from sys.modules
        for name, mod in sys.modules.items():
            if hasattr(mod, '__path__') and 'rich' not in name:
                try:
                    rich_mod = importlib.import_module(f"{name}.rich")
                    Console = getattr(importlib.import_module(f"{name}.rich.console"), 'Console')
                    Table = getattr(importlib.import_module(f"{name}.rich.table"), 'Table')
                    Panel = getattr(importlib.import_module(f"{name}.rich.panel"), 'Panel')
                    Text = getattr(importlib.import_module(f"{name}.rich.text"), 'Text')
                    Style = getattr(importlib.import_module(f"{name}.rich.style"), 'Style')
                    box = importlib.import_module(f"{name}.rich.box")
                    HAS_RICH = True
                    return True
                except (ImportError, AttributeError):
                    continue
    except Exception:
        pass

    return False

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
    if HAS_RICH and Console is not None:
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

    def __init__(self, log_fn: Optional[Callable[[str], None]] = None):
        """
        Initialize the logger.

        Args:
            log_fn: Optional fallback logging function for plain text mode.
        """
        self.console = get_console() if HAS_RICH else None
        self._log_fn = log_fn or print
        self._trace_entries: List[TraceEntry] = []

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

    def stage_header(self, stage_num: int, title: str, subtitle: str = "") -> None:
        """Print a beautiful stage header."""
        if self.console:
            header_text = f"STAGE {stage_num}: {title}"
            panel = Panel(
                Text(subtitle, style="dim") if subtitle else "",
                title=f"[bold white]{header_text}[/]",
                border_style="bright_blue",
                padding=(0, 2),
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("═" * 70)
            self._log_fn(f"  STAGE {stage_num}: {title}")
            if subtitle:
                self._log_fn(f"  {subtitle}")
            self._log_fn("═" * 70)

    # ─── Trace logging ────────────────────────────────────────────────────────

    def trace_start(self, blend_path: str) -> None:
        """Start tracing - show main file info."""
        self._trace_entries = []
        if self.console:
            self.console.print()
            self.console.print(f"[bold cyan]{ICON_FOLDER} Main file:[/] {Path(blend_path).name}")
            self.console.print(f"[dim]{ICON_SEARCH} Scanning for dependencies...[/]")
            self.console.print()
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_FOLDER}  Main file: {Path(blend_path).name}")
            self._log_fn(f"{ICON_SEARCH}  Scanning for dependencies...")
            self._log_fn("")

    def trace_entry(
        self,
        source_blend: str,
        block_type: str,
        block_name: str,
        found_file: str,
        status: str,
        error_msg: Optional[str] = None,
    ) -> None:
        """Log a single trace entry - entries are collected and displayed in trace_summary()."""
        entry = TraceEntry(source_blend, block_type, block_name, found_file, status, error_msg)
        self._trace_entries.append(entry)

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

            # Add columns - File column gets most space
            table.add_column("Type", style="bright_magenta", no_wrap=True, width=10)
            table.add_column("Block", style="white", no_wrap=False, ratio=1)
            table.add_column("File", style="white", no_wrap=False, ratio=2)
            table.add_column("Status", justify="right", no_wrap=True, width=12)

            # Add rows
            for entry in self._trace_entries:
                type_name = BLOCK_TYPE_NAMES.get(entry.block_type, entry.block_type)
                type_style = BLOCK_TYPE_STYLES.get(entry.block_type, "white")

                # Status cell with color and icon
                if entry.status == "ok":
                    status_cell = Text(f"{ICON_CHECK} OK", style="green")
                elif entry.status == "missing":
                    status_cell = Text(f"{ICON_WARN} MISSING", style="yellow bold")
                else:
                    status_cell = Text(f"{ICON_CROSS} ERROR", style="red bold")

                # Build file cell with optional error message
                file_cell = Text()
                if entry.status == "ok":
                    file_cell.append(entry.found_file, style="white")
                else:
                    file_cell.append(entry.found_file, style="dim")
                    if entry.error_msg:
                        file_cell.append(f"\n  {ICON_ARROW} {entry.error_msg}", style="red dim")

                table.add_row(
                    Text(f"[{type_name}]", style=type_style),
                    entry.block_name,
                    file_cell,
                    status_cell,
                )

            self.console.print(table)
        else:
            # Plain text fallback - print each entry
            for entry in self._trace_entries:
                type_name = BLOCK_TYPE_NAMES.get(entry.block_type, entry.block_type)
                status_icon = ICON_CHECK if entry.status == "ok" else (f"{ICON_WARN} MISSING" if entry.status == "missing" else f"{ICON_CROSS} UNREADABLE")
                self._log_fn(f"  [{type_name:10}] {entry.block_name:20} {ICON_ARROW} {entry.found_file}  {status_icon}")
                if entry.error_msg:
                    self._log_fn(f"               {ICON_ARROW} {entry.error_msg}")

    def trace_summary(
        self,
        total: int,
        missing: int,
        unreadable: int,
        project_root: Optional[str] = None,
        cross_drive: int = 0,
    ) -> None:
        """Print trace table and summary."""
        # First, render the trace table with all collected entries
        self._render_trace_table()

        if self.console:
            self.console.print()

            # Summary line
            summary = Text()
            summary.append(f"{ICON_CHART} Trace complete: ", style="bold")
            summary.append(f"{total}", style="cyan bold")
            summary.append(" dependencies found")
            self.console.print(summary)

            if missing > 0:
                self.console.print(f"    [yellow]{ICON_WARN}  {missing} missing file(s)[/]")
            if unreadable > 0:
                self.console.print(f"    [red]{ICON_ERROR}  {unreadable} unreadable file(s)[/]")
            if cross_drive > 0:
                self.console.print(f"    [yellow]{ICON_WARN}  {cross_drive} on different drive (excluded)[/]")

            if project_root:
                self.console.print()
                self.console.print(f"[bold cyan]{ICON_FOLDER} Project root:[/] {project_root}")
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_CHART}  Trace complete: {total} dependencies found")
            if missing > 0:
                self._log_fn(f"    {ICON_WARN}  {missing} missing file(s)")
            if unreadable > 0:
                self._log_fn(f"    {ICON_ERROR}  {unreadable} unreadable file(s)")
            if cross_drive > 0:
                self._log_fn(f"    {ICON_WARN}  {cross_drive} on different drive (excluded)")
            if project_root:
                self._log_fn("")
                self._log_fn(f"{ICON_FOLDER}  Project root: {project_root}")

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
        """Log an upload step starting."""
        if self.console:
            self.console.print()
            self.console.print(f"[bold cyan]{ICON_ROCKET} [{step}/{total_steps}][/] {title}")
            if detail:
                self.console.print(f"    [dim]{detail}[/]")
            self.console.print()
        else:
            self._log_fn("")
            self._log_fn(f"{ICON_ROCKET}  [{step}/{total_steps}] {title}")
            if detail:
                self._log_fn(f"    {detail}")
            self._log_fn("")

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


# ─── Factory function ─────────────────────────────────────────────────────────

def create_logger(log_fn: Optional[Callable[[str], None]] = None) -> SubmitLogger:
    """Create a SubmitLogger instance."""
    return SubmitLogger(log_fn)
