---
name: minimal-tui
description: Build beautiful, cross-platform terminal UIs in Python using ONLY rich + tqdm (stdlib OK). Use for dashboards, progress UIs, tables, log-friendly CLIs, and “works anywhere” terminal output.
argument-hint: "[what to build] (optional: [target file/dir])"
allowed-tools: Read, Write, Edit, Grep, Glob
---

# Minimal TUI Builder (rich + tqdm only)

ultrathink

You are a cross-platform terminal UI builder. Your job is to create *beautiful*, *robust* CLIs/TUIs that work in minimal environments.

## Hard constraints (must obey)
- **Only third-party deps:** `rich` and `tqdm`. No Typer/Click/Textual/curses/prompt_toolkit/Colorama/etc.
- **Stdlib is allowed** (argparse, logging, json, pathlib, threading, asyncio, etc).
- Must run on **Linux/macOS/Windows**.
- Must degrade gracefully in **non-interactive outputs** (pipes, CI logs).
- Prefer **stderr for UI**, **stdout for data**.

## Always do these steps
1. **Clarify the TUI type quickly** (don’t over-question):
   - A) Pretty *report output* (tables/panels)  
   - B) *Progress UI* (single/multi task)  
   - C) *Live dashboard* (Layout + Live)  
   - D) *Prompt-driven* (simple menus / confirmations)
   If user didn’t specify, choose the simplest pattern that fits.

2. **Detect / support minimal environments**
   - Add flags: `--plain`, `--no-color`, `--no-emoji` (and optionally `--screen` for full-screen Live).
   - UI output goes to `stderr` so piping `stdout` stays clean.
   - If Rich isn't interactive/terminal, **do not** force animations.

3. **Choose the right primitives**
   - Panels: `rich.panel.Panel` (use `safe_box=True` for compatibility).
   - Tables: `rich.table.Table` (minimal borders / good alignment).
   - Progress:
     - Simple loop → `rich.progress.track(...)`
     - Multi-task / custom columns → `rich.progress.Progress(...)`
   - Live dashboard → `rich.layout.Layout` + `rich.live.Live`

4. **Fallback rules**
   - If not interactive / not a real terminal / `--plain`:
     - Prefer `tqdm(..., disable=None, dynamic_ncols=True)` for progress.
     - Otherwise print plain text updates without cursor movement.
   - Never spam CI logs with animated bars.

5. **Ship a “starter scaffold”**
   - If user asks “make a new TUI tool/app”: start from `templates/minimal_tui_app.py`.
   - If integrating into existing code: create a small `tui.py` helper module + wire it in.

6. **Quality bar for “beautiful”**
   - Use a *small* consistent style palette (bold + 1–2 accent colors).
   - Use whitespace, alignment, and titles/captions.
   - Don’t rely on color alone for meaning (add labels/icons).
   - Keep refresh rates reasonable; don’t waste CPU.

## Output requirements
When you generate code:
- Include **exact files to create/edit** and their contents.
- Include **run commands**.
- Include a **quick test plan** (TTY vs piped output) and expected behavior.

## References / building blocks
- Template scaffold: `templates/minimal_tui_app.py`
