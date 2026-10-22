"""Deterministic connector-local event id slugs."""

from __future__ import annotations

import hashlib
import re

_UNSAFE = re.compile(r"[^a-z0-9_.:-]+")
_DIGEST_CHARS = 32


def stable_id_slug(
    seed: str,
    *,
    fallback: str,
    limit: int = 96,
    keep: str = "head",
    unsafe: re.Pattern[str] = _UNSAFE,
) -> str:
    """Encode source identifiers without folding case or replacing punctuation.

    Safe lowercase seeds retain their identity. Escapes include percent itself;
    shortened IDs use a reserved tilde and a digest of the original bytes.
    Snapshot connectors replace older lossy IDs on their next complete refresh.
    """
    raw = str(seed)
    if not raw:
        return fallback
    if limit <= _DIGEST_CHARS + 1 or keep not in {"head", "tail"}:
        raise ValueError("invalid connector identity length or retention mode")
    slug = "".join(
        "".join(f"%{byte:02x}" for byte in char.encode("utf-8")) if char in "%~" or unsafe.fullmatch(char) else char
        for char in raw
    )
    if len(slug) <= limit:
        return slug
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
    room = limit - _DIGEST_CHARS - 1
    kept = slug[-room:] if keep == "tail" else slug[:room]
    return f"{kept}~{digest}"


__all__ = ["stable_id_slug"]
