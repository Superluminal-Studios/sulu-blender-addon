def progress_cb(action: str, *, current: int | None = None, total: int | None = None, message: str = "") -> None:
    """
    Example progress callback for BAT packer.
    BAT calls progress callbacks with lightweight strings; keep this fast.
    """
    if current is not None and total:
        pct = (current / total) * 100
        print(f"[{action}] {current}/{total} ({pct:5.1f}%) {message}")
    else:
        print(f"[{action}] {message}")
