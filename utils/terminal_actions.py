"""Cross-platform, single-key terminal input for long-running workers."""

from __future__ import annotations

import os
import queue
import select
import sys
import threading
from typing import List, Optional


class TerminalKeyReader:
    """Read single keys without blocking worker progress.

    The reader is deliberately transport-only: callers decide which keys are
    actions. Non-interactive and redirected stdin safely disable the reader.
    """

    def __init__(self) -> None:
        self._keys: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fd: Optional[int] = None
        self._original_terminal = None
        self.active = False

    def start(self) -> bool:
        if self.active:
            return True
        try:
            if not sys.stdin or not sys.stdin.isatty():
                return False
        except Exception:
            return False

        self._stop.clear()
        if sys.platform == "win32":
            target = self._read_windows
        else:
            try:
                import termios
                import tty

                self._fd = sys.stdin.fileno()
                self._original_terminal = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
            except Exception:
                self._fd = None
                self._original_terminal = None
                return False
            target = self._read_posix

        self.active = True
        self._thread = threading.Thread(
            target=target,
            name="sulu-terminal-actions",
            daemon=True,
        )
        self._thread.start()
        return True

    def _read_windows(self) -> None:
        import msvcrt

        while not self._stop.wait(0.03):
            while msvcrt.kbhit():
                key = msvcrt.getwch()
                # Windows special keys arrive as a two-character sequence.
                if key in {"\x00", "\xe0"}:
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                    continue
                self._keys.put(key)

    def _read_posix(self) -> None:
        fd = self._fd
        if fd is None:
            return
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select([fd], [], [], 0.1)
                if readable:
                    raw = os.read(fd, 1)
                    if raw:
                        self._keys.put(raw.decode("utf-8", errors="ignore"))
            except (OSError, ValueError):
                return

    def drain(self) -> List[str]:
        keys: List[str] = []
        while True:
            try:
                keys.append(self._keys.get_nowait())
            except queue.Empty:
                return keys

    def stop(self) -> None:
        if not self.active:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.3)

        if self._fd is not None and self._original_terminal is not None:
            try:
                import termios

                termios.tcsetattr(
                    self._fd,
                    termios.TCSADRAIN,
                    self._original_terminal,
                )
            except Exception:
                pass

        self._thread = None
        self._fd = None
        self._original_terminal = None
        self.active = False

    def __enter__(self) -> "TerminalKeyReader":
        self.start()
        return self

    def __exit__(self, *_args) -> None:
        self.stop()
