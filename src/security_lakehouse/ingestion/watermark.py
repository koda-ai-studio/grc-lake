"""Per-connector high-water cursor (watermark) persistence.

An incremental pull needs to remember where it stopped so the next run only
fetches new records. Watermarks are appended to ``gold/watermarks.jsonl``
(append-only, auditable); cursors are partitioned by connector and collection scope.
Unscoped legacy cursors are never borrowed by a scoped collection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.io import append_jsonl, canonical_sha256, read_jsonl
from security_lakehouse.models import utc_iso

__all__ = ["WATERMARKS_FILE", "collection_scope", "read_watermark", "write_watermark"]

WATERMARKS_FILE = ("gold", "watermarks.jsonl")


def _path(lake_dir: str | Path) -> Path:
    return Path(lake_dir).joinpath(*WATERMARKS_FILE)


def collection_scope(
    config: dict[str, Any], *, repo: str | None, fixture_dir: str | Path | None, token_env: str
) -> str:
    """Bind a cursor to saved access and effective CLI/runtime collection overrides."""
    access = config.get("credential_fingerprint") or canonical_sha256(
        {"credentials": config.get("credentials"), "options": config.get("options")}
    )
    return canonical_sha256(
        {
            "version": 1,
            "access": access,
            "repo": repo,
            "fixture_dir": str(Path(fixture_dir).resolve()) if fixture_dir else None,
            "token_env": token_env,
        }
    )


def read_watermark(lake_dir: str | Path, connector_id: str, *, scope_id: str | None = None) -> str | None:
    """Return the cursor for exactly this connector and scope (None selects legacy rows)."""
    latest: str | None = None
    for row in read_jsonl(_path(lake_dir), missing_ok=True):
        if (
            row.get("connector_id") == connector_id
            and row.get("scope_id") == scope_id
            and row.get("cursor") is not None
        ):
            latest = str(row["cursor"])
    return latest


def write_watermark(lake_dir: str | Path, connector_id: str, cursor: str, *, scope_id: str | None = None) -> None:
    """Append a new high-water cursor for ``connector_id``."""
    append_jsonl(
        _path(lake_dir),
        {
            "connector_id": connector_id,
            "cursor": cursor,
            "scope_id": scope_id,
            "updated_at": utc_iso(datetime.now(UTC)),
        },
    )
