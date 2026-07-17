"""Thread-safe cooperative cancellation for network and cache operations."""

from __future__ import annotations

import threading
from collections.abc import Callable

from .errors import CancelledError

CancelCallback = Callable[[], None]


class CancellationToken:
    """One-shot cancellation token that can promptly close blocking resources."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: set[CancelCallback] = set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        callbacks: tuple[CancelCallback, ...]
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                # Cancellation is best effort and must remain idempotent.
                pass

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledError("Sulu Market asset import was cancelled")

    def register(self, callback: CancelCallback) -> Callable[[], None]:
        """Register a close callback and return an idempotent unregister function."""

        call_now = False
        with self._lock:
            if self._event.is_set():
                call_now = True
            else:
                self._callbacks.add(callback)
        if call_now:
            try:
                callback()
            except Exception:
                pass

        def unregister() -> None:
            with self._lock:
                self._callbacks.discard(callback)

        return unregister
