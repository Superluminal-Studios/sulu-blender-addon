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

# Progress bar glyphs (no emoji)
BAR_FULL = "█" if _UNICODE else "#"
BAR_EMPTY = "░" if _UNICODE else "-"

# ─────────────────────────── Superluminal logo marks ───────────────────────────

# NOTE: Logo lines must have NO trailing whitespace to prevent wrapping issues.
# The _normalize_logo_mark function also strips as a safety measure.
LOGO_MARK = "\n".join(
    [
        "                                        ▄▖▄▖▄▖▄▖█▌█▌█▌▀▘▀",
        "                                    ▄▖█▌█▌█▌█▌▀▘",
        "                                  █▌█▌█▌█▌",
        "                                █▌█▌█▌▀▘",
        "                              █▌█▌█▌█▌",
        "                            █▌█▌█▌█▌        █▌",
        "  █████████  █████  █████   █▌█▌█▌          █▌   █████       █████  █████",
        " ███░░░░░███░░███  ░░███    █▌█▌█▌          █▌  ░░███       ░░███  ░░███",
        "░███    ░░░  ░███   ░███    █▌█▌            █▌   ░███        ░███   ░███",
        "░░█████████  ░███   ░███    █▌█▌          █▌█▌   ░███        ░███   ░███",
        " ░░░░░░░░███ ░███   ░███    █▌▀▘          █▌█▌   ░███        ░███   ░███",
        " ███    ░███ ░███   ░███    █▌          ▄▖█▌█▌   ░███      █ ░███   ░███",
        "░░█████████  ░░████████     █▌          █▌█▌█▌   ███████████ ░░████████",
        " ░░░░░░░░░    ░░░░░░░░      █▌        █▌█▌█▌█▌  ░░░░░░░░░░░   ░░░░░░░░",
        "                                The Superluminal Computing Corporation",
        "                                  ▄▖█▌█▌█▌▀▘",
        "                                ▄▖█▌█▌█▌▀▘",
        "                            ▄▖█▌█▌█▌▀▘",
        "                ▄▖▄▖▄▖▄▖█▌█▌█▌▀▘▀▘",
    ]
)

# Tiny logo for narrow terminals that can't show LOGO_MARK.
LOGO_TINY = "\n".join(
    [
        "                  ▖▖▌▘▘▘",
        "╔═╗╦ ╦╔═╗╔═╗╦═╗ ▖▌▌▘ ▖ ╦  ╦ ╦╔╦╗╦╔╗╔╔═╗╦",
        "╚═╗║ ║╠═╝║╣ ╠╦╝ ▌▌▘ ▖▌ ║  ║ ║║║║║║║║╠═╣║",
        "╚═╝╚═╝╩  ╚═╝╩╚═ ▌▘  ▌▌ ╩═╝╚═╝╩ ╩╩╝╚╝╩ ╩╩═╝",
        "                ▘ ▖▌▌▘",
        "             ▖▖▖▖▖▘▘",
    ]
)

# A conservative ASCII fallback for legacy terminals that don't reliably render Unicode.
LOGO_MARK_ASCII = "\n".join(
    [
        "  SUPERLUMINAL COMPUTING CORPORATION",
        "  S U L U   S U B M I T T E R",
    ]
)

# Wide logo variant (prefer this when terminal is wide enough to show it).
LOGO_WIDE = "\n".join(
    [
        "                                                                              ▄▖▄▖▄▖▄▖█▌█▌█▌▀▘▀",
        "                                                                          ▄▖█▌█▌█▌█▌▀▘",
        "                                                                        █▌█▌█▌█▌",
        "                                                                      █▌█▌█▌▀▘",
        "                                                                    █▌█▌█▌█▌",
        "                                                                  █▌█▌█▌█▌        █▌",
        "  █████████  █████  ████████████████  ██████████ ███████████      █▌█▌█▌          █▌   █████      █████  ███████████   █████████████████   █████  █████████  █████",
        " ███░░░░░███░░███  ░░███░░███░░░░░███░░███░░░░░█░░███░░░░░███     █▌█▌█▌          █▌  ░░███      ░░███  ░░███░░██████ ██████░░███░░██████ ░░███  ███░░░░░███░░███",
        "░███    ░░░  ░███   ░███ ░███    ░███ ░███  █ ░  ░███    ░███     █▌█▌            █▌   ░███       ░███   ░███ ░███░█████░███ ░███ ░███░███ ░███ ░███    ░███ ░███",
        "░░█████████  ░███   ░███ ░██████████  ░██████    ░██████████      █▌█▌          █▌█▌   ░███       ░███   ░███ ░███░░███ ░███ ░███ ░███░░███░███ ░███████████ ░███",
        " ░░░░░░░░███ ░███   ░███ ░███░░░░░░   ░███░░█    ░███░░░░░███     █▌▀▘          █▌█▌   ░███       ░███   ░███ ░███ ░░░  ░███ ░███ ░███ ░░██████ ░███░░░░░███ ░███",
        " ███    ░███ ░███   ░███ ░███         ░███ ░   █ ░███    ░███     █▌          ▄▖█▌█▌   ░███      █░███   ░███ ░███      ░███ ░███ ░███  ░░█████ ░███    ░███ ░███      █",
        "░░█████████  ░░████████  █████        ██████████ █████   █████    █▌          █▌█▌█▌   ███████████░░████████  █████     ███████████████  ░░██████████   ████████████████",
        " ░░░░░░░░░    ░░░░░░░░  ░░░░░        ░░░░░░░░░░ ░░░░░   ░░░░░     █▌        █▌█▌█▌█▌  ░░░░░░░░░░░  ░░░░░░░░  ░░░░░     ░░░░░░░░░░░░░░░    ░░░░░░░░░░   ░░░░░░░░░░░░░░░░",
        "                                                                          ▄▖█▌█▌█▌",
        "                                                                        ▄▖█▌█▌█▌▀▘    The Superluminal Computing Corporation",
        "                                                                      ▄▖█▌█▌█▌▀▘",
        "                                                                  ▄▖█▌█▌█▌▀▘",
        "                                                      ▄▖▄▖▄▖▄▖█▌█▌█▌▀▘▀▘",
    ]
)


def _normalize_logo_mark(raw: str) -> str:
    """Normalize logo mark for terminal rendering (prevent unwanted wrapping)."""
    lines = raw.splitlines()

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    lines = [ln.rstrip() for ln in lines]
    return "\n".join(lines)


def _get_logo_width(raw: str) -> int:
    """Get the maximum line width of the logo."""
    lines = raw.splitlines()
    return max((len(ln) for ln in lines), default=0)


# Pre-normalize logos once (prevents accidental trailing whitespace issues).
_LOGO_MARK_NORM = _normalize_logo_mark(LOGO_MARK)
_LOGO_WIDE_NORM = _normalize_logo_mark(LOGO_WIDE)
_LOGO_TINY_NORM = _normalize_logo_mark(LOGO_TINY)
_LOGO_ASCII_NORM = _normalize_logo_mark(LOGO_MARK_ASCII)

_LOGO_MARK_WIDTH = _get_logo_width(_LOGO_MARK_NORM)
_LOGO_WIDE_WIDTH = _get_logo_width(_LOGO_WIDE_NORM)
_LOGO_TINY_WIDTH = _get_logo_width(_LOGO_TINY_NORM)
_LOGO_ASCII_WIDTH = _get_logo_width(_LOGO_ASCII_NORM)


def _get_logo_mark(terminal_width: int = 120) -> str:
    """
    Return the appropriate logo mark text, or empty string if terminal too narrow.

    Selection rules:
      - If Unicode is supported:
          wide (if it fits) → normal mark (if it fits) → tiny (if it fits) → ASCII (if it fits)
      - If Unicode is not supported:
          ASCII (if it fits) → empty
    """
    if terminal_width <= 0:
        terminal_width = 80

    # Unicode terminals: prefer the nicest mark that fully fits.
    if _UNICODE:
        if terminal_width >= _LOGO_WIDE_WIDTH and _LOGO_WIDE_NORM:
            return _LOGO_WIDE_NORM
        if terminal_width >= _LOGO_MARK_WIDTH and _LOGO_MARK_NORM:
            return _LOGO_MARK_NORM
        # Use tiny for terminals that can't show LOGO_MARK.
        if terminal_width >= _LOGO_TINY_WIDTH and _LOGO_TINY_NORM:
            return _LOGO_TINY_NORM
        if terminal_width >= _LOGO_ASCII_WIDTH and _LOGO_ASCII_NORM:
            return _LOGO_ASCII_NORM
        return ""

    # Non-Unicode terminals: ASCII only.
    if terminal_width >= _LOGO_ASCII_WIDTH and _LOGO_ASCII_NORM:
        return _LOGO_ASCII_NORM
    return ""


# ─────────────────────────── Sulu terminal theme ───────────────────────────


def _build_sulu_theme():
    if Theme is None:
        return None
    return Theme(
        {
            "sulu.fg": "#D8DEEC",
            "sulu.muted": "#A2A6AF",
            "sulu.dim": "#7E828B",
            "sulu.accent": "#5250FF",
            "sulu.ring": "#757EFF",
            "sulu.ok": "#1EA138",
            "sulu.warn": "#E17100",
            "sulu.err": "#FF2056",
            "sulu.stroke": "#454A56",
            "sulu.stroke_subtle": "#3A3E48",
            "sulu.stroke_strong": "#545A69",
            # panel fills (require truecolor to be distinct on Windows)
            "sulu.panel": "on #1E2027",
            "sulu.well": "on #21232B",
            "sulu.control": "on #24272E",
            "sulu.overlay": "on #2C2F36",
            "sulu.title": "bold #D8DEEC",
            "sulu.stage": "bold #5250FF",
            "sulu.ok_b": "bold #1EA138",
            "sulu.warn_b": "bold #E17100",
            "sulu.err_b": "bold #FF2056",
            "sulu.link": "underline #5250FF",
            "sulu.pill": "#A2A6AF on #24272E",
        }
    )


SULU_TUI_THEME = _build_sulu_theme()

SULU_PANEL_BOX = getattr(box, "SQUARE", None) if box is not None else None
SULU_TABLE_BOX = getattr(box, "SIMPLE_HEAD", None) if box is not None else None

PANEL_PADDING = (0, 2)

# ─────────────────────────── Console setup ───────────────────────────


def get_console() -> Any:
    """
    Get a rich Console instance or a fallback (None).

    Windows note:
      - Forcing legacy_windows=True collapses hex colors into the 16‑color palette.
        Dark “on #1E2027” often becomes “on black”, making panel fills look absent.
      - Prefer ANSI Truecolor on modern Windows terminals so panel backgrounds render.
    """
    if not (RICH_AVAILABLE and Console is not None):
        return None

    theme = SULU_TUI_THEME

    kwargs: Dict[str, Any] = dict(
        force_terminal=True,
        highlight=False,
        color_system="auto",
    )
    if theme is not None:
        kwargs["theme"] = theme

    # On Windows: default to modern ANSI truecolor so our "on #xxxxxx" backgrounds work.
    if sys.platform == "win32":
        legacy_env = os.environ.get("SULU_LEGACY_WINDOWS", "").strip().lower()
        use_legacy = legacy_env in ("1", "true", "yes", "on")

        if not use_legacy:
            kwargs["color_system"] = "truecolor"
        kwargs["legacy_windows"] = use_legacy

    def _try_console(k: Dict[str, Any]) -> Any:
        try:
            return Console(**k, emoji=False)
        except TypeError:
            try:
                return Console(**k)
            except TypeError:
                return None

    con = _try_console(kwargs)
    if con is not None:
        return con

    k2 = dict(kwargs)
    k2.pop("legacy_windows", None)
    con = _try_console(k2)
    if con is not None:
        return con

    k3 = dict(k2)
    k3.pop("color_system", None)
    con = _try_console(k3)
    if con is not None:
        return con

    return None


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
        self._pack_entries: List[Dict[str, Any]] = []

        # Zip state
        self._zip_total = 0

        # Upload/transfer state
        self._upload_total = 0
        self._upload_step = 0
        self._transfer_active = False
        self._transfer_title = ""
        self._transfer_detail = ""
        self._transfer_cur = 0
        self._transfer_total = 0

        # Live region for in-place progress (single line; no frame flicker)
        self._live = None
        self._last_progress_time = 0.0  # rate limiting
        self._progress_bar_width = 0
        self._inline_progress_active = False  # fallback path if Live can't start

    # ───────────────────── internal helpers ─────────────────────

    MIN_TABLE_WIDTH = 60

    def _compute_cols(self) -> Dict[str, int]:
        """Compute column widths based on console width."""
        width = self._get_width()
        width = max(self.MIN_TABLE_WIDTH, width)

        status_w = 3
        gaps = 3
        lead = 2
        usable = max(30, width - lead - gaps - status_w)
        col_w = max(10, usable // 3)
        return {"col": col_w, "status": status_w, "total": width}

    def _print(self, msg: str = "") -> None:
        if self.console:
            self.console.print(msg)
        else:
            self._log_fn(msg)

    def _rule(self, title: str = "") -> None:
        """Subtle divider."""
        if self.console and Rule is not None:
            if title:
                self.console.print(
                    Rule(f"[sulu.muted]{title}[/]", style="sulu.stroke_subtle")
                )
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
        ell = "…" if _UNICODE else "."
        return s[: mx - 1] + ell

    def _get_width(self) -> int:
        """Get the current console width."""
        if self.console:
            try:
                return int(self.console.width or 80)
            except Exception:
                pass
        return 80

    # ───────────────────── logo marks ─────────────────────

    def _print_logo(self, style: str = "sulu.dim") -> None:
        """Print logo directly, line by line, centered, to avoid wrapping issues."""
        width = self._get_width()
        logo_str = _get_logo_mark(width)
        if not logo_str:
            return

        lines = logo_str.split("\n")
        max_len = max(len(line) for line in lines) if lines else 0

        if self.console and Text is not None:
            self.console.print()
            for line in lines:
                padding = max(0, (width - max_len) // 2)
                padded_line = " " * padding + line
                self.console.print(
                    Text(padded_line, style=style, no_wrap=True, overflow="crop")
                )
            self.console.print()
        else:
            self._log_fn("")
            for line in lines:
                padding = max(0, (width - max_len) // 2)
                self._log_fn(" " * padding + line)
            self._log_fn("")

    def logo_start(self) -> None:
        """Logo mark + start panel at the beginning of a submission."""
        if self.console and Text is not None:
            self._print_logo(style="sulu.dim")
        else:
            width = self._get_width()
            logo_str = _get_logo_mark(width)
            self._log_fn("")
            if logo_str:
                self._log_fn(logo_str)
                self._log_fn("")
            self._log_fn("=== SULU SUBMITTER ===")
            self._log_fn("Render farm submission pipeline")

    def logo_end(
        self,
        job_id: Optional[str] = None,
        elapsed: Optional[float] = None,
        job_url: Optional[str] = None,
    ) -> None:
        """Logo mark + celebratory end panel (after job registration)."""
        sparkle = "·:*" if _UNICODE else "***"

        if self.console and Text is not None and Align is not None:
            self._print_logo(style="#FFFFFF")

            body = Text()
            body.append(f"{sparkle} ", style="bold #1EA138")
            body.append("SUBMISSION COMPLETE", style="bold #1EA138")
            body.append(f" {sparkle[::-1]}", style="bold #1EA138")
            body.append("\n\n")

            body.append(
                "Your render job is now queued and will begin rendering shortly.",
                style="sulu.fg",
            )

            if job_id:
                body.append("\n")
                body.append("Job ID: ", style="sulu.muted")
                body.append(str(job_id), style="sulu.fg")

            if job_url:
                body.append("\n\n")
                body.append(str(job_url), style="underline #5250FF")

            title = Text()
            title.append(f"{GLYPH_OK}  SUCCESS", style="sulu.ok_b")
            if elapsed is not None:
                title.append(f"  ·  {elapsed:.1f}s", style="sulu.dim")

            panel = self._panel(
                Align.center(body),
                title=title,
                border_style="sulu.ok",
                style="sulu.panel",
                padding=(1, 2),
            )
            self.console.print(panel)
        else:
            width = self._get_width()
            logo_str = _get_logo_mark(width)
            self._log_fn("")
            if logo_str:
                self._log_fn(logo_str)
                self._log_fn("")
            time_str = f" ({elapsed:.1f}s)" if elapsed is not None else ""
            self._log_fn(f"{sparkle} SUBMISSION COMPLETE{time_str} {sparkle[::-1]}")
            self._log_fn("")
            self._log_fn(
                "Your render job is now queued and will begin rendering shortly."
            )
            if job_id:
                self._log_fn(f"Job ID: {job_id}")
            if job_url:
                self._log_fn(f"{job_url}")

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
            cols = self._compute_cols()
            c = cols["col"]
            s = cols["status"]
            header = Text("  ", no_wrap=True, overflow="crop")
            header.append(f"{'Source':<{c}} ", style="sulu.muted")
            header.append(f"{'Block':<{c}} ", style="sulu.muted")
            header.append(f"{'Resolved':<{c}} ", style="sulu.muted")
            header.append(f"{'':>{s}}", style="sulu.muted")
            self.console.print(header)
            self.console.print(
                Text(
                    "  " + (GLYPH_DASH * (max(0, cols["total"] - 2))),
                    style="sulu.stroke_subtle",
                    no_wrap=True,
                    overflow="crop",
                )
            )
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
        entry = TraceEntry(
            source_blend, block_type, block_name, found_file, status, error_msg
        )
        self._trace_entries.append(entry)

        cols = self._compute_cols()
        type_name = BLOCK_TYPE_NAMES.get(block_type, block_type)
        c = cols["col"]
        s = cols["status"]

        src_t = self._trunc(source_blend, c)
        file_t = self._trunc(found_file, c)

        type_part = f"[{type_name}]"
        name_max = max(0, c - len(type_part) - 1)
        name_t = self._trunc(block_name, name_max)

        if self.console and Text is not None:
            line = Text("  ", no_wrap=True, overflow="crop")

            line.append(f"{src_t:<{c}} ", style="sulu.dim")

            tag = Text(type_part, style="sulu.pill")
            line.append_text(tag)
            line.append(" ", style="sulu.dim")
            line.append(f"{name_t:<{name_max}} ", style="sulu.fg")

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

            if error_msg and status == "unreadable":
                msg = self._trunc(error_msg, max(20, cols["total"] - 8))
                self.console.print(
                    Text(
                        f"  {GLYPH_SEAM} {GLYPH_ARROW} {msg}",
                        style="sulu.dim",
                        no_wrap=True,
                        overflow="crop",
                    )
                )
        else:
            status_str = (
                GLYPH_OK
                if status == "ok"
                else (GLYPH_WARN if status == "missing" else GLYPH_FAIL)
            )
            block_str = f"[{type_name}] {block_name}"
            self._log_fn(
                f"  {src_t:<{c}} {block_str:<{c}} {file_t:<{c}} {status_str:>{s}}"
            )
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
            self._log_fn(
                f"Trace: {total} dependencies (missing={missing}, unreadable={unreadable}, cross_drive={cross_drive})"
            )
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
            cols = self._compute_cols()
            w = cols["total"]
            file_w = max(20, w - 24)

            header = Text("  ", no_wrap=True, overflow="crop")
            header.append(f"{'File':<{file_w}} ", style="sulu.muted")
            header.append(f"{'Size':>10} ", style="sulu.muted")
            header.append(f"{'':>3}", style="sulu.muted")
            self.console.print(header)
            self.console.print(
                Text(
                    "  " + (GLYPH_DASH * (max(0, w - 2))),
                    style="sulu.stroke_subtle",
                    no_wrap=True,
                    overflow="crop",
                )
            )
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
        self._pack_entries.append(
            {"index": index, "filepath": filepath, "size": size, "status": status}
        )
        filename = Path(filepath).name
        size_str = format_size(size) if size else ""
        cols = self._compute_cols()
        w = cols["total"]
        file_w = max(20, w - 24)

        name_t = self._trunc(filename, file_w)

        if self.console and Text is not None:
            line = Text("  ", no_wrap=True, overflow="crop")
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
            status_str = (
                GLYPH_OK
                if status == "ok"
                else (GLYPH_WARN if status == "missing" else GLYPH_FAIL)
            )
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
            cols = self._compute_cols()
            w = cols["total"]
            file_w = max(20, w - 30)

            header = Text("  ", no_wrap=True, overflow="crop")
            header.append(f"{'File':<{file_w}} ", style="sulu.muted")
            header.append(f"{'Size':>10} ", style="sulu.muted")
            header.append(f"{'Mode':>16}", style="sulu.muted")
            self.console.print(header)
            self.console.print(
                Text(
                    "  " + (GLYPH_DASH * (max(0, w - 2))),
                    style="sulu.stroke_subtle",
                    no_wrap=True,
                    overflow="crop",
                )
            )
        else:
            self._log_fn("")
            self._log_fn("Archive:")
            self._log_fn("-" * 70)

    def zip_entry(
        self, index: int, total: int, arcname: str, size: int, method: str
    ) -> None:
        """Log a single file being zipped (structured callback)."""
        cols = self._compute_cols()
        w = cols["total"]
        file_w = max(20, w - 30)
        name_t = self._trunc(arcname, file_w)
        size_str = format_size(size) if size else ""

        if self.console and Text is not None:
            line = Text("  ", no_wrap=True, overflow="crop")
            line.append(f"{name_t:<{file_w}} ", style="sulu.fg")
            line.append(f"{size_str:>10} ", style="sulu.dim")
            line.append(f"{method:>16}", style="sulu.muted")
            self.console.print(line)
        else:
            self._log_fn(f"  {name_t:<42} {size_str:>10} {method:>16}")

    def zip_done(
        self, zippath: str, total_files: int, total_bytes: int, elapsed: float
    ) -> None:
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
            self._log_fn(
                f"Archive ready: {total_files} files, {format_size(total_bytes)}, {elapsed:.1f}s"
            )

    # ───────────────────── upload / transfer ─────────────────────

    def _compute_progress_bar_width(self) -> int:
        """Compute a stable progress bar width that won't hit the last terminal column."""
        width = max(self.MIN_TABLE_WIDTH, self._get_width())
        reserved = 2 + 4 + 30  # indent + seams + stats
        bar_w = max(18, width - reserved)
        return min(60, bar_w)

    def _start_live_progress(self) -> None:
        """
        Start a Rich Live region for progress (single line).

        Key anti-flicker choices:
        - Single-line renderable (no panel frame to repaint)
        - no_wrap + overflow="crop"
        - auto_refresh=False: repaint only when we call update()
        """
        if not self.console or Live is None:
            return
        if self._live is not None:
            return

        renderable = self._build_progress_line(self._transfer_cur, self._transfer_total)

        try:
            self._live = Live(
                renderable,
                console=self.console,
                refresh_per_second=10,
                screen=False,
                transient=True,
                auto_refresh=False,
                vertical_overflow="crop",
            )
        except TypeError:
            try:
                self._live = Live(
                    renderable,
                    console=self.console,
                    refresh_per_second=10,
                    screen=False,
                    transient=True,
                    auto_refresh=False,
                )
            except TypeError:
                self._live = Live(renderable, console=self.console)

        try:
            self._live.start(refresh=True)
        except TypeError:
            try:
                self._live.start()
            except Exception:
                self._live = None
                return
        except Exception:
            self._live = None
            return

        self._inline_progress_active = False

    def _stop_live_progress(self) -> None:
        """Stop the Rich Live region if active (or clear inline fallback line)."""
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

        if self._inline_progress_active and self.console:
            try:
                self.console.file.write("\r\033[2K")
                self.console.file.flush()
            except Exception:
                pass
            self._inline_progress_active = False

    def _live_update(self, renderable: Any) -> None:
        """Update live renderable (version-tolerant)."""
        if self._live is None:
            return
        try:
            self._live.update(renderable, refresh=True)
        except TypeError:
            try:
                self._live.update(renderable)
            except Exception:
                pass

    def upload_start(self, total: int) -> None:
        """Begin the upload phase."""
        self._upload_total = total
        self._upload_step = 0
        self._transfer_active = False
        self._last_progress_time = 0.0
        self._progress_bar_width = 0
        self._inline_progress_active = False
        self._stop_live_progress()

    def upload_step(
        self, step: int, total_steps: int, title: str, detail: str = ""
    ) -> None:
        """Start a transfer substage - shows title and prepares for progress bar."""
        self._stop_live_progress()

        self._upload_step = step
        self._transfer_title = title
        self._transfer_detail = detail
        self._transfer_active = True
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

    def _build_progress_line(self, cur: int, total: int) -> Any:
        """Build a single-line progress renderable."""
        if not self.console or Text is None:
            return ""

        bar_width = self._progress_bar_width or self._compute_progress_bar_width()

        line = Text(no_wrap=True, overflow="crop")
        line.append("  ", style="sulu.dim")
        line.append(f"{GLYPH_SEAM} ", style="sulu.stroke_subtle")

        if total > 0:
            pct = cur / max(total, 1)
            pct = 0.0 if pct < 0.0 else (1.0 if pct > 1.0 else pct)

            filled = int(bar_width * pct)
            empty = max(0, bar_width - filled)

            bar = Text(no_wrap=True, overflow="crop")
            if filled:
                bar.append(BAR_FULL * filled, style="sulu.accent")
            if empty:
                bar.append(BAR_EMPTY * empty, style="sulu.stroke_subtle")
            line.append_text(bar)

            line.append(f" {GLYPH_SEAM} ", style="sulu.stroke_subtle")

            line.append(f"{pct * 100:5.1f}%", style="sulu.accent")
            line.append("  ", style="sulu.stroke_subtle")
            line.append(f"{format_size(cur)}", style="sulu.fg")
            line.append(" / ", style="sulu.dim")
            line.append(f"{format_size(total)}", style="sulu.muted")
        else:
            bar = Text(
                BAR_EMPTY * bar_width, style="sulu.stroke_subtle", no_wrap=True, overflow="crop"
            )
            line.append_text(bar)
            line.append(f" {GLYPH_SEAM} ", style="sulu.stroke_subtle")
            line.append(f"{format_size(cur)}", style="sulu.fg")
            line.append(" transferred", style="sulu.dim")

        return line

    def transfer_progress(self, cur: int, total: int) -> None:
        """Update the transfer progress bar."""
        self._transfer_cur = cur
        self._transfer_total = total

        if self.console and Text is not None:
            self._render_progress_bar(cur, total)
        else:
            if total > 0:
                pct = (cur / max(total, 1)) * 100
                sys.stderr.write(
                    f"\r  {format_size(cur)} / {format_size(total)} ({pct:.1f}%) "
                )
                sys.stderr.flush()

    def _render_progress_bar(self, cur: int, total: int) -> None:
        """Render/update the progress line with rate limiting (no flicker, no new lines)."""
        if not self.console or Text is not None and self.console is None:
            return
        if Text is None:
            return

        now = time.time()
        if (now - self._last_progress_time) < 0.1:
            return
        self._last_progress_time = now

        self._start_live_progress()
        renderable = self._build_progress_line(cur, total)

        if self._live is not None:
            self._live_update(renderable)
            return

        # Fallback: inline CR update, never prints a newline.
        try:
            self.console.file.write("\r\033[2K")
            self.console.file.flush()
        except Exception:
            pass
        try:
            self.console.print(renderable, end="")
            try:
                self.console.file.flush()
            except Exception:
                pass
            self._inline_progress_active = True
        except Exception:
            pass

    def upload_complete(self, title: str) -> None:
        """Mark current transfer substage as complete."""
        self._transfer_active = False

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

    def upload_end(self, elapsed: float) -> None:
        """Final upload completion message."""
        if self.console and Text is not None:
            self._stop_live_progress()

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

    def report_info(self, report_path: str) -> None:
        """Display the report file location."""
        if self.console:
            self.console.print(
                f"[sulu.dim]{GLYPH_INFO}[/] [sulu.muted]Report: {report_path}[/]"
            )
        else:
            self._log_fn(f"Report: {report_path}")

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

    # ───────────────────── chat-style prompts ─────────────────────

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
        """Styled chat-style input prompt. Returns the user's answer."""
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

    def fatal(self, message: str) -> None:
        """Print error, prompt to close, then exit."""
        self.warn_block(message, severity="error")
        try:
            self._input_fn("\nPress ENTER to close this window...", "")
        except Exception:
            pass
        sys.exit(1)

    def info_exit(self, message: str) -> None:
        """Print info message, prompt to close, then exit cleanly."""
        if self.console and Panel is not None and Text is not None:
            panel = self._panel(
                Text(str(message), style="sulu.fg"),
                title=Text(f"{GLYPH_INFO}  INFO", style="sulu.muted"),
                border_style="sulu.accent",
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn(f"[i] {message}")
        try:
            self._input_fn("\nPress ENTER to close this window...", "")
        except Exception:
            pass
        sys.exit(0)

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
                self.console.print(
                    f"[sulu.ok_b]{GLYPH_OK}[/] [sulu.fg]Storage connected[/]"
                )
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
                self._log_fn(f"  {ext:12} : {cnt:4} files")
            self._log_fn(f"  Total size: {format_size(total_size)}")

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

        self.warn_block(
            "TEST MODE — no upload or job registration performed.", severity="warning"
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
    def pack_file(
        self,
        index: int,
        total: int,
        filepath: str,
        size: Optional[int] = None,
        status: str = "ok",
    ) -> None:
        self.pack_entry(index, filepath, size=size, status=status)

    def pack_summary(
        self,
        ok_count: int,
        missing_count: int = 0,
        unreadable_count: int = 0,
        cross_drive_count: int = 0,
        total_size: int = 0,
    ) -> None:
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
