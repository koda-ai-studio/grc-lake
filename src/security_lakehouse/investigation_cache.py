"""Bounded process-local reuse of completed graph models, never partial builds."""

from collections import OrderedDict
from collections.abc import Callable, Mapping
from sys import getsizeof
from threading import Event, Lock
from time import monotonic
from typing import Any

from security_lakehouse.investigation_index import ReadIndexes

Model = tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], Mapping[str, Mapping[str, Any]], str, ReadIndexes]
Key = tuple[str, str]


def model_size(model: Model, limit: int, check: Callable[[], None]) -> int:
    """Account reachable Python objects, stopping once the retention budget is exceeded."""
    seen: set[int] = set()
    pending: list[Any] = [model]
    total = 0
    processed = 0
    while pending:
        if processed % 128 == 0:
            check()
        processed += 1
        item = pending.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        total += getsizeof(item)
        if total > limit:
            return total
        if isinstance(item, Mapping):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (tuple, list, set, frozenset)):
            pending.extend(item)
    return total


class _Flight:
    def __init__(self) -> None:
        self.ready = Event()
        self.model: Model | None = None


class ModelCache:
    """One model per lake, LRU eviction, cancellable same-key build coalescing.

    The byte budget accounts Python objects, not allocator overhead, active
    readers or builds. No lock is held while building or waiting on another build.
    """

    def __init__(self, *, max_bytes: int = 128 * 1024 * 1024, max_entries: int = 8, ttl: float = 60):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.ttl = ttl
        self._lock = Lock()
        self._entries: OrderedDict[Key, tuple[Model, int, float]] = OrderedDict()
        self._building: dict[Key, _Flight] = {}
        self._bytes = 0

    def get_or_build(
        self, key: Key, build: Callable[[], Model], valid: Callable[[], bool], check: Callable[[], None]
    ) -> Model:
        if self.max_bytes <= 0 or self.max_entries <= 0:
            check()
            return build()
        while True:
            check()
            with self._lock:
                for previous in list(self._entries):
                    if monotonic() - self._entries[previous][2] >= self.ttl:
                        self._bytes -= self._entries.pop(previous)[1]
                cached = self._entries.get(key)
                if cached is not None:
                    self._entries.move_to_end(key)
                    return cached[0]
                waiting = self._building.get(key)
                if waiting is None:
                    finished = _Flight()
                    self._building[key] = finished
                    break
            # A disconnected waiter must not cancel the leader or other readers.
            if waiting.ready.wait(0.05):
                check()
                if waiting.model is not None:
                    # Oversized models can serve existing waiters without
                    # becoming a retained cache entry. Their lifetime is bounded
                    # by active requests, just like an uncached build's result.
                    return waiting.model
        try:
            model = build()
            check()
            size = model_size(model, self.max_bytes, check)
            if valid():
                check()
                finished.model = model
                if size > self.max_bytes:
                    return model
                with self._lock:
                    for previous in list(self._entries):
                        if previous[0] == key[0]:
                            self._bytes -= self._entries.pop(previous)[1]
                    while self._entries and (
                        self._bytes + size > self.max_bytes or len(self._entries) >= self.max_entries
                    ):
                        self._bytes -= self._entries.popitem(last=False)[1][1]
                    self._entries[key] = model, size, monotonic()
                    self._bytes += size
            return model
        finally:
            with self._lock:
                del self._building[key]
                finished.ready.set()
