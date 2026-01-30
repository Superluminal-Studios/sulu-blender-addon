"""
download_logger.py — Rich-based logging for Sulu Download worker.

Design: scrolling transcript with panels, matching submit_logger style.
Calm, confident, concise.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, List, Optional, Tuple

from .worker_utils import format_size, supports_unicode
from .logger_utils import (
    RICH_AVAILABLE,
    Console,
    Table,
    Panel,
    Text,
    Live,
    Align,
    box,
    GLYPH_STAGE,
    GLYPH_OK,
    GLYPH_FAIL,
    GLYPH_WARN,
    GLYPH_INFO,
    GLYPH_BULLET,
    GLYPH_HEX,
    BAR_FULL,
    BAR_EMPTY,
    SULU_PANEL_BOX,
    PANEL_PADDING,
    get_console,
    get_logo_mark as _get_logo_mark,
    get_logo_tiny as _get_logo_tiny,
)

_UNICODE = supports_unicode()


class DownloadLogger:
    """Scrolling transcript logger for download worker."""

    def __init__(
        self,
        log_fn: Optional[Callable[[str], None]] = None,
        input_fn: Optional[Callable[[str, str], str]] = None,
    ):
        self.console = get_console() if RICH_AVAILABLE else None
        self._log_fn = log_fn or print
        self._input_fn = input_fn or (lambda prompt, default="": input(prompt))

        self._dest_dir: str = ""
        self._transfer_cur: int = 0
        self._transfer_total: int = 0

        # Live progress
        self._live: Optional[Any] = None
        self._last_progress_time: float = 0.0

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
        title: Any = None,
        border: str = "sulu.stroke",
        padding: Tuple[int, int] = PANEL_PADDING,
    ) -> Any:
        if Panel is None:
            return body
        return Panel(
            body,
            title=title,
            title_align="left",
            border_style=border,
            padding=padding,
            box=SULU_PANEL_BOX,
            style="sulu.panel",
        )

    # ─────────────────────── Logo ───────────────────────

    def logo_start(self, job_name: str = "", dest_dir: str = "") -> None:
        """Show startup logo with job info panel."""
        self._dest_dir = dest_dir
        width = self._get_width()

        if self.console and Text is not None:
            # Gradient logo
            logo_str = _get_logo_mark(width)
            if logo_str:
                lines = logo_str.split("\n")
                max_len = max(len(ln) for ln in lines) if lines else 0

                lines = [""] * 3 + lines + [""] * 2
                num_lines = len(lines)

                bg_gradient = [
                    "#000000", "#000000", "#010204", "#020408", "#03060c",
                    "#040810", "#050a14", "#060c18", "#070e1c", "#081020",
                    "#091224", "#0a1428", "#0b162c", "#0c1830", "#0d1a34",
                    "#0e1c38", "#0f1e3c", "#102040", "#112244", "#122448",
                ]

                for i, line in enumerate(lines):
                    pad = max(0, (width - max_len) // 2)
                    padded = (" " * pad + line).ljust(width)
                    idx = int((i / max(num_lines - 1, 1)) * (len(bg_gradient) - 1))
                    t = Text(padded, style=f"#A0A8B8 on {bg_gradient[idx]}")
                    t.no_wrap = True
                    t.overflow = "crop"
                    self.console.print(t)

            # Job info panel
            if job_name or dest_dir:
                self.console.print()

                title = Text()
                title.append(f"{GLYPH_HEX} ", style="sulu.accent")
                title.append("Download", style="sulu.dim")

                body = Text()
                if job_name:
                    body.append(job_name, style="sulu.fg")
                if dest_dir:
                    if job_name:
                        body.append("\n")
                    body.append(dest_dir, style="sulu.dim")

                panel = self._panel(body, title=title, padding=(0, 2))
                self.console.print(panel)
        else:
            logo_str = _get_logo_mark(width)
            if logo_str:
                self._log_fn(logo_str)
            self._log_fn("")
            if job_name:
                self._log_fn(f"Downloading: {job_name}")
            if dest_dir:
                self._log_fn(f"To: {dest_dir}")

    # ─────────────────────── Info panels ───────────────────────

    def auto_mode_info(self) -> None:
        """Show auto-download mode info panel."""
        if self.console and Text is not None and Panel is not None:
            self.console.print()

            title = Text()
            title.append(f"{GLYPH_INFO} ", style="sulu.accent")
            title.append("Auto-download", style="sulu.dim")

            body = Text()
            body.append("Downloading frames as they finish rendering.\n", style="sulu.fg")
            body.append("Close this window anytime. Rerun later to resume.", style="sulu.muted")

            panel = self._panel(body, title=title, border="sulu.accent", padding=(0, 2))
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("Auto-download: Downloading frames as they finish rendering.")
            self._log_fn("Close anytime. Rerun later to resume.")

    def connection_complete(self) -> None:
        """Show storage connection success in a panel."""
        if self.console and Text is not None and Panel is not None:
            body = Text()
            body.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            body.append("Connected to storage", style="sulu.fg")

            panel = self._panel(body, border="sulu.ok", padding=(0, 1))
            self.console.print(panel)
        else:
            self._log_fn(f"{GLYPH_OK} Connected to storage")

    def resume_info(self, cached_count: int) -> None:
        """Show resume info panel when frames were previously downloaded."""
        if cached_count <= 0:
            return

        if self.console and Text is not None and Panel is not None:
            self._stop_live()
            self.console.print()

            title = Text()
            title.append(f"{GLYPH_INFO} ", style="sulu.accent")
            title.append("Resuming", style="sulu.dim")

            body = Text()
            body.append(f"{cached_count} frames previously downloaded.", style="sulu.fg")

            panel = self._panel(body, title=title, border="sulu.accent", padding=(0, 2))
            self.console.print(panel)

            # Restart live after panel
            self._start_live()
        else:
            self._log_fn(f"  Resuming: {cached_count} frames previously downloaded.")

    # ─────────────────────── Progress ───────────────────────

    def _build_progress_line(self, cur: int, total: int, status: str = "") -> Any:
        if not self.console or Text is None:
            return ""

        bar_width = max(20, min(45, self._get_width() - 50))
        line = Text()
        line.no_wrap = True
        line.overflow = "crop"
        line.append("  ", style="sulu.dim")

        if total > 0:
            pct = max(0.0, min(1.0, cur / max(total, 1)))
            filled = int(bar_width * pct)
            empty = bar_width - filled

            line.append(BAR_FULL * filled, style="sulu.accent")
            line.append(BAR_EMPTY * empty, style="sulu.stroke_subtle")
            line.append(f"  {pct * 100:5.1f}%", style="sulu.accent")
            line.append(f"  {format_size(cur)}", style="sulu.fg")
            line.append(f" / {format_size(total)}", style="sulu.muted")
        else:
            line.append(BAR_EMPTY * bar_width, style="sulu.stroke_subtle")
            line.append(f"  {format_size(cur)}", style="sulu.fg")

        if status:
            line.append(f"  {status}", style="sulu.dim")

        return line

    def _start_live(self) -> None:
        if not self.console or Live is None or self._live is not None:
            return
        try:
            self._live = Live(
                self._build_progress_line(0, 0),
                console=self.console,
                refresh_per_second=10,
                transient=True,
                auto_refresh=False,
            )
            self._live.start()
        except Exception:
            self._live = None

    def _stop_live(self) -> None:
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    def transfer_start(self, title: str = "Downloading") -> None:
        """Start a transfer with header."""
        self._stop_live()
        self._transfer_cur = 0
        self._transfer_total = 0

        if self.console and Text is not None:
            self.console.print()
            header = Text()
            header.append(f"  {GLYPH_STAGE} ", style="sulu.accent")
            header.append(title, style="sulu.title")
            self.console.print(header)
        else:
            self._log_fn(f"\n> {title}")

    def transfer_progress(self, cur: int, total: int) -> None:
        self._transfer_cur = cur
        self._transfer_total = total

        now = time.time()
        if now - self._last_progress_time < 0.1:
            return
        self._last_progress_time = now

        if self.console and Text is not None:
            if self._live is None:
                self._start_live()
            if self._live:
                try:
                    self._live.update(self._build_progress_line(cur, total), refresh=True)
                except Exception:
                    pass
        else:
            if total > 0:
                pct = (cur / max(total, 1)) * 100
                sys.stderr.write(f"\r  {format_size(cur)} / {format_size(total)} ({pct:.1f}%) ")
            else:
                sys.stderr.write(f"\r  {format_size(cur)} ")
            sys.stderr.flush()

    def transfer_progress_ext(
        self, cur: int, total: int,
        checks: int = 0, transfers: int = 0,
        status: str = "", current_file: str = "",
    ) -> None:
        self._transfer_cur = cur
        self._transfer_total = total

        now = time.time()
        if now - self._last_progress_time < 0.1:
            return
        self._last_progress_time = now

        # Build status text
        status_text = ""
        if status == "checking":
            status_text = f"[{checks}] Checking existing files"

        if self.console and Text is not None:
            if self._live is None:
                self._start_live()
            if self._live:
                try:
                    self._live.update(self._build_progress_line(cur, total, status_text), refresh=True)
                except Exception:
                    pass
        else:
            suffix = f"  {status_text}" if status_text else ""
            if total > 0:
                pct = (cur / max(total, 1)) * 100
                sys.stderr.write(f"\r  {format_size(cur)} / {format_size(total)} ({pct:.1f}%){suffix} ")
            else:
                sys.stderr.write(f"\r  {format_size(cur)}{suffix} ")
            sys.stderr.flush()

    def transfer_complete(self, message: str = "Complete") -> None:
        self._stop_live()

        if self.console and Text is not None:
            line = Text()
            line.append(f"  {GLYPH_OK} ", style="sulu.ok_b")
            line.append(message, style="sulu.fg")
            if self._transfer_total > 0:
                line.append(f"  {format_size(self._transfer_total)}", style="sulu.dim")
            self.console.print(line)
        else:
            sys.stderr.write("\n")
            size = f"  {format_size(self._transfer_total)}" if self._transfer_total > 0 else ""
            self._log_fn(f"  {GLYPH_OK} {message}{size}")

    # ─────────────────────── Messages ───────────────────────

    def info(self, msg: str) -> None:
        if self.console:
            self.console.print(f"  [sulu.dim]{GLYPH_INFO}[/] [sulu.muted]{msg}[/]")
        else:
            self._log_fn(f"  {msg}")

    def success(self, msg: str) -> None:
        if self.console:
            self.console.print(f"  [sulu.ok_b]{GLYPH_OK}[/] [sulu.fg]{msg}[/]")
        else:
            self._log_fn(f"  {GLYPH_OK} {msg}")

    def warning(self, msg: str) -> None:
        if self.console:
            self.console.print(f"  [sulu.warn_b]{GLYPH_WARN}[/] [sulu.warn]{msg}[/]")
        else:
            self._log_fn(f"  ! {msg}")

    def error(self, msg: str) -> None:
        if self.console:
            self.console.print(f"  [sulu.err_b]{GLYPH_FAIL}[/] [sulu.err]{msg}[/]")
        else:
            self._log_fn(f"  X {msg}")

    def log(self, msg: str) -> None:
        if self.console:
            self.console.print(f"  [sulu.muted]{msg}[/]")
        else:
            self._log_fn(f"  {msg}")

    def __call__(self, msg: str) -> None:
        self.log(msg)

    # ─────────────────────── End screen ───────────────────────

    def logo_end(self, elapsed: Optional[float] = None, dest_dir: Optional[str] = None) -> str:
        """Show completion and prompt. Returns 'o' (open) or 'c' (close)."""
        self._stop_live()
        dest = dest_dir or self._dest_dir

        if self.console and Text is not None and Panel is not None and Table is not None and Align is not None:
            self.console.print()

            # Account for panel borders (2) + padding (4) + grid overhead (2) = 8 chars
            inner_w = max(20, self._get_width() - 8)
            logo_str = _get_logo_tiny()

            logo_renderable = None
            if logo_str:
                # Build a grid with each line as a separate row
                lines = logo_str.split("\n")
                max_len = max(len(line) for line in lines) if lines else 0
                padding = max(0, (inner_w - max_len) // 2)
                logo_grid = Table.grid(padding=(0, 0))
                logo_grid.add_column()
                for line in lines:
                    line_txt = Text(" " * padding + line, style="#FFFFFF")
                    line_txt.no_wrap = True
                    line_txt.overflow = "crop"
                    logo_grid.add_row(line_txt)
                logo_renderable = logo_grid

            # Panel title with time
            panel_title = Text()
            panel_title.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            panel_title.append("Done", style="sulu.ok_b")
            if elapsed is not None:
                panel_title.append(f"  {elapsed:.1f}s", style="sulu.muted")

            headline = Text("Download complete", style="sulu.ok_b")

            # Action row
            actions = Text()
            actions.append(" O ", style="bold #15171E on #1EA138")
            actions.append(" Open folder", style="sulu.fg")
            actions.append("    ")
            actions.append(" ENTER ", style="bold #D8DEEC on #24272E")
            actions.append(" Close", style="sulu.muted")

            body = Table.grid(padding=(0, 0))
            body.expand = True
            body.add_column(justify="center")

            if logo_renderable is not None:
                body.add_row(logo_renderable)

            body.add_row(Text(""))
            body.add_row(Align.center(headline))
            if dest:
                dest_text = Text(dest, style="sulu.dim")
                body.add_row(Align.center(dest_text))
            body.add_row(Text(""))
            body.add_row(Align.center(actions))

            panel = self._panel(body, title=panel_title, border="sulu.ok", padding=(1, 2))
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

            s = (raw or "").strip().lower()
            return "o" if s in ("o", "open", "y", "yes") else "c"

        # Plain text
        self._log_fn("")
        if elapsed:
            self._log_fn(f"Done  {elapsed:.1f}s")
        else:
            self._log_fn("Done")
        self._log_fn("Download complete")
        if dest:
            self._log_fn(f"  {dest}")
        self._log_fn("")
        self._log_fn("  [O] Open folder")
        self._log_fn("  [Enter] Close")

        if not self._can_prompt():
            return "c"

        try:
            raw = self._input_fn("> ", "")
        except (EOFError, KeyboardInterrupt):
            return "c"

        s = (raw or "").strip().lower()
        return "o" if s in ("o", "open", "y", "yes") else "c"

    # ─────────────────────── Errors ───────────────────────

    def warn_block(self, message: str, severity: str = "warning") -> None:
        self._stop_live()
        if self.console and Panel is not None and Text is not None:
            border = "sulu.warn" if severity == "warning" else "sulu.err"
            glyph = GLYPH_WARN if severity == "warning" else GLYPH_FAIL
            panel = Panel(
                Text(message, style="sulu.fg"),
                title=Text(f"{glyph}  {severity.title()}", style="sulu.muted"),
                title_align="left",
                border_style=border,
                padding=(1, 2),
                box=SULU_PANEL_BOX,
                style="sulu.well",
            )
            self.console.print()
            self.console.print(panel)
        else:
            self._log_fn(f"\n{severity.title()}: {message}")

    def fatal(self, message: str) -> None:
        self._stop_live()
        self.warn_block(message, severity="error")
        try:
            self._input_fn("\nPress Enter to close.", "")
        except Exception:
            pass
        sys.exit(1)


def create_logger(
    log_fn: Optional[Callable[[str], None]] = None,
    input_fn: Optional[Callable[[str, str], str]] = None,
) -> DownloadLogger:
    return DownloadLogger(log_fn, input_fn=input_fn)
