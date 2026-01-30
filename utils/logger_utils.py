"""
logger_utils.py — TUI utilities and Rich setup for Sulu logger.

Contains:
- Rich library import handling (with fallbacks)
- Unicode glyph constants
- Logo marks (ASCII and Unicode variants)
- Sulu terminal theme definition
- Console factory function
- Data models (TraceEntry, BLOCK_TYPE_NAMES)

This module is intentionally separate from the SubmitLogger class to keep
presentation/setup code isolated from business logic.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

from .worker_utils import supports_unicode

# ─────────────────────────────────────────────────────────────────────────────
# Rich library imports (with fallbacks)
# ─────────────────────────────────────────────────────────────────────────────

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
        from pathlib import Path
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


# ─────────────────────────────────────────────────────────────────────────────
# Unicode glyphs with ASCII fallbacks
# ─────────────────────────────────────────────────────────────────────────────

_UNICODE = supports_unicode()

ELLIPSIS = "…" if _UNICODE else "..."

GLYPH_STAGE = "▸" if _UNICODE else ">"
GLYPH_OK = "✓" if _UNICODE else "OK"
GLYPH_FAIL = "✕" if _UNICODE else "X"
GLYPH_WARN = "!"
GLYPH_INFO = "ⓘ" if _UNICODE else "i"
GLYPH_ARROW = "→" if _UNICODE else "->"
GLYPH_BULLET = "•" if _UNICODE else "-"
GLYPH_SEAM = "┆" if _UNICODE else "|"
GLYPH_DASH = "┄" if _UNICODE else "-"

GLYPH_HEX = "⬡" if _UNICODE else "#"
GLYPH_LINK = "⟐" if _UNICODE else "*"

BAR_FULL = "█" if _UNICODE else "#"
BAR_EMPTY = "░" if _UNICODE else "-"


# ─────────────────────────────────────────────────────────────────────────────
# Superluminal logo marks
# ─────────────────────────────────────────────────────────────────────────────

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

LOGO_MARK_ASCII = "\n".join(
    [
        "  SUPERLUMINAL COMPUTING CORPORATION",
        "  S U L U   S U B M I T T E R",
    ]
)

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
    """Normalize logo by stripping empty leading/trailing lines."""
    lines = raw.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join([ln.rstrip() for ln in lines])


def _get_logo_width(raw: str) -> int:
    """Get the maximum line width of a logo."""
    lines = raw.splitlines()
    return max((len(ln) for ln in lines), default=0)


_LOGO_MARK_NORM = _normalize_logo_mark(LOGO_MARK)
_LOGO_WIDE_NORM = _normalize_logo_mark(LOGO_WIDE)
_LOGO_TINY_NORM = _normalize_logo_mark(LOGO_TINY)
_LOGO_ASCII_NORM = _normalize_logo_mark(LOGO_MARK_ASCII)

_LOGO_MARK_WIDTH = _get_logo_width(_LOGO_MARK_NORM)
_LOGO_WIDE_WIDTH = _get_logo_width(_LOGO_WIDE_NORM)
_LOGO_TINY_WIDTH = _get_logo_width(_LOGO_TINY_NORM)
_LOGO_ASCII_WIDTH = _get_logo_width(_LOGO_ASCII_NORM)


def get_logo_mark(terminal_width: int = 120) -> str:
    """
    Return the appropriate logo mark text, or empty string if terminal too narrow.

    Selection rules:
      - If Unicode is supported:
          wide (if it fits) -> normal mark (if it fits) -> tiny (if it fits) -> ASCII (if it fits)
      - If Unicode is not supported:
          ASCII (if it fits) -> empty
    """
    if terminal_width <= 0:
        terminal_width = 80

    if _UNICODE:
        if terminal_width >= _LOGO_WIDE_WIDTH and _LOGO_WIDE_NORM:
            return _LOGO_WIDE_NORM
        if terminal_width >= _LOGO_MARK_WIDTH and _LOGO_MARK_NORM:
            return _LOGO_MARK_NORM
        if terminal_width >= _LOGO_TINY_WIDTH and _LOGO_TINY_NORM:
            return _LOGO_TINY_NORM
        if terminal_width >= _LOGO_ASCII_WIDTH and _LOGO_ASCII_NORM:
            return _LOGO_ASCII_NORM
        return ""

    if terminal_width >= _LOGO_ASCII_WIDTH and _LOGO_ASCII_NORM:
        return _LOGO_ASCII_NORM
    return ""


def get_logo_tiny() -> str:
    """Return the tiny logo text, or empty string if Unicode not supported."""
    if _UNICODE:
        return _LOGO_TINY_NORM
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Sulu terminal theme
# ─────────────────────────────────────────────────────────────────────────────


def _build_sulu_theme():
    """Build the Sulu Rich theme if Theme class is available."""
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

PANEL_PADDING = (1, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Console setup
# ─────────────────────────────────────────────────────────────────────────────


def get_console() -> Any:
    """
    Get a rich Console instance or a fallback (None).

    Windows note:
      - legacy_windows=True collapses hex colors into the 16-color palette.
        Dark "on #1E2027" often becomes "on black", making panel fills look absent.
      - Prefer ANSI Truecolor on modern Windows terminals so panel backgrounds render.
    """
    if not (RICH_AVAILABLE and Console is not None):
        return None

    kwargs: Dict[str, Any] = dict(
        force_terminal=True,
        highlight=False,
        color_system="auto",
    )
    if SULU_TUI_THEME is not None:
        kwargs["theme"] = SULU_TUI_THEME

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


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────


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
