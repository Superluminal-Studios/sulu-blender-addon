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
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .worker_utils import format_size, supports_unicode

# Rich library imports (with fallbacks)

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


# Unicode glyphs with ASCII fallbacks

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

GLYPH_HEX = "⬡" if _UNICODE else "#"
GLYPH_LINK = "⟐" if _UNICODE else "*"

BAR_FULL = "█" if _UNICODE else "#"
BAR_EMPTY = "░" if _UNICODE else "-"


# Superluminal logo marks

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


# Sulu terminal theme


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


# Console setup


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


# Shared transcript logger


class TranscriptLogger:
    """Shared terminal transcript behavior for submit and download workers."""

    MESSAGE_INDENT = ""
    LOG_STYLE: Optional[str] = None
    PLAIN_MESSAGE_PREFIXES = {
        "info": "[i] ",
        "success": f"{GLYPH_OK} ",
        "warning": "! ",
        "error": "X ",
        "log": "",
    }
    PLAIN_WARN_BLOCK_PREFIX = ""

    LOGO_BG_GRADIENT = (
        "#000000",
        "#000000",
        "#010204",
        "#020408",
        "#03060c",
        "#040810",
        "#050a14",
        "#060c18",
        "#070e1c",
        "#081020",
        "#091224",
        "#0a1428",
        "#0b162c",
        "#0c1830",
        "#0d1a34",
        "#0e1c38",
        "#0f1e3c",
        "#102040",
        "#112244",
        "#122448",
        "#13264c",
        "#142850",
        "#152a54",
        "#162c58",
        "#172e5c",
        "#183060",
    )
    LOGO_EXTRA_TOP_LINES = 4
    LOGO_EXTRA_BOTTOM_LINES = 3

    PROGRESS_SEAMS = True
    PROGRESS_EXT_WIDTH_RESERVE = 20
    PROGRESS_STATUS_STYLE = "sulu.muted"
    THROTTLE_PLAIN_PROGRESS = False
    LIVE_INITIAL_CURRENT = True
    LIVE_VERTICAL_CROP = True
    LIVE_START_REFRESH = True
    INLINE_PROGRESS_FALLBACK = True

    def __init__(
        self,
        log_fn: Optional[Callable[[str], None]] = None,
        input_fn: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self.console = get_console() if RICH_AVAILABLE else None
        self._log_fn = log_fn or print
        self._input_fn = input_fn or (lambda prompt, default="": input(prompt))
        self._transfer_cur = 0
        self._transfer_total = 0
        self._live = None
        self._last_progress_time = 0.0
        self._progress_bar_width = 0
        self._inline_progress_active = False

    def _print(self, msg: str = "") -> None:
        if self.console:
            self.console.print(msg)
        else:
            self._log_fn(msg)

    def _get_width(self) -> int:
        if self.console:
            try:
                return int(self.console.width or 80)
            except Exception:
                pass
        return 80

    def _can_prompt(self) -> bool:
        try:
            return bool(sys.stdin) and bool(
                getattr(sys.stdin, "isatty", lambda: False)()
            )
        except Exception:
            return False

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

    def _print_logo(self, style: str = "sulu.dim", gradient_bg: bool = False) -> None:
        width = self._get_width()
        logo_str = get_logo_mark(width)
        if not logo_str:
            return

        lines = logo_str.split("\n")
        max_len = max(len(line) for line in lines) if lines else 0
        if gradient_bg:
            lines = (
                [""] * self.LOGO_EXTRA_TOP_LINES
                + lines
                + [""] * self.LOGO_EXTRA_BOTTOM_LINES
            )

        num_lines = len(lines)
        if self.console and Text is not None:
            for i, line in enumerate(lines):
                padding = max(0, (width - max_len) // 2)
                padded_line = " " * padding + line
                if gradient_bg and num_lines > 1:
                    color_idx = int(
                        (i / max(num_lines - 1, 1))
                        * (len(self.LOGO_BG_GRADIENT) - 1)
                    )
                    bg_color = self.LOGO_BG_GRADIENT[color_idx]
                    padded_line = padded_line.ljust(width)
                    text = Text(padded_line, style=f"#A0A8B8 on {bg_color}")
                else:
                    text = Text(padded_line, style=style)
                text.no_wrap = True
                text.overflow = "crop"
                self.console.print(text)
        else:
            self._log_fn("")
            for line in lines:
                padding = max(0, (width - max_len) // 2)
                self._log_fn(" " * padding + line)
            self._log_fn("")

    def _centered_logo_grid(self, logo: Any) -> Any:
        if Table is None or Text is None:
            return None
        # Account for panel borders (2) + padding (4) + grid overhead (2) = 8 chars
        inner_width = max(20, self._get_width() - 8)
        logo_str = logo(inner_width) if callable(logo) else logo
        if not logo_str:
            return None
        lines = logo_str.split("\n")
        max_len = max(len(line) for line in lines) if lines else 0
        padding = max(0, (inner_width - max_len) // 2)
        logo_grid = Table.grid(padding=(0, 0))
        logo_grid.add_column()
        for line in lines:
            line_text = Text(" " * padding + line, style="#FFFFFF")
            line_text.no_wrap = True
            line_text.overflow = "crop"
            logo_grid.add_row(line_text)
        return logo_grid

    def _compute_progress_bar_width(self) -> int:
        width = max(60, self._get_width())
        reserved = 2 + 4 + 30
        return min(60, max(18, width - reserved))

    def _progress_width(self, *, extended: bool) -> int:
        bar_width = self._progress_bar_width or self._compute_progress_bar_width()
        if extended:
            bar_width = max(12, bar_width - self.PROGRESS_EXT_WIDTH_RESERVE)
        return bar_width

    def _append_progress_prefix(self, line: Any) -> None:
        line.append("  ", style="sulu.dim")
        if self.PROGRESS_SEAMS:
            line.append(f"{GLYPH_SEAM} ", style="sulu.stroke_subtle")

    def _append_progress_bar_separator(self, line: Any) -> None:
        if self.PROGRESS_SEAMS:
            line.append(f" {GLYPH_SEAM} ", style="sulu.stroke_subtle")

    def _append_known_progress(
        self, line: Any, pct: float, cur: int, total: int
    ) -> None:
        line.append(f"{pct * 100:5.1f}%", style="sulu.accent")
        line.append("  ", style="sulu.stroke_subtle")
        line.append(format_size(cur), style="sulu.fg")
        line.append(" / ", style="sulu.dim")
        line.append(format_size(total), style="sulu.muted")

    def _append_unknown_progress(self, line: Any, cur: int) -> None:
        line.append(format_size(cur), style="sulu.fg")
        line.append(" transferred", style="sulu.dim")

    def _progress_status_text(
        self,
        checks: int,
        transfers: int,
        status: str,
        current_file: str,
    ) -> str:
        if status == "checking":
            return f"Checking {checks} existing files"
        if transfers > 0 and checks > transfers:
            return f"({checks - transfers} unchanged)"
        return ""

    def _build_progress_line(self, cur: int, total: int) -> Any:
        return self._build_progress_line_ext(
            cur,
            total,
            checks=0,
            transfers=0,
            status="",
            current_file="",
            _reserve_status=False,
        )

    def _build_progress_line_ext(
        self,
        cur: int,
        total: int,
        checks: int,
        transfers: int,
        status: str,
        current_file: str,
        *,
        _reserve_status: bool = True,
    ) -> Any:
        if not self.console or Text is None:
            return ""

        bar_width = self._progress_width(extended=_reserve_status)
        line = Text()
        line.no_wrap = True
        line.overflow = "crop"
        self._append_progress_prefix(line)

        if total > 0:
            pct = max(0.0, min(1.0, cur / max(total, 1)))
            filled = int(bar_width * pct)
            empty = max(0, bar_width - filled)
            bar = Text()
            bar.no_wrap = True
            bar.overflow = "crop"
            if filled:
                bar.append(BAR_FULL * filled, style="sulu.accent")
            if empty:
                bar.append(BAR_EMPTY * empty, style="sulu.stroke_subtle")
            line.append_text(bar)
            self._append_progress_bar_separator(line)
            self._append_known_progress(line, pct, cur, total)
        else:
            bar = Text(BAR_EMPTY * bar_width, style="sulu.stroke_subtle")
            bar.no_wrap = True
            bar.overflow = "crop"
            line.append_text(bar)
            self._append_progress_bar_separator(line)
            self._append_unknown_progress(line, cur)

        status_text = self._progress_status_text(
            checks, transfers, status, current_file
        )
        if status_text:
            line.append("  ", style="sulu.dim")
            line.append(status_text, style=self.PROGRESS_STATUS_STYLE)
        return line

    def _start_live_progress(self) -> None:
        if not self.console or Live is None or self._live is not None:
            return

        if self.LIVE_INITIAL_CURRENT:
            renderable = self._build_progress_line(
                self._transfer_cur, self._transfer_total
            )
        else:
            renderable = self._build_progress_line(0, 0)

        kwargs: Dict[str, Any] = {
            "console": self.console,
            "refresh_per_second": 10,
            "transient": True,
            "auto_refresh": False,
        }
        if self.LIVE_VERTICAL_CROP:
            kwargs["screen"] = False
            kwargs["vertical_overflow"] = "crop"

        try:
            self._live = Live(renderable, **kwargs)
        except TypeError:
            kwargs.pop("vertical_overflow", None)
            try:
                self._live = Live(renderable, **kwargs)
            except TypeError:
                try:
                    self._live = Live(renderable, console=self.console)
                except Exception:
                    self._live = None
                    return
        except Exception:
            self._live = None
            return

        try:
            if self.LIVE_START_REFRESH:
                self._live.start(refresh=True)
            else:
                self._live.start()
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

    def _stop_live(self) -> None:
        """Subclass hook for screens that must stop an active live region."""

    def _live_update(self, renderable: Any) -> None:
        if self._live is None:
            return
        try:
            self._live.update(renderable, refresh=True)
        except TypeError:
            try:
                self._live.update(renderable)
            except Exception:
                pass
        except Exception:
            pass

    def _render_progress_bar(self, cur: int, total: int) -> None:
        self._render_progress_bar_ext(
            cur,
            total,
            checks=0,
            transfers=0,
            status="",
            current_file="",
            _reserve_status=False,
        )

    def _render_progress_bar_ext(
        self,
        cur: int,
        total: int,
        checks: int,
        transfers: int,
        status: str,
        current_file: str,
        *,
        _reserve_status: bool = True,
    ) -> None:
        if not self.console or Text is None:
            return
        now = time.time()
        if now - self._last_progress_time < 0.1:
            return
        self._last_progress_time = now

        self._start_live_progress()
        renderable = self._build_progress_line_ext(
            cur,
            total,
            checks,
            transfers,
            status,
            current_file,
            _reserve_status=_reserve_status,
        )
        if self._live is not None:
            self._live_update(renderable)
            return
        if not self.INLINE_PROGRESS_FALLBACK:
            return

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

    def _plain_progress_due(self) -> bool:
        if not self.THROTTLE_PLAIN_PROGRESS:
            return True
        now = time.time()
        if now - self._last_progress_time < 0.1:
            return False
        self._last_progress_time = now
        return True

    def _plain_transfer_progress(self, cur: int, total: int) -> Optional[str]:
        if total <= 0:
            return None
        pct = (cur / max(total, 1)) * 100
        return f"\r  {format_size(cur)} / {format_size(total)} ({pct:.1f}%) "

    def _plain_transfer_progress_ext(
        self,
        cur: int,
        total: int,
        checks: int,
        transfers: int,
        status: str,
        current_file: str,
    ) -> str:
        status_suffix = ""
        if status == "checking":
            status_suffix = f"  Checking {checks} existing files"
        elif transfers > 0 and checks > transfers:
            status_suffix = f"  ({checks - transfers} unchanged)"
        if total > 0:
            pct = (cur / max(total, 1)) * 100
            return (
                f"\r  {format_size(cur)} / {format_size(total)} "
                f"({pct:.1f}%){status_suffix} "
            )
        return f"\r  {format_size(cur)} transferred{status_suffix} "

    def transfer_progress(self, cur: int, total: int) -> None:
        self._transfer_cur = cur
        self._transfer_total = total
        if self.console and Text is not None:
            self._render_progress_bar(cur, total)
            return
        if not self._plain_progress_due():
            return
        output = self._plain_transfer_progress(cur, total)
        if output is not None:
            sys.stderr.write(output)
            sys.stderr.flush()

    def transfer_progress_ext(
        self,
        cur: int,
        total: int,
        checks: int = 0,
        transfers: int = 0,
        status: str = "",
        current_file: str = "",
    ) -> None:
        self._transfer_cur = cur
        self._transfer_total = total
        if self.console and Text is not None:
            self._render_progress_bar_ext(
                cur, total, checks, transfers, status, current_file
            )
            return
        if not self._plain_progress_due():
            return
        sys.stderr.write(
            self._plain_transfer_progress_ext(
                cur, total, checks, transfers, status, current_file
            )
        )
        sys.stderr.flush()

    def _message(self, kind: str, msg: str) -> None:
        rich_parts = {
            "info": ("sulu.dim", GLYPH_INFO, "sulu.muted"),
            "success": ("sulu.ok_b", GLYPH_OK, "sulu.fg"),
            "warning": ("sulu.warn_b", GLYPH_WARN, "sulu.warn"),
            "error": ("sulu.err_b", GLYPH_FAIL, "sulu.err"),
        }
        if self.console:
            glyph_style, glyph, message_style = rich_parts[kind]
            self.console.print(
                f"{self.MESSAGE_INDENT}[{glyph_style}]{glyph}[/] "
                f"[{message_style}]{msg}[/]"
            )
        else:
            self._log_fn(
                f"{self.MESSAGE_INDENT}{self.PLAIN_MESSAGE_PREFIXES[kind]}{msg}"
            )

    def info(self, msg: str) -> None:
        self._message("info", msg)

    def success(self, msg: str) -> None:
        self._message("success", msg)

    def warning(self, msg: str) -> None:
        self._message("warning", msg)

    def error(self, msg: str) -> None:
        self._message("error", msg)

    def log(self, msg: str) -> None:
        if self.console and self.LOG_STYLE:
            self.console.print(f"{self.MESSAGE_INDENT}[{self.LOG_STYLE}]{msg}[/]")
        elif self.console:
            self._print(msg)
        else:
            self._log_fn(
                f"{self.MESSAGE_INDENT}{self.PLAIN_MESSAGE_PREFIXES['log']}{msg}"
            )

    def warn_block(self, message: str, severity: str = "warning") -> None:
        self._stop_live()
        if not self.console or Panel is None or Text is None:
            tag = "Warning" if severity == "warning" else "Error"
            self._log_fn(f"{self.PLAIN_WARN_BLOCK_PREFIX}{tag}: {message}")
            return

        border = "sulu.warn" if severity == "warning" else "sulu.err"
        glyph = GLYPH_WARN if severity == "warning" else GLYPH_FAIL
        title = Text(f"{glyph}  {severity.title()}", style="sulu.muted")
        panel = self._panel(
            Text(str(message), style="sulu.fg"),
            title=title,
            border_style=border,
            style="sulu.well",
        )
        self.console.print()
        self.console.print(panel)

    def fatal(self, message: str) -> None:
        self._stop_live()
        self.warn_block(message, severity="error")
        try:
            self._input_fn("\nPress Enter to close.", "")
        except Exception:
            pass
        sys.exit(1)


# Data models


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
