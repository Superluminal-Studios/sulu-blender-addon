"""
download_logger.py — Rich-based logging for Sulu Download worker.

Design: scrolling transcript with panels, matching submit_logger style.
Calm, confident, concise.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

from .worker_utils import format_size
from .logger_utils import (
    Table,
    Panel,
    Text,
    Align,
    GLYPH_STAGE,
    GLYPH_OK,
    GLYPH_INFO,
    GLYPH_HEX,
    get_logo_mark as _get_logo_mark,
    get_logo_tiny as _get_logo_tiny,
    TranscriptLogger,
)

class DownloadLogger(TranscriptLogger):
    """Scrolling transcript logger for download worker."""

    MESSAGE_INDENT = "  "
    LOG_STYLE = "sulu.muted"
    PLAIN_MESSAGE_PREFIXES = {
        "info": "",
        "success": f"{GLYPH_OK} ",
        "warning": "! ",
        "error": "X ",
        "log": "",
    }
    PLAIN_WARN_BLOCK_PREFIX = "\n"
    LOGO_BG_GRADIENT = TranscriptLogger.LOGO_BG_GRADIENT[:20]
    LOGO_EXTRA_TOP_LINES = 3
    LOGO_EXTRA_BOTTOM_LINES = 2
    PROGRESS_SEAMS = False
    PROGRESS_STATUS_STYLE = "sulu.dim"
    THROTTLE_PLAIN_PROGRESS = True
    LIVE_INITIAL_CURRENT = False
    LIVE_VERTICAL_CROP = False
    LIVE_START_REFRESH = False
    INLINE_PROGRESS_FALLBACK = False

    def __init__(
        self,
        log_fn: Optional[Callable[[str], None]] = None,
        input_fn: Optional[Callable[[str, str], str]] = None,
    ):
        super().__init__(log_fn=log_fn, input_fn=input_fn)
        self._dest_dir: str = ""

    def _compute_progress_bar_width(self) -> int:
        return max(20, min(45, self._get_width() - 50))

    def _progress_width(self, *, extended: bool) -> int:
        return self._compute_progress_bar_width()

    def _append_known_progress(
        self, line, pct: float, cur: int, total: int
    ) -> None:
        line.append(f"  {pct * 100:5.1f}%", style="sulu.accent")
        line.append(f"  {format_size(cur)}", style="sulu.fg")
        line.append(f" / {format_size(total)}", style="sulu.muted")

    def _append_unknown_progress(self, line, cur: int) -> None:
        line.append(f"  {format_size(cur)}", style="sulu.fg")

    def _progress_status_text(
        self,
        checks: int,
        transfers: int,
        status: str,
        current_file: str,
    ) -> str:
        return f"Checking {checks} files" if status == "checking" else ""

    def _plain_transfer_progress(self, cur: int, total: int) -> str:
        if total > 0:
            pct = (cur / max(total, 1)) * 100
            return f"\r  {format_size(cur)} / {format_size(total)} ({pct:.1f}%) "
        return f"\r  {format_size(cur)} "

    def _plain_transfer_progress_ext(
        self,
        cur: int,
        total: int,
        checks: int,
        transfers: int,
        status: str,
        current_file: str,
    ) -> str:
        status_text = f"Checking {checks} files" if status == "checking" else ""
        suffix = f"  {status_text}" if status_text else ""
        if total > 0:
            pct = (cur / max(total, 1)) * 100
            return (
                f"\r  {format_size(cur)} / {format_size(total)} "
                f"({pct:.1f}%){suffix} "
            )
        return f"\r  {format_size(cur)}{suffix} "

    def _start_live(self) -> None:
        self._start_live_progress()

    def _stop_live(self) -> None:
        self._stop_live_progress()

    # Logo

    def logo_start(
        self,
        job_name: str = "",
        dest_dir: str = "",
        *,
        show_logo: bool = True,
    ) -> None:
        """Show startup logo with job info panel."""
        self._dest_dir = dest_dir
        width = self._get_width()

        if self.console and Text is not None:
            if show_logo:
                self._print_logo(gradient_bg=True)

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
            if show_logo:
                logo_str = _get_logo_mark(width)
                if logo_str:
                    self._log_fn(logo_str)
                self._log_fn("")
            if job_name:
                self._log_fn(f"Downloading: {job_name}")
            if dest_dir:
                self._log_fn(f"To: {dest_dir}")

    # Info panels

    def auto_mode_info(self) -> None:
        """Show auto-download mode info panel."""
        if self.console and Text is not None and Panel is not None:
            self.console.print()

            title = Text()
            title.append(f"{GLYPH_INFO} ", style="sulu.accent")
            title.append("Auto-download", style="sulu.dim")

            body = Text()
            body.append("Downloading frames as they render.\n", style="sulu.fg")
            body.append("Close anytime. Run again to resume.", style="sulu.muted")

            panel = self._panel(
                body,
                title=title,
                border_style="sulu.accent",
                padding=(0, 2),
            )
            self.console.print(panel)
        else:
            self._log_fn("")
            self._log_fn("Auto-download: Downloading frames as they render.")
            self._log_fn("Close anytime. Run again to resume.")

    def download_actions(self, *, have_job: bool, have_report: bool) -> None:
        """Show persistent single-key actions available during the download."""
        if self.console and Text is not None and Panel is not None:
            self.console.print()

            title = Text()
            title.append(f"{GLYPH_INFO} ", style="sulu.accent")
            title.append("While downloading", style="sulu.dim")

            actions = Text()
            action_count = 0

            def add_action(key: str, label: str, style: str) -> None:
                nonlocal action_count
                if action_count:
                    actions.append("   ", style="sulu.dim")
                actions.append(f" {key} ", style=style)
                actions.append(f" {label}", style="sulu.fg")
                action_count += 1

            if have_job:
                add_action("J", "Job page", "bold #15171E on #1EA138")
            if have_report:
                add_action("R", "Diagnostics", "bold #D8DEEC on #5250FF")
            add_action("O", "Folder", "bold #D8DEEC on #24272E")
            add_action("C", "Cancel", "bold #F4D8D8 on #6E2930")

            panel = self._panel(
                Align.center(actions) if Align is not None else actions,
                title=title,
                border_style="sulu.accent",
                padding=(0, 2),
            )
            self.console.print(panel)
        else:
            actions = []
            if have_job:
                actions.append("[J] Job page")
            if have_report:
                actions.append("[R] Diagnostics")
            actions.extend(("[O] Folder", "[C] Cancel"))
            self._log_fn("")
            self._log_fn("While downloading: " + "  ".join(actions))

    def action_feedback(self, message: str) -> None:
        """Acknowledge a shortcut without disturbing the transfer transcript."""
        self.info(message)

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
            body.append(f"{cached_count} frames already downloaded", style="sulu.fg")

            panel = self._panel(
                body,
                title=title,
                border_style="sulu.accent",
                padding=(0, 2),
            )
            self.console.print(panel)

            # Restart live after panel
            self._start_live()
        else:
            self._log_fn(f"  Resuming: {cached_count} frames already downloaded")

    # Progress

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

    def __call__(self, msg: str) -> None:
        self.log(msg)

    # End screen

    def cancelled(self, dest_dir: Optional[str] = None) -> str:
        """Show a calm cancellation screen. Returns 'o' (open) or 'c'."""
        self._stop_live()
        dest = dest_dir or self._dest_dir

        if (
            self.console
            and Text is not None
            and Panel is not None
            and Table is not None
            and Align is not None
        ):
            self.console.print()
            headline = Text("Download stopped", style="sulu.warn_b")
            subtitle = Text(
                "Downloaded frames are safe. Run again anytime to resume.",
                style="sulu.muted",
            )
            actions = Text()
            actions.append(" O ", style="bold #15171E on #1EA138")
            actions.append(" Open folder", style="sulu.fg")
            actions.append("    ")
            actions.append(" ENTER ", style="bold #D8DEEC on #24272E")
            actions.append(" Close", style="sulu.muted")

            body = Table.grid(padding=(0, 0))
            body.expand = True
            body.add_column(justify="center")
            body.add_row(Align.center(headline))
            body.add_row(Align.center(subtitle))
            if dest:
                body.add_row(Align.center(Text(dest, style="sulu.dim")))
            body.add_row(Text(""))
            body.add_row(Align.center(actions))
            self.console.print(
                self._panel(
                    body,
                    border_style="sulu.warn",
                    padding=(1, 2),
                )
            )
            if not self._can_prompt():
                return "c"
            try:
                raw = self._input_fn("", "")
            except (EOFError, KeyboardInterrupt):
                return "c"
            return "o" if (raw or "").strip().lower() in {"o", "open"} else "c"

        self._log_fn("")
        self._log_fn("Download stopped")
        self._log_fn("Downloaded frames are safe. Run again anytime to resume.")
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
        return "o" if (raw or "").strip().lower() in {"o", "open"} else "c"

    def logo_end(
        self,
        elapsed: Optional[float] = None,
        dest_dir: Optional[str] = None,
        mp4_path: Optional[str] = None,
    ) -> str:
        """Show completion and prompt. Returns 'o' (open) or 'c' (close)."""
        self._stop_live()
        dest = dest_dir or self._dest_dir

        if self.console and Text is not None and Panel is not None and Table is not None and Align is not None:
            self.console.print()

            logo_renderable = self._centered_logo_grid(_get_logo_tiny())

            # Panel title with time
            panel_title = Text()
            panel_title.append(f"{GLYPH_OK} ", style="sulu.ok_b")
            panel_title.append("Done", style="sulu.ok_b")
            if elapsed is not None:
                panel_title.append(f"  {elapsed:.1f}s", style="sulu.muted")

            headline = Text(
                "Download and MP4 complete" if mp4_path else "Download complete",
                style="sulu.ok_b",
            )

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
            if mp4_path:
                body.add_row(
                    Align.center(Text(Path(mp4_path).name, style="sulu.accent"))
                )
            body.add_row(Text(""))
            body.add_row(Align.center(actions))

            panel = self._panel(
                body,
                title=panel_title,
                border_style="sulu.ok",
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

            s = (raw or "").strip().lower()
            return "o" if s in ("o", "open", "y", "yes") else "c"

        # Plain text
        self._log_fn("")
        if elapsed:
            self._log_fn(f"Done  {elapsed:.1f}s")
        else:
            self._log_fn("Done")
        self._log_fn(
            "Download and MP4 complete" if mp4_path else "Download complete"
        )
        if dest:
            self._log_fn(f"  {dest}")
        if mp4_path:
            self._log_fn(f"  {Path(mp4_path).name}")
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

def create_logger(
    log_fn: Optional[Callable[[str], None]] = None,
    input_fn: Optional[Callable[[str, str], str]] = None,
) -> DownloadLogger:
    return DownloadLogger(log_fn, input_fn=input_fn)
