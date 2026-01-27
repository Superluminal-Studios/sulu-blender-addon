#!/usr/bin/env python3
"""
Minimal cross-platform TUI scaffold using ONLY:
- rich (beauty layer)
- tqdm (fallback progress layer)
- Python stdlib

Design principles:
- UI -> stderr (safe for piping stdout)
- stdout -> machine-friendly output (json / text)
- Rich when interactive; tqdm/plain when not
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional, TypeVar

from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    track,
)
from rich.table import Table

from tqdm import tqdm

T = TypeVar("T")


# -----------------------------
# CLI + console setup
# -----------------------------


@dataclass(frozen=True)
class UiOptions:
    plain: bool
    no_color: bool
    no_emoji: bool
    refresh: float
    screen: bool


def parse_args(argv: Optional[list[str]] = None) -> UiOptions:
    p = argparse.ArgumentParser(description="Minimal rich+tqdm TUI scaffold")
    p.add_argument(
        "--plain", action="store_true", help="Disable Rich UI; use tqdm/plain text."
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Force-disable colors (NO_COLOR env is also respected by Rich).",
    )
    p.add_argument(
        "--no-emoji",
        action="store_true",
        help="Disable emoji/icons for minimal terminals.",
    )
    p.add_argument(
        "--refresh",
        type=float,
        default=10.0,
        help="Rich refreshes per second (live/progress).",
    )
    p.add_argument(
        "--screen",
        action="store_true",
        help="Use alternate screen buffer for full-screen dashboards.",
    )
    ns = p.parse_args(argv)
    return UiOptions(
        plain=ns.plain,
        no_color=ns.no_color,
        no_emoji=ns.no_emoji,
        refresh=ns.refresh,
        screen=ns.screen,
    )


def make_consoles(opts: UiOptions) -> tuple[Console, Console]:
    # no_color=None lets Rich respect env vars like NO_COLOR / FORCE_COLOR automatically.
    no_color = True if opts.no_color else None

    ui = Console(
        stderr=True,
        no_color=no_color,
        emoji=not opts.no_emoji,
        highlight=False,
        safe_box=True,
    )
    out = Console(
        file=sys.stdout,
        no_color=True,  # stdout should be boring & safe by default
        emoji=False,
        highlight=False,
        safe_box=True,
    )
    return ui, out


def use_rich_ui(ui: Console, opts: UiOptions) -> bool:
    # Rich has its own detection (TERM=dumb disables features), but these two cover most cases.
    return (not opts.plain) and ui.is_terminal and ui.is_interactive


# -----------------------------
# Reusable UI building blocks
# -----------------------------


def iter_progress(
    items: Iterable[T], *, desc: str, total: Optional[int], ui: Console, opts: UiOptions
) -> Iterable[T]:
    """Rich progress when interactive, otherwise tqdm (auto-disables on non-TTY via disable=None)."""
    if use_rich_ui(ui, opts):
        return track(
            items,
            description=desc,
            total=total,
            console=ui,
            refresh_per_second=opts.refresh,
        )
    return tqdm(items, desc=desc, total=total, disable=None, dynamic_ncols=True)


def make_header(title: str) -> Panel:
    return Panel(
        Align.center(f"[bold]{title}[/bold]"),
        safe_box=True,
        padding=(0, 1),
    )


def make_stats_table(step: int, errors: int) -> Table:
    table = Table(title="Stats", box=None, show_header=False)
    table.add_column("key", style="dim", justify="right")
    table.add_column("value", justify="left")
    table.add_row("step", str(step))
    table.add_row("errors", str(errors))
    return table


def make_layout(app_title: str) -> Layout:
    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )
    layout["header"].update(make_header(app_title))
    layout["footer"].update(Panel("[dim]Ctrl+C to quit[/dim]", safe_box=True))
    return layout


# -----------------------------
# Demo "app" logic (replace this)
# -----------------------------


def run(ui: Console, out: Console, opts: UiOptions) -> int:
    ui.print(Panel("Starting…", title="minimal-tui", safe_box=True))

    errors = 0

    # A) Progress example
    for _ in iter_progress(range(60), desc="Working", total=60, ui=ui, opts=opts):
        time.sleep(0.03)
        if random.random() < 0.02:
            errors += 1

    # B) Multi-task progress example (optional)
    if use_rich_ui(ui, opts):
        columns = [
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ]
        with Progress(
            *columns, console=ui, refresh_per_second=opts.refresh, transient=True
        ) as progress:
            t1 = progress.add_task("Phase 1", total=100)
            t2 = progress.add_task("Phase 2", total=80)

            while not progress.finished:
                progress.update(t1, advance=2)
                progress.update(t2, advance=1)
                time.sleep(0.02)

    # C) Live dashboard example
    if use_rich_ui(ui, opts):
        layout = make_layout("Live dashboard")
        with Live(
            layout, console=ui, refresh_per_second=opts.refresh, screen=opts.screen
        ):
            for step in range(30):
                layout["left"].update(
                    Panel(make_stats_table(step, errors), title="Left", safe_box=True)
                )
                layout["right"].update(
                    Panel(
                        f"[bold]Status[/bold]\nstep={step}\nerrors={errors}",
                        title="Right",
                        safe_box=True,
                    )
                )
                time.sleep(0.08)

    # stdout: clean, machine-friendly
    sys.stdout.write(json.dumps({"errors": errors}) + "\n")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    opts = parse_args(argv)
    ui, out = make_consoles(opts)
    try:
        return run(ui, out, opts)
    except KeyboardInterrupt:
        ui.print("\n[dim]Interrupted[/dim]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
