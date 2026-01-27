"""
submit_tui.py - Beautiful TUI for the Superluminal submission process.

Uses only rich + tqdm (+ stdlib). Degrades gracefully in non-interactive environments.

Phases:
1. Tracing  - Two-column live display (datablocks | files discovered)
2. Packing  - File mapping/compression with progress
3. Upload   - Transfer progress with rclone stats
4. Status   - Final job registration result
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Any

# Single keypress input (no Enter required)
def _getch() -> str:
    """Get a single character from stdin without requiring Enter."""
    try:
        if sys.platform == "win32":
            import msvcrt
            ch = msvcrt.getch()
            # Handle escape sequences
            if ch in (b'\x00', b'\xe0'):
                msvcrt.getch()  # consume second byte
                return ""
            if ch == b'\x1b':  # ESC
                return "ESC"
            return ch.decode('utf-8', errors='ignore')
        else:
            import tty
            import termios
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == '\x1b':  # ESC
                    return "ESC"
                return ch
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        # Fallback to regular input
        result = input()
        return result[0] if result else ""


def _wait_for_key(valid_keys: List[str], timeout: float = 0) -> str:
    """Wait for one of the valid keys to be pressed. Returns the key or 'ESC'."""
    valid_lower = [k.lower() for k in valid_keys]
    while True:
        ch = _getch()
        if ch == "ESC":
            return "ESC"
        if ch.lower() in valid_lower:
            return ch.lower()
        # Also accept Enter as confirmation (returns first valid key)
        if ch in ('\r', '\n') and valid_keys:
            return valid_keys[0].lower()

# Detect if we're in a real terminal
_IS_TTY = sys.stderr.isatty() if hasattr(sys.stderr, "isatty") else False

# Rich imports - try multiple methods
RICH_AVAILABLE = False
Console = None
Group = None
Live = None
Layout = None
Panel = None
Progress = None
SpinnerColumn = None
TextColumn = None
BarColumn = None
TaskProgressColumn = None
TimeElapsedColumn = None
TimeRemainingColumn = None
DownloadColumn = None
TransferSpeedColumn = None
Table = None
Text = None
Style = None
Align = None
box = None


def _try_import_rich():
    """Try to import rich from various locations."""
    global RICH_AVAILABLE, Console, Group, Live, Layout, Panel, Progress
    global SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    global TimeElapsedColumn, TimeRemainingColumn, DownloadColumn, TransferSpeedColumn
    global Table, Text, Style, Align, box

    # Method 1: Try relative import (works when imported as part of package)
    try:
        from ..rich.console import Console as _Console, Group as _Group
        from ..rich.live import Live as _Live
        from ..rich.layout import Layout as _Layout
        from ..rich.panel import Panel as _Panel
        from ..rich.progress import (
            Progress as _Progress,
            SpinnerColumn as _SpinnerColumn,
            TextColumn as _TextColumn,
            BarColumn as _BarColumn,
            TaskProgressColumn as _TaskProgressColumn,
            TimeElapsedColumn as _TimeElapsedColumn,
            TimeRemainingColumn as _TimeRemainingColumn,
            DownloadColumn as _DownloadColumn,
            TransferSpeedColumn as _TransferSpeedColumn,
        )
        from ..rich.table import Table as _Table
        from ..rich.text import Text as _Text
        from ..rich.style import Style as _Style
        from ..rich.align import Align as _Align
        from ..rich import box as _box

        Console, Group = _Console, _Group
        Live, Layout, Panel = _Live, _Layout, _Panel
        Progress = _Progress
        SpinnerColumn, TextColumn, BarColumn = _SpinnerColumn, _TextColumn, _BarColumn
        TaskProgressColumn = _TaskProgressColumn
        TimeElapsedColumn, TimeRemainingColumn = _TimeElapsedColumn, _TimeRemainingColumn
        DownloadColumn, TransferSpeedColumn = _DownloadColumn, _TransferSpeedColumn
        Table, Text, Style, Align, box = _Table, _Text, _Style, _Align, _box
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
        import rich.live
        import rich.layout
        import rich.panel
        import rich.progress
        import rich.table
        import rich.text
        import rich.style
        import rich.align
        import rich.box

        Console, Group = rich.console.Console, rich.console.Group
        Live = rich.live.Live
        Layout = rich.layout.Layout
        Panel = rich.panel.Panel
        Progress = rich.progress.Progress
        SpinnerColumn = rich.progress.SpinnerColumn
        TextColumn = rich.progress.TextColumn
        BarColumn = rich.progress.BarColumn
        TaskProgressColumn = rich.progress.TaskProgressColumn
        TimeElapsedColumn = rich.progress.TimeElapsedColumn
        TimeRemainingColumn = rich.progress.TimeRemainingColumn
        DownloadColumn = rich.progress.DownloadColumn
        TransferSpeedColumn = rich.progress.TransferSpeedColumn
        Table = rich.table.Table
        Text = rich.text.Text
        Style = rich.style.Style
        Align = rich.align.Align
        box = rich.box
        RICH_AVAILABLE = True
        return
    except ImportError:
        pass

    # Method 3: System rich as last resort
    try:
        from rich.console import Console as _Console, Group as _Group
        from rich.live import Live as _Live
        from rich.layout import Layout as _Layout
        from rich.panel import Panel as _Panel
        from rich.progress import (
            Progress as _Progress,
            SpinnerColumn as _SpinnerColumn,
            TextColumn as _TextColumn,
            BarColumn as _BarColumn,
            TaskProgressColumn as _TaskProgressColumn,
            TimeElapsedColumn as _TimeElapsedColumn,
            TimeRemainingColumn as _TimeRemainingColumn,
            DownloadColumn as _DownloadColumn,
            TransferSpeedColumn as _TransferSpeedColumn,
        )
        from rich.table import Table as _Table
        from rich.text import Text as _Text
        from rich.style import Style as _Style
        from rich.align import Align as _Align
        from rich import box as _box

        Console, Group = _Console, _Group
        Live, Layout, Panel = _Live, _Layout, _Panel
        Progress = _Progress
        SpinnerColumn, TextColumn, BarColumn = _SpinnerColumn, _TextColumn, _BarColumn
        TaskProgressColumn = _TaskProgressColumn
        TimeElapsedColumn, TimeRemainingColumn = _TimeElapsedColumn, _TimeRemainingColumn
        DownloadColumn, TransferSpeedColumn = _DownloadColumn, _TransferSpeedColumn
        Table, Text, Style, Align, box = _Table, _Text, _Style, _Align, _box
        RICH_AVAILABLE = True
        return
    except ImportError:
        pass


# Try importing rich at module load time
_try_import_rich()

# ---------------------------------------------------------------------------
# Color palette (minimal, consistent)
# ---------------------------------------------------------------------------
STYLE_HEADER = "bold cyan"
STYLE_SUCCESS = "bold green"
STYLE_WARNING = "bold yellow"
STYLE_ERROR = "bold red"
STYLE_DIM = "dim"
STYLE_HIGHLIGHT = "bold white"
STYLE_ACCENT = "cyan"
STYLE_MUTED = "dim white"

# ---------------------------------------------------------------------------
# Status symbols for consistent display
# ---------------------------------------------------------------------------
SYM_OK = "✓"        # File exists / operation succeeded
SYM_MISSING = "✗"   # File missing
SYM_WARN = "⚠"      # Warning (unreadable, etc.)
SYM_REWRITE = "↻"   # Blend file rewritten
SYM_ACTIVE = "●"    # Currently processing
SYM_PENDING = "○"   # Pending / not started
SYM_ARROW = "→"     # Transfer / mapping


# ---------------------------------------------------------------------------
# Dataclasses for state tracking
# ---------------------------------------------------------------------------
@dataclass
class FileEntry:
    """A file with its status."""
    path: str
    status: str = "ok"  # "ok", "missing", "unreadable", "rewrite", "active"

    def styled(self, max_len: int = 45) -> "Text":
        """Return styled text for this file entry."""
        t = Text()
        if self.status == "ok":
            t.append(f"{SYM_OK} ", style=STYLE_SUCCESS)
        elif self.status == "missing":
            t.append(f"{SYM_MISSING} ", style=STYLE_ERROR)
        elif self.status == "unreadable":
            t.append(f"{SYM_WARN} ", style=STYLE_WARNING)
        elif self.status == "rewrite":
            t.append(f"{SYM_REWRITE} ", style=STYLE_ACCENT)
        elif self.status == "active":
            t.append(f"{SYM_ARROW} ", style=STYLE_ACCENT)
        else:
            t.append("  ", style=STYLE_DIM)
        t.append(_shorten(self.path, max_len), style=STYLE_MUTED if self.status == "ok" else None)
        return t


@dataclass
class TraceState:
    """State for the tracing phase."""

    blendfiles_opened: List[str] = field(default_factory=list)
    datablocks_seen: deque = field(default_factory=lambda: deque(maxlen=30))
    files_found: deque = field(default_factory=lambda: deque(maxlen=30))  # List of FileEntry
    total_files: int = 0
    total_datablocks: int = 0
    files_ok: int = 0
    files_missing: int = 0
    files_unreadable: int = 0
    current_blendfile: str = ""
    start_time: float = 0.0
    elapsed_time: float = 0.0  # Frozen when done
    done: bool = False


@dataclass
class PackState:
    """State for the packing phase."""

    files_total: int = 0
    files_processed: int = 0
    files_packed: deque = field(default_factory=lambda: deque(maxlen=30))  # List of FileEntry
    current_file: str = ""
    bytes_total: int = 0
    bytes_processed: int = 0
    mode: str = ""  # "PROJECT" or "ZIP", set when pack_start is called
    rewritten_blends: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    unreadable_files: Dict[str, str] = field(default_factory=dict)
    start_time: float = 0.0
    elapsed_time: float = 0.0  # Frozen when done
    done: bool = False


@dataclass
class UploadPhaseState:
    """State for a single upload phase (blend, deps, manifest, addons)."""

    name: str = ""
    label: str = ""
    bytes_total: int = 0
    bytes_transferred: int = 0
    files_total: int = 0
    files_transferred: int = 0
    current_file: str = ""
    start_time: float = 0.0
    elapsed_time: float = 0.0
    done: bool = False
    active: bool = False


@dataclass
class UploadState:
    """State for the upload phase."""

    # Individual upload phases - initialized based on mode
    phases: Dict[str, UploadPhaseState] = field(default_factory=dict)
    # Which phases to show (in order)
    phase_order: List[str] = field(default_factory=list)
    current_phase: str = ""
    files_uploaded: deque = field(default_factory=lambda: deque(maxlen=10))
    start_time: float = 0.0
    elapsed_time: float = 0.0  # Frozen when done
    done: bool = False
    include_addons: bool = False  # Whether addons phase should be shown


def _create_upload_phases_for_mode(upload_type: str, include_addons: bool = False) -> Tuple[Dict[str, UploadPhaseState], List[str]]:
    """Create upload phases based on upload mode."""
    if upload_type == "ZIP":
        phases = {
            "zip": UploadPhaseState(name="zip", label="Main Zip"),
        }
        order = ["zip"]
        if include_addons:
            phases["addons"] = UploadPhaseState(name="addons", label="Add-ons")
            order.append("addons")
    else:  # PROJECT
        phases = {
            "blend": UploadPhaseState(name="blend", label="Main Blend"),
            "deps": UploadPhaseState(name="deps", label="Dependencies"),
        }
        order = ["blend", "deps"]
        if include_addons:
            phases["addons"] = UploadPhaseState(name="addons", label="Add-ons")
            order.append("addons")
    return phases, order


@dataclass
class SubmitTUIState:
    """Overall TUI state."""

    trace: TraceState = field(default_factory=TraceState)
    pack: PackState = field(default_factory=PackState)
    upload: UploadState = field(default_factory=UploadState)
    current_phase: str = "init"  # init, question, trace, pack, upload, done
    job_name: str = ""
    project_name: str = ""
    blend_name: str = ""
    upload_type: str = "PROJECT"
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    # Question state
    question_title: str = ""
    question_text: str = ""
    question_options: List[str] = field(default_factory=list)
    question_hotkeys: List[str] = field(default_factory=list)  # e.g., ["y", "n"]
    question_selected: int = 0
    # Inline prompt (shown at bottom of main screen)
    inline_prompt: str = ""
    inline_prompt_options: str = ""  # e.g., "Open [y]  Close [n]"


# ---------------------------------------------------------------------------
# Plain-text fallback (for non-TTY / CI)
# ---------------------------------------------------------------------------
class PlainTextUI:
    """Fallback UI that prints plain text - no animations."""

    def __init__(self, state: SubmitTUIState):
        self.state = state
        self._last_phase = ""
        self._trace_file_count = 0
        self._pack_file_count = 0

    def update(self) -> None:
        """Called periodically - print updates when state changes."""
        s = self.state

        if s.current_phase != self._last_phase:
            self._last_phase = s.current_phase
            if s.current_phase == "trace":
                print(f"\n[TRACE] Scanning dependencies for: {s.blend_name}")
            elif s.current_phase == "pack":
                print(f"\n[PACK] Packing files ({s.upload_type} mode)")
            elif s.current_phase == "upload":
                print(f"\n[UPLOAD] Uploading to cloud storage")
            elif s.current_phase == "done":
                print(f"\n[DONE] Submission complete")

        # Print trace progress periodically
        if s.current_phase == "trace":
            if s.trace.total_files > self._trace_file_count + 50:
                self._trace_file_count = s.trace.total_files
                print(f"  Found {s.trace.total_files} files...")

        # Print pack progress periodically
        if s.current_phase == "pack":
            if s.pack.files_processed > self._pack_file_count + 20:
                self._pack_file_count = s.pack.files_processed
                pct = (
                    int(100 * s.pack.files_processed / s.pack.files_total)
                    if s.pack.files_total > 0
                    else 0
                )
                print(f"  Packed {s.pack.files_processed}/{s.pack.files_total} files ({pct}%)")

    def finish(self, success: bool, message: str = "") -> None:
        """Called when submission completes."""
        if success:
            print(f"\n[OK] {message or 'Submission successful'}")
        else:
            print(f"\n[ERROR] {message or 'Submission failed'}")


# ---------------------------------------------------------------------------
# Rich TUI (the beautiful version)
# ---------------------------------------------------------------------------
class RichSubmitTUI:
    """Beautiful TUI for the submission process using rich."""

    def __init__(self, state: SubmitTUIState, console: Optional["Console"] = None, force: bool = False):
        self.state = state
        # Force terminal mode when requested (e.g., when launched from Blender)
        self.console = console or Console(stderr=True, force_terminal=True)
        self._live: Optional[Live] = None
        self._lock = threading.Lock()

    def _make_header(self) -> Text:
        """Create a compact header line."""
        s = self.state
        header = Text()
        header.append("SUPERLUMINAL ", style=STYLE_HEADER)
        header.append(s.blend_name or "Submit", style=STYLE_HIGHLIGHT)
        header.append(" → ", style=STYLE_DIM)
        header.append(s.project_name or "Project", style=STYLE_ACCENT)
        header.append(f" ({s.upload_type})", style=STYLE_MUTED)
        return header

    def _make_progress_summary(self) -> Text:
        """Create a single-line progress summary showing all phases."""
        s = self.state
        phases = ["trace", "pack", "upload"]
        phase_idx = {"trace": 0, "pack": 1, "upload": 2, "done": 3}
        current_idx = phase_idx.get(s.current_phase, -1)

        summary = Text()
        for i, phase in enumerate(phases):
            if i > 0:
                summary.append(" → ", style=STYLE_DIM)

            if i < current_idx or s.current_phase == "done":
                # Completed
                summary.append("✓ ", style=STYLE_SUCCESS)
                summary.append(phase.capitalize(), style=STYLE_SUCCESS)
            elif i == current_idx:
                # Active
                summary.append("● ", style=STYLE_ACCENT)
                summary.append(phase.capitalize(), style="bold " + STYLE_ACCENT)
            else:
                # Pending
                summary.append("○ ", style=STYLE_DIM)
                summary.append(phase.capitalize(), style=STYLE_DIM)

        return summary

    def _make_trace_panel(self) -> Panel:
        """Create a compact two-column tracing panel."""
        s = self.state.trace
        is_active = self.state.current_phase == "trace"
        is_done = s.done or self.state.current_phase in ("pack", "upload", "done")
        is_pending = not is_active and not is_done

        # Create a compact table with two columns side by side
        table = Table(
            show_header=True,
            header_style=STYLE_ACCENT if is_active else STYLE_DIM,
            box=box.SIMPLE_HEAD,
            expand=True,
            padding=(0, 1),
            show_edge=False,
        )

        # Build header with counts
        db_header = f"Traced Datablocks ({s.total_datablocks})"
        file_counts = []
        if s.files_ok > 0:
            file_counts.append(f"{SYM_OK}{s.files_ok}")
        if s.files_missing > 0:
            file_counts.append(f"{SYM_MISSING}{s.files_missing}")
        if s.files_unreadable > 0:
            file_counts.append(f"{SYM_WARN}{s.files_unreadable}")
        file_header = f"Found Files ({s.total_files})"
        if file_counts:
            file_header += f"  {' '.join(file_counts)}"

        table.add_column(db_header, style=STYLE_MUTED if is_active else STYLE_DIM, no_wrap=True, ratio=1)
        table.add_column(file_header, style=STYLE_MUTED if is_active else STYLE_DIM, no_wrap=True, ratio=1)

        # Show only last 4 items from each column
        datablocks = list(s.datablocks_seen)[-4:]
        files = list(s.files_found)[-4:]
        max_rows = max(len(datablocks), len(files), 2 if is_pending else 1)

        for i in range(max_rows):
            db_text = Text(overflow="ellipsis")
            if i < len(datablocks):
                db_text.append(datablocks[i], style=STYLE_MUTED if is_active else STYLE_DIM)

            file_text = Text(overflow="ellipsis")
            if i < len(files):
                entry = files[i]
                if isinstance(entry, FileEntry):
                    file_text = entry.styled(40)
                else:
                    file_text.append(str(entry), style=STYLE_MUTED if is_active else STYLE_DIM)

            table.add_row(db_text, file_text)

        # Status line - use frozen elapsed_time if done
        status_text = Text()
        if is_done:
            elapsed = s.elapsed_time if s.elapsed_time > 0 else 0
            status_text.append(f"{SYM_OK} Complete", style=STYLE_SUCCESS)
            status_text.append(f"  {elapsed:.1f}s", style=STYLE_DIM)
        elif is_active:
            elapsed = time.time() - s.start_time if s.start_time else 0
            if s.current_blendfile:
                status_text.append(f"Scanning: {_shorten(s.current_blendfile, 30)}", style=STYLE_MUTED)
            status_text.append(f"  {elapsed:.1f}s", style=STYLE_DIM)
        else:
            status_text.append(f"{SYM_PENDING} Waiting...", style=STYLE_DIM)

        # Title and border style based on state
        if is_done:
            title = f"[{STYLE_SUCCESS}]{SYM_OK} Trace[/]"
            border = STYLE_SUCCESS
        elif is_active:
            title = f"[bold {STYLE_ACCENT}]{SYM_ACTIVE} Trace[/]"
            border = STYLE_ACCENT
        else:
            title = f"[{STYLE_DIM}]{SYM_PENDING} Trace[/]"
            border = STYLE_DIM

        return Panel(
            Group(table, status_text),
            title=title,
            border_style=border,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def _make_pack_panel(self) -> Panel:
        """Create the packing progress panel - same layout for PROJECT and ZIP."""
        s = self.state.pack
        is_active = self.state.current_phase == "pack"
        is_done = s.done or self.state.current_phase in ("upload", "done")
        is_pending = not is_active and not is_done

        # Create a table showing files being packed
        table = Table(
            show_header=True,
            header_style=STYLE_ACCENT if is_active else STYLE_DIM,
            box=box.SIMPLE_HEAD,
            expand=True,
            padding=(0, 1),
            show_edge=False,
        )

        # Build headers with counts
        mode = s.mode if s.mode else self.state.upload_type
        action_word = "Mapping" if mode == "PROJECT" else "Compressing"
        if s.files_total > 0:
            packed_header = f"{action_word} Files ({s.files_processed}/{s.files_total})"
        else:
            packed_header = f"{action_word} Files"

        stats_parts = []
        if s.rewritten_blends:
            stats_parts.append(f"{SYM_REWRITE}{len(s.rewritten_blends)}")
        if s.missing_files:
            stats_parts.append(f"{SYM_MISSING}{len(s.missing_files)}")
        if s.unreadable_files:
            stats_parts.append(f"{SYM_WARN}{len(s.unreadable_files)}")

        stats_header = "  ".join(stats_parts) if stats_parts else ""

        table.add_column(packed_header, style=STYLE_MUTED if is_active else STYLE_DIM, no_wrap=True, ratio=3)
        table.add_column(stats_header, style=STYLE_MUTED if is_active else STYLE_DIM, no_wrap=True, ratio=1, justify="right")

        # Show recent files being packed
        files = list(s.files_packed)[-4:]
        for entry in files:
            if isinstance(entry, FileEntry):
                table.add_row(entry.styled(50), Text(""))
            else:
                table.add_row(Text(str(entry), style=STYLE_MUTED), Text(""))

        # Pad with empty rows if needed
        for _ in range(max(0, 2 - len(files))):
            table.add_row(Text(""), Text(""))

        # Progress bar / status at bottom - use frozen elapsed_time if done
        status_text = Text()
        if is_done:
            elapsed = s.elapsed_time if s.elapsed_time > 0 else 0
            status_text.append(f"{SYM_OK} Complete", style=STYLE_SUCCESS)
            status_text.append(f"  {s.files_processed} files  {elapsed:.1f}s", style=STYLE_DIM)
        elif is_active:
            pct = int(100 * s.files_processed / s.files_total) if s.files_total > 0 else 0
            elapsed = time.time() - s.start_time if s.start_time else 0
            status_text.append(f"[{pct:3d}%] ", style=STYLE_ACCENT)
            bar_width = 30
            filled = int(bar_width * s.files_processed / s.files_total) if s.files_total > 0 else 0
            status_text.append("█" * filled, style=STYLE_ACCENT)
            status_text.append("░" * (bar_width - filled), style=STYLE_DIM)
            status_text.append(f"  {elapsed:.1f}s", style=STYLE_DIM)
        else:
            status_text.append(f"{SYM_PENDING} Waiting...", style=STYLE_DIM)

        # Title and border style based on state
        display_mode = s.mode if s.mode else self.state.upload_type
        mode_str = f" ({display_mode})" if display_mode else ""
        if is_done:
            title = f"[{STYLE_SUCCESS}]{SYM_OK} Pack{mode_str}[/]"
            border = STYLE_SUCCESS
        elif is_active:
            title = f"[bold {STYLE_ACCENT}]{SYM_ACTIVE} Pack{mode_str}[/]"
            border = STYLE_ACCENT
        else:
            title = f"[{STYLE_DIM}]{SYM_PENDING} Pack[/]"
            border = STYLE_DIM

        return Panel(
            Group(table, status_text),
            title=title,
            border_style=border,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def _make_upload_phase_row(self, phase: "UploadPhaseState") -> Text:
        """Create a single upload phase progress row."""
        row = Text()

        # Status symbol
        if phase.done:
            row.append(f"{SYM_OK} ", style=STYLE_SUCCESS)
        elif phase.active:
            row.append(f"{SYM_ACTIVE} ", style=STYLE_ACCENT)
        else:
            row.append(f"{SYM_PENDING} ", style=STYLE_DIM)

        # Label (fixed width)
        label = f"{phase.label:<14}"
        style = STYLE_SUCCESS if phase.done else (STYLE_ACCENT if phase.active else STYLE_DIM)
        row.append(label, style=style)

        # Progress bar
        bar_width = 20
        if phase.bytes_total > 0:
            pct = phase.bytes_transferred / phase.bytes_total
            filled = int(bar_width * pct)
            if phase.done:
                row.append("█" * bar_width, style=STYLE_SUCCESS)
            elif phase.active:
                row.append("█" * filled, style=STYLE_ACCENT)
                row.append("░" * (bar_width - filled), style=STYLE_DIM)
            else:
                row.append("░" * bar_width, style=STYLE_DIM)
        else:
            row.append("░" * bar_width, style=STYLE_DIM)

        # Size info
        row.append("  ", style=STYLE_DIM)
        if phase.bytes_total > 0:
            size_str = f"{_format_size(phase.bytes_transferred):>8} / {_format_size(phase.bytes_total):<8}"
            row.append(size_str, style=STYLE_MUTED if phase.active or phase.done else STYLE_DIM)
        else:
            row.append(" " * 20, style=STYLE_DIM)

        # Time
        if phase.done:
            row.append(f"  {phase.elapsed_time:.1f}s", style=STYLE_DIM)
        elif phase.active and phase.start_time > 0:
            elapsed = time.time() - phase.start_time
            row.append(f"  {elapsed:.1f}s", style=STYLE_DIM)

        return row

    def _make_upload_panel(self) -> Panel:
        """Create the upload progress panel with relevant progress bars for mode."""
        s = self.state.upload
        is_active = self.state.current_phase == "upload"
        is_done = s.done or self.state.current_phase == "done"
        is_pending = not is_active and not is_done

        parts = []

        # Show only relevant upload phases based on mode
        for phase_name in s.phase_order:
            phase = s.phases.get(phase_name)
            if phase:
                parts.append(self._make_upload_phase_row(phase))

        # Current file being uploaded
        if is_active and s.current_phase:
            current_phase = s.phases.get(s.current_phase)
            if current_phase and current_phase.current_file:
                file_text = Text()
                file_text.append(f"  {SYM_ARROW} ", style=STYLE_ACCENT)
                file_text.append(_shorten(current_phase.current_file, 50), style=STYLE_MUTED)
                parts.append(file_text)

        # Status line
        status_text = Text()
        if is_done:
            elapsed = s.elapsed_time if s.elapsed_time > 0 else 0
            total_bytes = sum(p.bytes_total for p in s.phases.values())
            status_text.append(f"{SYM_OK} Complete", style=STYLE_SUCCESS)
            status_text.append(f"  {_format_size(total_bytes)}  {elapsed:.1f}s", style=STYLE_DIM)
        elif is_active:
            elapsed = time.time() - s.start_time if s.start_time else 0
            status_text.append(f"Uploading...  {elapsed:.1f}s", style=STYLE_MUTED)
        else:
            status_text.append(f"{SYM_PENDING} Waiting...", style=STYLE_DIM)
        parts.append(status_text)

        # Title and border style based on state
        if is_done:
            title = f"[{STYLE_SUCCESS}]{SYM_OK} Upload[/]"
            border = STYLE_SUCCESS
        elif is_active:
            title = f"[bold {STYLE_ACCENT}]{SYM_ACTIVE} Upload[/]"
            border = STYLE_ACCENT
        else:
            title = f"[{STYLE_DIM}]{SYM_PENDING} Upload[/]"
            border = STYLE_DIM

        return Panel(
            Group(*parts),
            title=title,
            border_style=border,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def _make_question_panel(self) -> Panel:
        """Create a beautiful question prompt panel with simple y/n options."""
        s = self.state
        parts = []

        # Question text - handle multi-line
        for line in s.question_text.split("\n"):
            line_text = Text()
            line_text.append(line, style=STYLE_HIGHLIGHT if line.strip() else STYLE_DIM)
            parts.append(line_text)

        parts.append(Text(""))

        # Simple y/n style options
        options_row = Text()
        options_row.append("  ", style=STYLE_DIM)
        for i, option in enumerate(s.question_options):
            if i > 0:
                options_row.append("     ", style=STYLE_DIM)

            # Get the hotkey (first letter or y/n)
            hotkey = s.question_hotkeys[i] if hasattr(s, 'question_hotkeys') and i < len(s.question_hotkeys) else str(i + 1)

            options_row.append(option, style="bold cyan")
            options_row.append(" [", style=STYLE_DIM)
            options_row.append(hotkey, style="bold white")
            options_row.append("]", style=STYLE_DIM)

        parts.append(options_row)

        return Panel(
            Group(*parts),
            title=f"[bold {STYLE_ACCENT}]  {s.question_title}  [/]",
            border_style=STYLE_ACCENT,
            box=box.DOUBLE,
            padding=(1, 3),
        )

    def _make_footer(self) -> Text:
        """Create footer with cancel instructions."""
        footer = Text()
        footer.append("  Close window or press ", style=STYLE_DIM)
        footer.append("[ESC]", style=STYLE_MUTED)
        footer.append(" to cancel submission", style=STYLE_DIM)
        return footer

    def _make_final_status(self) -> Panel:
        """Create final success/error status panel with optional inline prompt."""
        s = self.state

        if s.error:
            content = Text()
            content.append(f" {SYM_MISSING} ERROR ", style="bold white on red")
            content.append(f"  {s.error}", style=STYLE_ERROR)
            return Panel(content, border_style=STYLE_ERROR, box=box.ROUNDED, padding=(0, 1))
        else:
            parts = []
            # Success message
            success_text = Text()
            success_text.append(f" {SYM_OK} SUCCESS ", style="bold white on green")
            if s.inline_prompt:
                success_text.append(f"  {s.inline_prompt}", style=STYLE_SUCCESS)
            else:
                success_text.append("  Job submitted!", style=STYLE_SUCCESS)
            parts.append(success_text)

            # Inline prompt options (if any)
            if s.inline_prompt_options:
                parts.append(Text(""))
                prompt_text = Text()
                prompt_text.append("  ", style=STYLE_DIM)
                # Parse and style the options
                for part in s.inline_prompt_options.split("  "):
                    part = part.strip()
                    if not part:
                        continue
                    # Find [x] pattern
                    if "[" in part and "]" in part:
                        idx = part.index("[")
                        label = part[:idx].strip()
                        hotkey = part[idx:]
                        prompt_text.append(label + " ", style="bold cyan")
                        prompt_text.append(hotkey, style="bold white")
                        prompt_text.append("   ", style=STYLE_DIM)
                    else:
                        prompt_text.append(part + "  ", style=STYLE_MUTED)
                parts.append(prompt_text)

            return Panel(
                Group(*parts) if len(parts) > 1 else parts[0],
                border_style=STYLE_SUCCESS,
                box=box.ROUNDED,
                padding=(0, 1),
            )

    def _render(self) -> Group:
        """Render the full TUI layout - always show all panels."""
        s = self.state
        parts = []

        # Question phase - show only question panel
        if s.current_phase == "question":
            parts.append(self._make_header())
            parts.append(Text(""))
            parts.append(self._make_question_panel())
            parts.append(Text(""))
            parts.append(self._make_footer())
            return Group(*parts)

        # Header + progress summary
        parts.append(self._make_header())
        parts.append(self._make_progress_summary())

        # Always show all three panels
        parts.append(self._make_trace_panel())
        parts.append(self._make_pack_panel())
        parts.append(self._make_upload_panel())

        # Final status when done
        if s.current_phase == "done":
            parts.append(self._make_final_status())
        else:
            # Footer with cancel instructions (only when not done)
            parts.append(self._make_footer())

        # Warnings (if any)
        if s.warnings:
            for w in s.warnings[-2:]:  # Show max 2 warnings
                parts.append(Text(f"  {SYM_WARN} {w}", style=STYLE_WARNING))

        return Group(*parts)

    def start(self) -> None:
        """Start the live display."""
        # Note: TTY check is done in SubmitTUI.__init__ - if we get here, we should render
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=10,
            transient=False,
        )
        self._live.start()

    def update(self) -> None:
        """Update the live display."""
        if self._live:
            with self._lock:
                self._live.update(self._render())

    def stop(self) -> None:
        """Stop the live display."""
        if self._live:
            self._live.stop()
            self._live = None

    def finish(self, success: bool, message: str = "") -> None:
        """Finish and show final state."""
        self.state.current_phase = "done"
        if not success:
            self.state.error = message or "Submission failed"
        self.update()
        self.stop()

        # Print final summary
        if success:
            self.console.print(
                f"\n[{STYLE_SUCCESS}]Job submitted successfully![/]"
            )
        else:
            self.console.print(
                f"\n[{STYLE_ERROR}]Submission failed: {message}[/]"
            )


# ---------------------------------------------------------------------------
# BAT Progress Callback for TUI
# ---------------------------------------------------------------------------
class TUIProgressCallback:
    """
    BAT-compatible progress callback that feeds the TUI.

    Implements the interface expected by blender_asset_tracer.pack.progress.Callback
    """

    def __init__(self, state: SubmitTUIState, update_fn: Callable[[], None]):
        self.state = state
        self.update_fn = update_fn
        self._update_counter = 0
        self._update_interval = 5  # Update TUI every N events

    def _maybe_update(self) -> None:
        """Throttled TUI update."""
        self._update_counter += 1
        if self._update_counter >= self._update_interval:
            self._update_counter = 0
            self.update_fn()

    # --- Trace callbacks ---

    def trace_blendfile(self, filename: Path) -> None:
        """Called for every blendfile opened when tracing dependencies."""
        name = _shorten(str(filename), 50)
        self.state.trace.current_blendfile = name
        self.state.trace.blendfiles_opened.append(name)
        self._maybe_update()

    def trace_asset(self, filename: Path) -> None:
        """Called for every asset found when tracing dependencies."""
        name = _shorten(str(filename), 50)
        self.state.trace.files_found.append(name)
        self.state.trace.total_files += 1
        self._maybe_update()

    # --- Pack callbacks ---

    def pack_start(self) -> None:
        """Called when packing starts."""
        self.state.current_phase = "pack"
        self.state.pack.start_time = time.time()
        self.update_fn()

    def pack_done(
        self, output_blendfile: Path, missing_files: Set[Path]
    ) -> None:
        """Called when packing is done."""
        self.state.pack.done = True
        self.state.pack.missing_files = [str(p) for p in missing_files]
        self.update_fn()

    def pack_aborted(self, reason: str) -> None:
        """Called when packing was aborted."""
        self.state.error = f"Packing aborted: {reason}"
        self.update_fn()

    def rewrite_blendfile(self, orig_filename: Path) -> None:
        """Called for every rewritten blendfile."""
        name = _shorten(str(orig_filename), 50)
        self.state.pack.rewritten_blends.append(name)
        self._maybe_update()

    def transfer_file(self, src: Path, dst: Path) -> None:
        """Called when a file transfer starts."""
        name = _shorten(str(src), 50)
        self.state.pack.current_file = name
        self.state.pack.files_processed += 1
        self._maybe_update()

    def transfer_file_skipped(self, src: Path, dst: Path) -> None:
        """Called when a file is skipped because it already exists."""
        self.state.pack.files_processed += 1
        self._maybe_update()

    def transfer_progress(self, total_bytes: int, transferred_bytes: int) -> None:
        """Called during file transfer, with per-pack info."""
        self.state.pack.bytes_total = total_bytes
        self.state.pack.bytes_processed = transferred_bytes
        self._maybe_update()

    def missing_file(self, filename: Path) -> None:
        """Called for every asset that does not exist on the filesystem."""
        self.state.pack.missing_files.append(str(filename))
        self._maybe_update()


# ---------------------------------------------------------------------------
# Custom trace wrapper with datablock tracking
# ---------------------------------------------------------------------------
def trace_with_tui(
    blend_path: Path,
    state: SubmitTUIState,
    update_fn: Callable[[], None],
    trace_deps_fn: Callable,
) -> Tuple[List[Path], Set[Path], Dict[Path, str]]:
    """
    Wrapper around trace_dependencies that feeds the TUI with datablock info.

    Returns the same tuple as trace_dependencies:
        (dependency_paths, missing_files, unreadable_files)
    """
    from ..blender_asset_tracer import trace
    from ..blender_asset_tracer.pack import progress as pack_progress

    state.current_phase = "trace"
    state.trace.start_time = time.time()
    update_fn()

    # Create our progress callback
    class TraceCallback(pack_progress.Callback):
        def trace_blendfile(self, filename: Path) -> None:
            name = _shorten(str(filename), 50)
            state.trace.current_blendfile = name
            state.trace.blendfiles_opened.append(name)
            update_fn()

        def trace_asset(self, filename: Path) -> None:
            name = _shorten(str(filename), 50)
            state.trace.files_found.append(name)
            state.trace.total_files += 1
            # Throttle updates
            if state.trace.total_files % 5 == 0:
                update_fn()

    callback = TraceCallback()

    # Trace with our callback
    deps: List[Path] = []
    missing: Set[Path] = set()
    unreadable: Dict[Path, str] = {}
    seen_hashes: Set[int] = set()

    for usage in trace.deps(blend_path, callback):
        abs_path = usage.abspath

        # Track datablock
        try:
            block_name = usage.block_name.decode("utf-8", errors="replace")
            block_type = usage.block.dna_type_name if hasattr(usage.block, "dna_type_name") else "?"
            db_display = f"{block_type}: {block_name}"
        except Exception:
            db_display = str(usage.block_name)[:30]

        state.trace.datablocks_seen.append(_shorten(db_display, 35))
        state.trace.total_datablocks += 1

        # Dedupe
        usage_hash = hash(usage)
        if usage_hash in seen_hashes:
            continue
        seen_hashes.add(usage_hash)

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

        # Update TUI
        if len(deps) % 10 == 0:
            update_fn()

    state.trace.done = True
    state.trace.current_blendfile = ""
    update_fn()

    return deps, missing, unreadable


# ---------------------------------------------------------------------------
# Main TUI controller
# ---------------------------------------------------------------------------
class SubmitTUI:
    """
    Main TUI controller for the submission process.

    Usage:
        tui = SubmitTUI(blend_name="scene.blend", project_name="MyProject")
        tui.start()

        # During trace phase:
        tui.set_phase("trace")
        tui.trace_datablock("Image", "texture.png")
        tui.trace_file("/path/to/texture.png")

        # During pack phase:
        tui.set_phase("pack")
        tui.pack_file("/path/to/file.png", 1024)

        # During upload phase:
        tui.set_phase("upload")
        tui.upload_progress(bytes_transferred, bytes_total)

        # Finish:
        tui.finish(success=True)
    """

    def __init__(
        self,
        blend_name: str = "",
        project_name: str = "",
        upload_type: str = "PROJECT",
        plain_mode: bool = False,
        force_tui: bool = False,
        include_addons: bool = False,
    ):
        self.state = SubmitTUIState(
            blend_name=blend_name,
            project_name=project_name,
            upload_type=upload_type,
        )
        # Initialize upload phases based on mode
        phases, order = _create_upload_phases_for_mode(upload_type, include_addons)
        self.state.upload.phases = phases
        self.state.upload.phase_order = order
        self.state.upload.include_addons = include_addons
        # Use TUI if: forced, or (rich available AND is TTY AND not plain mode)
        use_tui = force_tui or (RICH_AVAILABLE and _IS_TTY and not plain_mode)
        self._plain_mode = not use_tui
        self._force_tui = force_tui
        self._ui: Any = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the TUI display."""
        if self._plain_mode:
            self._ui = PlainTextUI(self.state)
        else:
            self._ui = RichSubmitTUI(self.state, force=self._force_tui)
            self._ui.start()

    def update(self) -> None:
        """Update the display."""
        if self._ui:
            with self._lock:
                self._ui.update()

    def stop(self) -> None:
        """Stop the TUI display."""
        if self._ui and hasattr(self._ui, "stop"):
            self._ui.stop()

    def finish(self, success: bool, message: str = "") -> None:
        """Finish the TUI and show final status."""
        if self._ui:
            self._ui.finish(success, message)

    # --- Phase control ---

    def set_phase(self, phase: str) -> None:
        """Set the current phase: 'trace', 'pack', 'upload', 'done'"""
        self.state.current_phase = phase
        if phase == "trace":
            self.state.trace.start_time = time.time()
        elif phase == "pack":
            self.state.pack.start_time = time.time()
        elif phase == "upload":
            self.state.upload.start_time = time.time()
        self.update()

    # --- Trace phase methods ---

    def trace_blendfile(self, path: str) -> None:
        """Called when a blendfile is opened for tracing."""
        name = _shorten(path, 50)
        self.state.trace.current_blendfile = name
        self.state.trace.blendfiles_opened.append(name)
        self.update()

    def trace_datablock(self, block_type: str, block_name: str) -> None:
        """Called when a datablock is processed."""
        display = f"{block_type}: {block_name}"
        self.state.trace.datablocks_seen.append(_shorten(display, 35))
        self.state.trace.total_datablocks += 1
        if self.state.trace.total_datablocks % 10 == 0:
            self.update()

    def trace_file(self, path: str, status: str = "ok") -> None:
        """Called when a file dependency is found.

        Args:
            path: File path
            status: "ok", "missing", or "unreadable"
        """
        entry = FileEntry(_shorten(path, 45), status)
        self.state.trace.files_found.append(entry)
        self.state.trace.total_files += 1

        # Track counts by status
        if status == "ok":
            self.state.trace.files_ok += 1
        elif status == "missing":
            self.state.trace.files_missing += 1
        elif status == "unreadable":
            self.state.trace.files_unreadable += 1

        if self.state.trace.total_files % 5 == 0:
            self.update()

    def trace_done(self) -> None:
        """Called when tracing is complete."""
        self.state.trace.done = True
        self.state.trace.current_blendfile = ""
        # Freeze elapsed time
        if self.state.trace.start_time > 0:
            self.state.trace.elapsed_time = time.time() - self.state.trace.start_time
        self.update()

    # --- Pack phase methods ---

    def pack_start(self, total_files: int, mode: str = "PROJECT") -> None:
        """Called when packing starts."""
        self.state.pack.files_total = total_files
        self.state.pack.mode = mode
        self.state.pack.start_time = time.time()
        self.update()

    def pack_file(self, path: str, size: int = 0, status: str = "ok") -> None:
        """Called when a file is being packed.

        Args:
            path: File path
            size: File size in bytes
            status: "ok", "missing", "unreadable", or "rewrite"
        """
        entry = FileEntry(_shorten(path, 45), status)
        self.state.pack.files_packed.append(entry)
        self.state.pack.current_file = _shorten(path, 50)
        self.state.pack.files_processed += 1
        self.state.pack.bytes_processed += size
        if self.state.pack.files_processed % 3 == 0:
            self.update()

    def pack_rewrite(self, path: str) -> None:
        """Called when a blendfile is rewritten."""
        self.state.pack.rewritten_blends.append(_shorten(path, 50))
        entry = FileEntry(_shorten(path, 45), "rewrite")
        self.state.pack.files_packed.append(entry)
        self.update()

    def pack_missing(self, path: str) -> None:
        """Called when a file is missing."""
        self.state.pack.missing_files.append(path)
        entry = FileEntry(_shorten(path, 45), "missing")
        self.state.pack.files_packed.append(entry)
        self.update()

    def pack_unreadable(self, path: str, error: str) -> None:
        """Called when a file is unreadable."""
        self.state.pack.unreadable_files[path] = error
        entry = FileEntry(_shorten(path, 45), "unreadable")
        self.state.pack.files_packed.append(entry)
        self.update()

    def pack_done(self) -> None:
        """Called when packing is complete."""
        self.state.pack.done = True
        self.state.pack.current_file = ""
        # Freeze elapsed time
        if self.state.pack.start_time > 0:
            self.state.pack.elapsed_time = time.time() - self.state.pack.start_time
        self.update()

    # --- Upload phase methods ---

    def upload_start(self, phase: str, total_bytes: int, total_files: int = 1) -> None:
        """Called when an upload phase starts (blend, deps, manifest, addons)."""
        # Mark previous phase as done if switching phases
        if self.state.upload.current_phase and self.state.upload.current_phase != phase:
            prev_phase = self.state.upload.phases.get(self.state.upload.current_phase)
            if prev_phase and not prev_phase.done:
                prev_phase.done = True
                prev_phase.active = False
                if prev_phase.start_time > 0:
                    prev_phase.elapsed_time = time.time() - prev_phase.start_time

        # Set up new phase
        self.state.upload.current_phase = phase
        if phase in self.state.upload.phases:
            p = self.state.upload.phases[phase]
            p.bytes_total = total_bytes
            p.bytes_transferred = 0
            p.files_total = total_files
            p.files_transferred = 0
            p.active = True
            p.done = False
            p.start_time = time.time()

        # Set overall start time on first phase
        if self.state.upload.start_time == 0:
            self.state.upload.start_time = time.time()
        self.update()

    def upload_progress(
        self,
        bytes_transferred: int,
        bytes_total: int = 0,
        speed: str = "",
        eta: str = "",
        current_file: str = "",
    ) -> None:
        """Called to update upload progress for current phase."""
        phase = self.state.upload.current_phase
        if phase and phase in self.state.upload.phases:
            p = self.state.upload.phases[phase]
            p.bytes_transferred = bytes_transferred
            if bytes_total > 0:
                p.bytes_total = bytes_total
            if current_file:
                p.current_file = _shorten(current_file, 50)
        self.update()

    def upload_file_done(self, path: str = "") -> None:
        """Called when a file upload completes within current phase."""
        phase = self.state.upload.current_phase
        if phase and phase in self.state.upload.phases:
            p = self.state.upload.phases[phase]
            p.files_transferred += 1
            p.current_file = ""
        if path:
            entry = FileEntry(_shorten(path, 45), "ok")
            self.state.upload.files_uploaded.append(entry)
        self.update()

    def upload_phase_done(self, phase: str = "") -> None:
        """Called when a specific upload phase completes."""
        phase = phase or self.state.upload.current_phase
        if phase and phase in self.state.upload.phases:
            p = self.state.upload.phases[phase]
            p.done = True
            p.active = False
            if p.start_time > 0:
                p.elapsed_time = time.time() - p.start_time
        self.update()

    def upload_done(self) -> None:
        """Called when all uploads are complete."""
        # Freeze all active phases
        for p in self.state.upload.phases.values():
            if p.active and not p.done:
                p.done = True
                p.active = False
                if p.start_time > 0:
                    p.elapsed_time = time.time() - p.start_time
        self.state.upload.done = True
        # Freeze overall elapsed time
        if self.state.upload.start_time > 0:
            self.state.upload.elapsed_time = time.time() - self.state.upload.start_time
        self.update()

    # --- Warning/error methods ---

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.state.warnings.append(message)
        self.update()

    def set_error(self, message: str) -> None:
        """Set an error message."""
        self.state.error = message
        self.update()

    # --- BAT callback integration ---

    def get_bat_callback(self) -> TUIProgressCallback:
        """Get a BAT-compatible progress callback."""
        return TUIProgressCallback(self.state, self.update)

    # --- Question/confirmation methods ---

    def show_question(
        self,
        title: str,
        text: str,
        options: List[str],
        hotkeys: Optional[List[str]] = None,
        selected: int = 0,
    ) -> None:
        """
        Show a question prompt with options.

        Args:
            title: Panel title (e.g., "Confirm Submission")
            text: Question text (e.g., "Do you want to proceed?")
            options: List of option labels (e.g., ["Yes", "No"])
            hotkeys: List of hotkeys (e.g., ["y", "n"]). Defaults to ["y", "n"] for 2 options.
            selected: Index of initially selected option (default 0)
        """
        # Clear screen first
        if self._ui and hasattr(self._ui, "console"):
            self._ui.console.clear()

        self.state.current_phase = "question"
        self.state.question_title = title
        self.state.question_text = text
        self.state.question_options = options
        # Default hotkeys
        if hotkeys is None:
            if len(options) == 2:
                hotkeys = ["y", "n"]
            else:
                hotkeys = [str(i + 1) for i in range(len(options))]
        self.state.question_hotkeys = hotkeys
        self.state.question_selected = selected
        self.update()

    def clear_question(self) -> None:
        """Clear the question prompt and return to main progress view."""
        self.state.current_phase = "init"
        self.state.question_title = ""
        self.state.question_text = ""
        self.state.question_options = []
        self.state.question_hotkeys = []
        self.state.question_selected = 0
        # Clear and redraw
        if self._ui and hasattr(self._ui, "console"):
            self._ui.console.clear()
        self.update()

    def clear_screen(self) -> None:
        """Clear the terminal screen."""
        if self._ui and hasattr(self._ui, "console"):
            self._ui.console.clear()

    def wait_for_key(self, valid_keys: List[str]) -> str:
        """
        Wait for a single keypress (no Enter required).
        Returns the key pressed, or 'ESC' if escape was pressed.
        """
        return _wait_for_key(valid_keys)

    def ask_yes_no(self, default_yes: bool = True) -> Optional[bool]:
        """
        Wait for y/n keypress. Returns True for yes, False for no, None for ESC.
        """
        key = _wait_for_key(["y", "n"])
        if key == "ESC":
            return None
        return key == "y"

    def show_inline_prompt(self, message: str, options: str) -> None:
        """
        Show a prompt inline with the success panel.

        Args:
            message: Success message (e.g., "Job submitted!")
            options: Options string (e.g., "Open [y]  Close [n]")
        """
        self.state.inline_prompt = message
        self.state.inline_prompt_options = options
        self.update()

    def clear_inline_prompt(self) -> None:
        """Clear the inline prompt."""
        self.state.inline_prompt = ""
        self.state.inline_prompt_options = ""
        self.update()

    # --- Addon phase control ---

    def set_include_addons(self, include: bool) -> None:
        """Enable or disable the addons upload phase."""
        if include and "addons" not in self.state.upload.phases:
            self.state.upload.phases["addons"] = UploadPhaseState(name="addons", label="Add-ons")
            if "addons" not in self.state.upload.phase_order:
                self.state.upload.phase_order.append("addons")
        elif not include and "addons" in self.state.upload.phases:
            del self.state.upload.phases["addons"]
            if "addons" in self.state.upload.phase_order:
                self.state.upload.phase_order.remove("addons")
        self.state.upload.include_addons = include
        self.update()

    # --- Pre-built dialogs ---

    def show_update_dialog(self, current_version: str, new_version: str) -> str:
        """
        Show an update available dialog and wait for response.
        This should be shown before the submission screen.

        Returns: 'y' for update, 'n' for skip, 'ESC' for cancel
        """
        self.clear_screen()
        self.show_question(
            title="Update Available",
            text=f"A new version of Superluminal is available!\n\n"
                 f"  Current:  v{current_version}\n"
                 f"  Latest:   v{new_version}",
            options=["Update", "Skip"],
            hotkeys=["y", "n"],
        )
        key = self.wait_for_key(["y", "n"])
        self.clear_screen()
        return key

    def show_browser_prompt(self, job_name: str = "", elapsed: float = 0) -> str:
        """
        Show browser prompt inline with the success panel.
        Keeps all submission panels visible.

        Returns: 'y' for open, 'n' for close, 'ESC' for cancel
        """
        message = f"Job submitted in {elapsed:.1f}s" if elapsed else "Job submitted!"
        self.state.current_phase = "done"
        self.show_inline_prompt(message, "Open in browser [y]  Close [n]")
        key = self.wait_for_key(["y", "n"])
        self.clear_inline_prompt()
        return key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _shorten(path: str, max_len: int = 50) -> str:
    """Shorten a path for display."""
    if len(path) <= max_len:
        return path
    # Try to keep filename visible
    parts = path.replace("\\", "/").split("/")
    if len(parts) > 2:
        filename = parts[-1]
        if len(filename) < max_len - 5:
            remaining = max_len - len(filename) - 5
            prefix = path[:remaining]
            return f"{prefix}.../{filename}"
    return path[: max_len - 3] + "..."


def _format_size(size_bytes: int) -> str:
    """Format bytes as human readable."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ---------------------------------------------------------------------------
# Convenience function to create TUI for submit worker
# ---------------------------------------------------------------------------
def create_submit_tui(
    blend_path: str,
    project_name: str,
    upload_type: str,
    plain_mode: bool = False,
    force_tui: bool = False,
) -> SubmitTUI:
    """Create a SubmitTUI instance for the submit worker."""
    blend_name = Path(blend_path).name
    return SubmitTUI(
        blend_name=blend_name,
        project_name=project_name,
        upload_type=upload_type,
        plain_mode=plain_mode,
        force_tui=force_tui,
    )
