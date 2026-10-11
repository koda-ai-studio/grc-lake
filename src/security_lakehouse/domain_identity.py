"""Separate platform authorization identity from source provenance identifiers."""

from typing import Any, NewType

PlatformTenantId = NewType("PlatformTenantId", str)
SourceAccountId = NewType("SourceAccountId", str)


def source_asset_key(row: dict[str, Any]) -> tuple[SourceAccountId, str]:
    legacy = str(row.get("tenant_id", ""))
    account = str(row.get("source_account_id", legacy))
    if "tenant_id" in row and account != legacy:
        raise ValueError("source account identity aliases disagree")
    return SourceAccountId(account), str(row["asset_id"])
