"""Pure-Python one-shot worker used by Blender's modal import operator."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .cancellation import CancellationToken

ResultT = TypeVar("ResultT")
PrepareCallback = Callable[[dict[str, Any], CancellationToken], ResultT]


@dataclass(frozen=True)
class WorkerOutcome(Generic[ResultT]):
    """Terminal worker value, published atomically after preparation ends."""

    result: ResultT | None = None
    error: BaseException | None = None


class ModalPreparationWorker(Generic[ResultT]):
    """Run one preparation callback off the Blender UI thread exactly once."""

    def __init__(
        self,
        settings: dict[str, Any],
        prepare: PrepareCallback[ResultT],
        *,
        thread_name: str = "SuluMarketAssetDownload",
    ) -> None:
        self._settings = settings.copy()
        self._prepare = prepare
        self._thread_name = thread_name
        self._cancellation = CancellationToken()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._outcome: WorkerOutcome[ResultT] | None = None

    @property
    def started(self) -> bool:
        with self._lock:
            return self._thread is not None

    @property
    def cancellation_requested(self) -> bool:
        return self._cancellation.cancelled

    @property
    def outcome(self) -> WorkerOutcome[ResultT] | None:
        with self._lock:
            return self._outcome

    def start(self) -> bool:
        """Start once, returning ``False`` without spawning on duplicate calls."""

        with self._lock:
            if self._thread is not None:
                return False
            thread = threading.Thread(
                target=self._run,
                name=self._thread_name,
                daemon=True,
            )
            self._thread = thread
        thread.start()
        return True

    def _run(self) -> None:
        try:
            outcome = WorkerOutcome(result=self._prepare(self._settings, self._cancellation))
        except BaseException as exc:
            # Never report through Blender from here. The modal main-thread poll owns reporting.
            outcome = WorkerOutcome[ResultT](error=exc)
        with self._lock:
            self._outcome = outcome

    def is_alive(self) -> bool:
        with self._lock:
            thread = self._thread
        return thread is not None and thread.is_alive()

    def wait(self, timeout: float | None = None) -> bool:
        """Join for tests/teardown and report whether a terminal outcome exists."""

        with self._lock:
            thread = self._thread
        if thread is None:
            return False
        thread.join(timeout)
        return self.outcome is not None

    def cancel(self) -> None:
        self._cancellation.cancel()
