"""Dependency-free verification of Stripe webhook signatures."""

from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_TOLERANCE_SECONDS = 300


def verify_stripe_signature(payload: bytes, header: str | None, secrets: list[str], *, now: int | None = None) -> bool:
    """Verify a ``Stripe-Signature`` header against the raw request body."""
    if not header or not secrets:
        return False
    timestamp: str | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not (timestamp.isascii() and timestamp.isdigit()) or not signatures:
        return False
    try:
        timestamp_seconds = int(timestamp)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp_seconds) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    signed = timestamp.encode() + b"." + payload
    for secret in secrets:
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if any(candidate.isascii() and hmac.compare_digest(expected, candidate) for candidate in signatures):
            return True
    return False
