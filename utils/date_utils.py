from __future__ import annotations
import os
from datetime import datetime

def format_submitted(ts: int | float | None) -> str:
    """Return a compact, locale-aware label (no seconds), working on Windows and Unix."""
    if not ts:
        return "—"

    dt  = datetime.fromtimestamp(ts)          # local time
    now = datetime.now()

    # ---------------- time portion ----------------
    # Hour without leading zero: %-I (POSIX) vs %#I (Windows)
    hour_fmt   = "%-I" if os.name != "nt" else "%#I"
    uses_ampm  = bool(dt.strftime("%p"))      # is this locale 12-hour?
    time_str   = (
        dt.strftime(f"{hour_fmt}:%M %p")      # 9:07 PM
        if uses_ampm
        else dt.strftime("%H:%M")             # 21:07
    )

    # ---------------- same day? -------------------
    if dt.date() == now.date():
        return time_str                       # e.g. “14:03” or “2:03 PM”

    # ---------------- date portion ---------------
    # %b = locale month abbrev; dt.day already has no leading zero
    date_str = f"{dt.strftime('%b')} {dt.day}"         # “Jun 4”
    if dt.year != now.year:
        date_str += f" {dt.year}"                      # “Jun 4 2024”

    return f"{date_str}, {time_str}"
