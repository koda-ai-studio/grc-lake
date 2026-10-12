"""Exponential backoff + jitter, honoring HTTP ``Retry-After`` on 429.

API limits are a fact of ingestion at scale. :func:`retry` wraps a call and
re-tries on caller-classified transient failures, sleeping with exponential
backoff + jitter — and deferring to a server-provided ``Retry-After`` when one
is present (the correct behavior for HTTP 429). ``sleep`` is injectable so tests
never actually wait.
"""

from __future__ import annotations

import email.utils
import math
import random
import time
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

T = TypeVar("T")

# Status codes that warrant a retry (rate-limit + transient gateway errors).
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


def is_retryable_http(exc: BaseException) -> bool:
    """A 429 or transient 5xx from any HTTP source is worth retrying."""
    return isinstance(exc, urllib.error.HTTPError) and exc.code in RETRYABLE_STATUS


def http_retry_after(exc: BaseException) -> float | None:
    """Read a server ``Retry-After`` (seconds) from a 429 response, if present.

    Accepts delta-seconds (integer, or decimal as some APIs send) and HTTP-date
    strings; a date without a zone is read as UTC.
    """
    if not isinstance(exc, urllib.error.HTTPError) or not exc.headers:
        return None
    raw = str(exc.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    if seconds is not None:
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def next_delay(
    attempt: int,
    *,
    base: float = 0.5,
    cap: float = 300.0,
    retry_after: float | None = None,
    jitter: bool = True,
) -> float:
    """Seconds to sleep before retry ``attempt`` (0-indexed).

    A server ``Retry-After`` wins (capped at ``cap``); otherwise exponential
    ``base*2**n`` with full jitter to avoid thundering-herd retries.
    """
    if retry_after is not None:
        return max(0.0, min(float(retry_after), cap))
    delay = min(base * (2**attempt), cap)
    if jitter:
        delay = random.uniform(0, delay)
    return delay


def retry(
    fn: Callable[[], T],
    *,
    is_retryable: Callable[[Exception], bool],
    retry_after: Callable[[Exception], float | None] = lambda _exc: None,
    max_retries: int = 4,
    base: float = 0.5,
    cap: float = 30.0,
    sleep: Callable[[float], Any] | None = None,
    max_elapsed: float = 120.0,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Call ``fn`` with retry on classified-transient exceptions.

    ``is_retryable`` decides whether an exception is worth retrying;
    ``retry_after`` extracts a server-suggested delay (e.g. from a 429 header).
    Raises the last exception once ``max_retries`` is exhausted. ``sleep``
    defaults to :func:`time.sleep`, resolved at call time so tests can patch it.
    """
    if type(max_retries) is not int or not 0 <= max_retries <= 20:
        raise ValueError("max_retries must be between 0 and 20")
    if any(not math.isfinite(value) or value < 0 for value in (base, cap, max_elapsed)) or max_elapsed == 0:
        raise ValueError("retry bounds must be finite and nonnegative with a positive deadline")
    _sleep = sleep or time.sleep
    deadline = clock() + max_elapsed
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= max_retries or not is_retryable(exc):
                raise
            advised = retry_after(exc)
            # Never shorten a provider's requested wait to our local budget.
            # Give control back to the caller instead of retrying too early.
            if advised is not None and (not math.isfinite(advised) or advised > cap):
                raise
            delay = next_delay(attempt, base=base, cap=cap, retry_after=advised)
            if clock() + delay >= deadline:
                raise
            _sleep(delay)
            if clock() >= deadline:
                raise
            attempt += 1


def http_retry(fn: Callable[[], T], **kwargs: Any) -> T:
    """Retry ``fn`` on retryable HTTP errors (429 / transient 5xx), honoring ``Retry-After``."""
    return retry(fn, is_retryable=is_retryable_http, retry_after=http_retry_after, **kwargs)
