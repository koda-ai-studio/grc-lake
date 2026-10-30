"""Bounded AWS organization inventory through an explicitly selected connection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from security_lakehouse.connections import connection_context
from security_lakehouse.connector_state import latest_config
from security_lakehouse.organization_scopes import _record, organization_scope
from security_lakehouse.timeutil import utc_now_iso_z

__all__ = ["discover_accounts", "discover_organization"]


def discover_accounts(client: Any, *, max_pages: int = 100) -> dict[str, Any]:
    accounts: dict[str, dict[str, Any]] = {}
    tokens: set[str] = set()
    token = None
    try:
        if not 1 <= max_pages <= 500:
            raise ValueError("invalid page budget")
        for _ in range(max_pages):
            page = client.list_accounts(MaxResults=20, **({"NextToken": token} if token else {}))
            if not isinstance(page.get("Accounts"), list):
                raise ValueError("malformed account page")
            for item in page["Accounts"]:
                account = item.get("Id")
                if not isinstance(account, str) or not re.fullmatch(r"\d{12}", account) or account in accounts:
                    raise ValueError("invalid or duplicate account")
                accounts[account] = {
                    "source_account_id": account,
                    "name": str(item.get("Name") or account)[:120],
                    "state": str(item.get("State") or "UNKNOWN"),
                    "access": "not_tested",
                }
            token = page.get("NextToken")
            if token is None:
                return {"complete": True, "accounts": list(accounts.values()), "error": None}
            if not isinstance(token, str) or not token or token in tokens:
                raise ValueError("invalid pagination token")
            tokens.add(token)
    except Exception as exc:
        if not isinstance(exc, (ValueError, TypeError, KeyError, OSError)) and not type(exc).__module__.startswith(
            "botocore."
        ):
            raise
        return {"complete": False, "accounts": list(accounts.values()), "error": "organization discovery incomplete"}
    return {
        "complete": False,
        "accounts": list(accounts.values()),
        "error": "organization discovery page budget exhausted",
    }


def discover_organization(
    lake: str | Path,
    organization_id: str,
    connection_id: str,
    *,
    actor: str = "system",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    from security_lakehouse.connectors_aws import AWSClient, verify_aws_account

    scope = organization_scope(lake, organization_id, expected_revision)
    child, info = connection_context(lake, connection_id)
    if info["connector_id"] != "aws-posture":
        raise ValueError("organization discovery currently requires an AWS connection")
    config = latest_config(child, "aws-posture")
    if not config or config.get("state") != "enabled":
        raise ValueError("enable and test the discovery connection first")
    credentials = config.get("credentials") or {}
    options = config.get("options") or {}
    try:
        client = AWSClient(
            region_name=options.get("region") or "us-east-1",
            role_arn=credentials.get("role_arn"),
            external_id=credentials.get("external_id"),
        )
        verify_aws_account(client, info["source_account_id"])
        result = discover_accounts(client.service_client("organizations"))
    except Exception as exc:
        if not isinstance(exc, (ValueError, TypeError, KeyError, OSError)) and not type(exc).__module__.startswith(
            "botocore."
        ):
            raise
        result = {"complete": False, "accounts": [], "error": "organization discovery failed"}
    return _record(
        lake,
        organization_id,
        {
            "kind": "discover",
            "scope": scope,
            "connection_id": connection_id,
            **result,
            "actor": actor,
            "occurred_at": utc_now_iso_z(),
        },
    )
