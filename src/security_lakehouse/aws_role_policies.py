"""Read-only role policy collection adapted from Agent-Bom (see NOTICE)."""

from __future__ import annotations

from typing import Any

from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.ingestion.paginate import paginate

PERMISSIONS = {
    "list_roles": "iam:ListRoles",
    "list_attached_role_policies": "iam:ListAttachedRolePolicies",
    "list_role_policies": "iam:ListRolePolicies",
    "get_policy": "iam:GetPolicy",
    "get_policy_version": "iam:GetPolicyVersion",
    "get_role_policy": "iam:GetRolePolicy",
}


def iam_gap(operation: str, *, reason: str = "read_failed") -> CollectionGapError:
    return CollectionGapError(
        f"AWS IAM role policy collection incomplete; check {PERMISSIONS[operation]}",
        collection=f"iam_roles:{operation}",
        reason=reason,
        permission=PERMISSIONS[operation],
    )


def iam_read(iam: Any, operation: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = getattr(iam, operation)(**kwargs)
        if not isinstance(response, dict):
            raise ValueError("invalid response")
        return response
    except CollectionGapError:
        raise
    except Exception as exc:
        response = getattr(exc, "response", {})
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        code = error.get("Code") if isinstance(error, dict) else None
        denied = code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}
        raise iam_gap(operation, reason="permission_denied" if denied else "read_failed") from exc


def iam_rows(iam: Any, operation: str, key: str, **kwargs: Any) -> list[Any]:
    def items(page: dict[str, Any]) -> list[Any]:
        rows = page[key]
        if not isinstance(rows, list):
            raise ValueError("invalid collection")
        return rows

    def cursor(page: dict[str, Any]) -> str | None:
        truncated = page.get("IsTruncated", False)
        if not isinstance(truncated, bool):
            raise ValueError("invalid truncation flag")
        if not truncated:
            return None
        marker = page.get("Marker")
        if not isinstance(marker, str) or not marker:
            raise ValueError("missing marker")
        return marker

    try:
        return list(
            paginate(
                lambda token: iam_read(iam, operation, **kwargs, **({"Marker": token} if token else {})), items, cursor
            )
        )
    except CollectionGapError:
        raise
    except Exception as exc:
        raise iam_gap(operation, reason="invalid_data") from exc


def read_role_policies(iam: Any, role_name: str) -> list[dict[str, Any]]:
    policies = []
    # Each role is atomic: a failed list/read cannot masquerade as an empty policy set.
    for entry in iam_rows(iam, "list_attached_role_policies", "AttachedPolicies", RoleName=role_name):
        if not isinstance(entry, dict) or not isinstance(arn := entry.get("PolicyArn"), str) or not arn:
            raise iam_gap("list_attached_role_policies", reason="invalid_data")
        metadata = iam_read(iam, "get_policy", PolicyArn=arn).get("Policy")
        version = metadata.get("DefaultVersionId") if isinstance(metadata, dict) else None
        if not isinstance(version, str) or not version:
            raise iam_gap("get_policy", reason="invalid_data")
        payload = iam_read(iam, "get_policy_version", PolicyArn=arn, VersionId=version).get("PolicyVersion")
        policies.append(
            {
                "policy_type": "managed",
                "policy_id": arn,
                "policy_version": version,
                "document": payload.get("Document") if isinstance(payload, dict) else None,
            }
        )
    for name in iam_rows(iam, "list_role_policies", "PolicyNames", RoleName=role_name):
        if not isinstance(name, str) or not name:
            raise iam_gap("list_role_policies", reason="invalid_data")
        payload = iam_read(iam, "get_role_policy", RoleName=role_name, PolicyName=name)
        policies.append({"policy_type": "inline", "policy_id": name, "document": payload.get("PolicyDocument")})
    return policies
