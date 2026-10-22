"""Human-readable asset names, kept alongside (never instead of) asset IDs.

A raw event may name its asset in ``entity.asset_name``. The name is display
data only: joins use source-account scope with ``asset_id``. Legacy unscoped
names only label unscoped rows. Names live on the gold asset rows
(``gold/asset_risk.jsonl``) rather than on normalized events, so the
``trustops.normalized_event.v1`` contract (and its Parquet and Iceberg exports)
is unchanged; read paths that show assets attach the name from there.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from security_lakehouse.projected_reads import read_projection
from security_lakehouse.read_cache import DerivedCache, input_versions

_ASSET_RISK = "gold/asset_risk.jsonl"
AssetNames = dict[str | tuple[str, str], str]

_ASSET_NAMES: DerivedCache[AssetNames] = DerivedCache(max_entries=64, per_root=1)


def entity_asset_id(entity: dict[str, Any]) -> str:
    """The asset ID normalization assigns to a raw event's entity."""
    for field in ("asset_id", "id", "name"):
        if field in entity:
            value = entity[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"entity.{field} must be a nonempty string")
    for field in ("asset_id", "id", "name"):
        if field in entity:
            return entity[field]
    raise ValueError("entity requires an asset_id, id, or legacy name")


def asset_name_key(row: dict[str, Any]) -> str | tuple[str, str]:
    """Keep legacy unscoped names separate from source-account scoped names."""
    asset = str(row.get("asset_id") or "")
    account = str(row.get("source_account_id", row.get("tenant_id", "")))
    return (account, asset) if account else asset


def names_from_assets(rows: Iterable[dict[str, Any]]) -> AssetNames:
    return {
        asset_name_key(row): str(row["asset_name"]) for row in rows if row.get("asset_id") and row.get("asset_name")
    }


def asset_name_for(row: dict[str, Any], names: AssetNames) -> str | None:
    return names.get(asset_name_key(row))


def asset_names_from_raw(raw_rows: Iterable[dict[str, Any]]) -> AssetNames:
    """Map asset ID to the first non-empty ``entity.asset_name`` seen for it."""
    names: AssetNames = {}
    for row in raw_rows:
        entity = row.get("entity")
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("asset_name") or "").strip()
        if name:
            names.setdefault(asset_name_key({**row, "asset_id": entity_asset_id(entity)}), name)
    return names


def load_asset_names(lake_dir: str | Path) -> AssetNames:
    """Asset ID to name, from the gold asset rows of a lake.

    Memoized per resolved lake root and asset file version; callers get a copy.
    """
    lake = Path(lake_dir)
    names = _ASSET_NAMES.get(lake, "asset_names", input_versions(lake, (_ASSET_RISK,)), lambda: _build(lake))
    return dict(names)


def _build(lake: Path) -> AssetNames:
    rows = read_projection(
        lake / _ASSET_RISK, ("asset_id", "asset_name", "source_account_id"), missing_ok=True, base_dir=lake
    )
    return names_from_assets(rows)


def with_asset_names(rows: list[dict[str, Any]], names: AssetNames) -> list[dict[str, Any]]:
    """Copy ``rows``, adding ``asset_name`` wherever the row's asset has one."""
    if not names:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        name = asset_name_for(row, names)
        out.append({**row, "asset_name": name} if name and not row.get("asset_name") else row)
    return out
