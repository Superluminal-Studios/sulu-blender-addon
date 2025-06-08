# utils/date_utils.py
from datetime import datetime

def format_submitted(ts: int | float | None) -> str:
    """Return a compact, locale-aware label without seconds."""
    if not ts:
        return "—"

    dt  = datetime.fromtimestamp(ts)   # local time
    now = datetime.now()

    # --- time ------------------------------------------------------
    # If the locale uses AM/PM, strftime('%p') is non-empty.
    uses_ampm = bool(dt.strftime("%p"))
    time_str  = dt.strftime("%-I:%M %p").strip() if uses_ampm else dt.strftime("%H:%M")

    # --- same-day? -------------------------------------------------
    if dt.date() == now.date():
        return time_str                          # e.g. “14:03” or “2:03 PM”

    # --- day & month (+year if different) -------------------------
    date_str = dt.strftime("%b %-d").replace(" 0", " ")   # “Jun 4”
    if dt.year != now.year:
        date_str += f" {dt.year}"                        # “Jun 4 2024”

    return f"{date_str}, {time_str}"
