"""Per-process admission and cooperative cancellation for investigation graph builds.

A graph build reads the tenant's whole evidence generation into memory, so an
unbounded number of concurrent builds can exhaust a replica. Admission is
fail-fast: a saturated process rejects instead of queueing. A running build
checks its token between phases and inside per-row loops; an aborted build
raises, so no partial graph is ever returned.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping

DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_CONCURRENCY = 64


class GraphBuildAborted(RuntimeError):
    """A build stopped at a checkpoint; ``reason`` is ``deadline`` or ``disconnected``."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"graph build aborted: {reason}")
        self.reason = reason


class BuildToken:
    """Cancellation signal and optional deadline shared with one build thread."""

    def __init__(self, timeout_seconds: float | None, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._cancelled = threading.Event()
        self._deadline = None if timeout_seconds is None else clock() + timeout_seconds

    def cancel(self) -> None:
        self._cancelled.set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise GraphBuildAborted("disconnected")
        if self._deadline is not None and self._clock() >= self._deadline:
            raise GraphBuildAborted("deadline")


class GraphBuildSlots:
    """Non-blocking counting slots; a full process rejects rather than queues."""

    def __init__(self, capacity: int) -> None:
        if not 1 <= capacity <= MAX_CONCURRENCY:
            raise ValueError(f"graph build concurrency must be between 1 and {MAX_CONCURRENCY}")
        self.capacity = capacity
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    def try_acquire(self) -> bool:
        with self._lock:
            if self._active >= self.capacity:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._active <= 0:
                raise RuntimeError("graph build slot released more times than acquired")
            self._active -= 1


def graph_build_settings(env: Mapping[str, str]) -> tuple[int, float | None]:
    """Return ``(concurrency, timeout_seconds)``; a timeout of ``0`` disables the deadline."""
    raw_capacity = env.get("GRC_LAKE_GRAPH_BUILD_CONCURRENCY", "").strip() or str(DEFAULT_CONCURRENCY)
    capacity = int(raw_capacity)
    if not 1 <= capacity <= MAX_CONCURRENCY:
        raise ValueError(f"GRC_LAKE_GRAPH_BUILD_CONCURRENCY must be between 1 and {MAX_CONCURRENCY}")
    raw_timeout = env.get("GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS", "").strip() or str(DEFAULT_TIMEOUT_SECONDS)
    timeout = float(raw_timeout)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS must be a finite number >= 0")
    return capacity, (timeout or None)
