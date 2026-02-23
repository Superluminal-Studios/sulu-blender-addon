"""Finalize stage for download workflow."""

from __future__ import annotations


def finalize_download(
    *,
    logger,
    elapsed: float,
    dest_dir: str,
    open_folder_fn,
) -> None:
    choice = logger.logo_end(elapsed=elapsed, dest_dir=dest_dir)
    if choice == "o":
        open_folder_fn(dest_dir)
