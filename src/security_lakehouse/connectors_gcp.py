"""GCP cloud-posture evidence collector.

A cloud-posture connector mirroring ``connectors_aws``. It collects read-only
GCP project posture signals — IAM role bindings on the project policy,
org/project policy constraints, and a Cloud Asset Inventory snapshot — and
emits them in the lake's raw evidence shape so they flow through the same
validate -> write -> pipeline path the ``github-security`` / ``okta-identity`` /
``aws-posture`` runners use.

Two clients sit behind one interface, mirroring ``connectors_aws``:

* :class:`GCPClient` — authenticated, read-only reads via the Google Cloud
  client libraries (Resource Manager, IAM, Cloud Asset Inventory). The Google
  client imports are lazy (inside the client) so the base/test install never
  needs them; CI runs entirely off fixtures.
* :class:`GCPFixtureClient` — reads ``iam_bindings.json`` / ``org_policies.json``
  / ``assets.json`` from a fixture directory so collection is fully testable
  without live GCP credentials.

The collector is strictly read-only and least-privilege: it only ever issues
``GetIamPolicy`` / ``ListOrgPolicies`` / ``GetEffectivePolicy`` / ``ListAssets``
style reads and never mutates GCP state.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.connector_errors import (
    CollectionGapError,
    ConnectorAccessError,
    ConnectorConfigError,
)
from security_lakehouse.connector_ids import stable_id_slug
from security_lakehouse.delegation import gcp_credentials
from security_lakehouse.identity import classify_identity_type
from security_lakehouse.ingestion.paginate import paginate
from security_lakehouse.io import canonical_sha256, read_json
from security_lakehouse.models import utc_iso

# Cloud/config controls that exist in controls/catalog.json. Verified before
# wiring (SOC2-CC6.1 logical access, ISO27001-A.5.15 access control,
# HIPAA-164.308(a)(4) access management).
IAM_CONTROLS = ["SOC2-CC6.1", "ISO27001-A.5.15", "HIPAA-164.308(a)(4)"]
POLICY_CONTROLS = ["SOC2-CC6.1", "ISO27001-A.5.15"]
ASSET_CONTROLS = ["SOC2-CC6.1"]

# GCP roles that grant broad, project-wide privilege. A binding to one of these
# is the noteworthy access signal an auditor should review.
PRIVILEGED_ROLES = {
    "roles/owner",
    "roles/editor",
    "roles/iam.securityAdmin",
    "roles/resourcemanager.organizationAdmin",
}

# Org-policy constraints whose enforcement we expect to be on. An unenforced
# constraint is an open config finding worth surfacing.
EXPECTED_ENFORCED_CONSTRAINTS = {
    "constraints/iam.disableServiceAccountKeyCreation",
    "constraints/compute.requireOsLogin",
}
# Expected-constraint verdicts bind to the logical access and MFA safeguard,
# which accepts account_config and carries POLICY_CONTROLS. The project passes
# only when every expected constraint is enforced: a bound not_evaluated
# (conditional, or an unreadable effective policy) blocks the pass.
# Privileged-role and public-member bindings are review signals, and
# observations stay unbound.
IDENTITY_SAFEGUARD = "SG-IDENTITY-001"
BINDABLE_STATUSES = {"pass", "open", "not_evaluated"}


# Each sub-collection, the API that serves it, and the IAM permission it needs.
# A disabled API or denied permission becomes a coverage gap for that
# sub-collection instead of failing the whole sync.
@dataclass(frozen=True)
class _Collection:
    key: str
    label: str
    api_label: str
    api: str
    permission: str


IAM_COLLECTION = _Collection(
    "iam_bindings",
    "project IAM bindings",
    "Cloud Resource Manager API",
    "cloudresourcemanager.googleapis.com",
    "resourcemanager.projects.getIamPolicy",
)
ORG_POLICY_COLLECTION = _Collection(
    "org_policies",
    "organization policies",
    "Org Policy API",
    "orgpolicy.googleapis.com",
    "orgpolicy.policies.list",
)
ASSET_COLLECTION = _Collection(
    "assets",
    "asset inventory",
    "Cloud Asset API",
    "cloudasset.googleapis.com",
    "cloudasset.assets.listResource",
)
# An expected constraint not set on the project is evaluated from its effective
# (inherited) policy. Google's REST reference names the permission
# orgpolicy.policies.get, but the IAM permission that exists, and that
# roles/orgpolicy.policyViewer grants, is orgpolicy.policy.get.
EFFECTIVE_ORG_POLICY_PERMISSION = "orgpolicy.policy.get"
EFFECTIVE_ORG_POLICY_COLLECTION = "effective_org_policies"
SERVICE_ACCOUNT_COLLECTION = _Collection(
    "service_accounts", "service accounts", "IAM API", "iam.googleapis.com", "iam.serviceAccounts.list"
)
_READ_FAILED = {
    "iam_bindings": "GCP collection incomplete: project IAM policy read failed",
    "org_policies": "GCP collection incomplete: organization policy read failed",
    "assets": "GCP collection incomplete: asset inventory read failed",
    "service_accounts": "GCP collection incomplete: service-account inventory read failed",
}
_SERVICE_NAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.googleapis\.com$")
_PERMISSION_NAME = re.compile(r"^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9]+){2,}$")
_PERMISSION_IN_MESSAGE = re.compile(r"[Pp]ermission '([a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9]+){2,})'")
_ADC_MISSING = (
    "GCP Application Default Credentials were not found; run "
    "'gcloud auth application-default login' or set GOOGLE_APPLICATION_CREDENTIALS"
)


def _collection_error(exc: Exception, collection: _Collection, project_id: str) -> ConnectorAccessError:
    """Map a Google client failure to an operator-safe error.

    Classification is duck-typed on ``google.api_core`` ``GoogleAPICallError``
    (``reason`` / ``metadata`` from the ``google.rpc.ErrorInfo`` detail, plus the
    HTTP ``code``) so the base install needs no Google packages. Provider text is
    never copied into the message; only a validated API or permission name is.
    """
    if type(exc).__name__ == "DefaultCredentialsError":
        return ConnectorAccessError(_ADC_MISSING)
    reason = str(getattr(exc, "reason", "") or "")
    raw_metadata = getattr(exc, "metadata", None)
    # ErrorInfo metadata is a protobuf map (a Mapping, not a dict).
    metadata = {str(k): str(v) for k, v in raw_metadata.items()} if isinstance(raw_metadata, Mapping) else {}
    message = str(getattr(exc, "message", "") or exc)
    code = getattr(exc, "code", None)
    project = _project_slug(project_id)
    not_collected = f"{collection.label} {'were' if collection.label.endswith('s') else 'was'} not collected"
    if reason == "SERVICE_DISABLED" or "has not been used in project" in message or "it is disabled" in message:
        service = metadata.get("service", "")
        api = service if _SERVICE_NAME.match(service) else collection.api
        label = collection.api_label if api == collection.api else api
        return CollectionGapError(
            f"{label} ({api}) is not enabled on project {project}; {not_collected}",
            collection=collection.key,
            reason="api_disabled",
            api=api,
        )
    if reason == "IAM_PERMISSION_DENIED" or type(exc).__name__ in {"PermissionDenied", "Forbidden"} or code == 403:
        permission = metadata.get("permission", "")
        if not _PERMISSION_NAME.match(permission):
            found = _PERMISSION_IN_MESSAGE.search(message)
            permission = found.group(1) if found else collection.permission
        return CollectionGapError(
            f"permission {permission} denied on project {project}; {not_collected}",
            collection=collection.key,
            reason="permission_denied",
            api=None,
            permission=permission,
        )
    return ConnectorAccessError(_READ_FAILED.get(collection.key, f"GCP collection incomplete: {collection.label}"))


def _effective_collection(identifier: str) -> _Collection:
    return _Collection(
        f"{EFFECTIVE_ORG_POLICY_COLLECTION}:{identifier}",
        f"effective policy for {identifier}",
        ORG_POLICY_COLLECTION.api_label,
        ORG_POLICY_COLLECTION.api,
        EFFECTIVE_ORG_POLICY_PERMISSION,
    )


def _effective_read_failed(identifier: str, project_id: str) -> CollectionGapError:
    return CollectionGapError(
        f"effective policy for {identifier} could not be read on project {_project_slug(project_id)}; "
        "its enforcement was not evaluated",
        collection=_effective_collection(identifier).key,
        reason="read_failed",
    )


def _boolean_enforcement(spec: Any) -> bool | None:
    """Only an explicit unconditional boolean rule establishes enforcement.

    Conditions, reset, and list (values/allow/deny) rules cannot be reduced to
    one verdict for the project, so they yield ``None``.
    """
    rules = getattr(spec, "rules", []) if spec is not None else []
    if len(rules) != 1 or getattr(spec, "reset", False):
        return None
    rule = rules[0]
    condition = getattr(getattr(rule, "condition", None), "expression", "")
    protobuf = getattr(rule, "_pb", None)
    kind = protobuf.WhichOneof("kind") if protobuf is not None else None
    value = getattr(rule, "enforce", None)
    if not condition and isinstance(value, bool) and (protobuf is None or kind == "enforce"):
        return value
    return None


def _items(payload: Any, collection: _Collection) -> Iterator[Any]:
    """Iterate SDK rows without mistaking an envelope for a collection."""
    if payload is None or isinstance(payload, (str, bytes, Mapping)):
        raise ConnectorAccessError(_READ_FAILED[collection.key])
    return iter(payload)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validated_records(payload: Any, collection: _Collection) -> list[dict[str, Any]]:
    """Reject the whole read when a record cannot be represented faithfully."""
    if not isinstance(payload, list):
        raise ConnectorAccessError(_READ_FAILED[collection.key])
    for item in payload:
        valid = isinstance(item, dict)
        if valid and collection == IAM_COLLECTION:
            members = item.get("members")
            condition = item.get("condition")
            valid = (
                _text(item.get("role"))
                and isinstance(members, list)
                and all(_text(member) for member in members)
                and (
                    condition is None
                    or isinstance(condition, dict)
                    and (not condition or _text(condition.get("expression")))
                    and all(isinstance(value, str) for value in condition.values())
                )
            )
        elif valid and collection == ORG_POLICY_COLLECTION:
            valid = _text(item.get("constraint") or item.get("name"))
        elif valid and collection == ASSET_COLLECTION:
            valid = _text(item.get("name"))
        if not valid:
            raise ConnectorAccessError(_READ_FAILED[collection.key])
    return payload


class GCPClient:
    """Authenticated, read-only GCP posture client.

    The Google Cloud client libraries are imported lazily so installs that
    never touch live GCP do not need them. Credentials resolve through Google's
    Application Default Credentials chain (``GOOGLE_APPLICATION_CREDENTIALS`` /
    workload identity / metadata server).
    """

    def __init__(self, project_id: str, *, credentials: Any = None) -> None:
        self.project_id = project_id
        self._credentials = credentials
        try:
            from google.cloud import (
                asset_v1,
                resourcemanager_v3,
            )
        except ImportError as exc:  # pragma: no cover - exercised only with live GCP
            raise ConnectorConfigError(
                "gcp-posture live collection requires google-cloud-resource-manager and "
                "google-cloud-asset; install the cloud extra or use --fixture-dir"
            ) from exc
        self._projects = resourcemanager_v3.ProjectsClient(credentials=credentials)
        self._assets = asset_v1.AssetServiceClient(credentials=credentials)
        # Org Policy lives in the separate google-cloud-org-policy distribution
        # (google.cloud.orgpolicy_v2), not resourcemanager_v3. Missing support
        # is reported as a coverage gap so the incomplete scope stays visible.
        self._org_policies: Any | None = None
        try:
            from google.cloud import orgpolicy_v2

            self._org_policies = orgpolicy_v2.OrgPolicyClient(credentials=credentials)
        except ImportError:  # pragma: no cover - optional dependency
            self._org_policies = None

    def service_accounts(self) -> list[dict[str, Any]]:
        """Port Agent-Bom's IAM inventory read; keep GRC credentials and page bounds."""
        try:
            from google.cloud import iam_admin_v1
        except ImportError:
            raise _service_account_gap("client_unavailable") from None
        try:
            client = iam_admin_v1.IAMClient(credentials=self._credentials)

            def fetch(token: str | None) -> Any:
                request = iam_admin_v1.ListServiceAccountsRequest(
                    name=f"projects/{self.project_id}", page_size=100, page_token=token or ""
                )
                # The public pager exposes its first response without advancing
                # another request; GRC owns cursor-loop and page-budget checks.
                return next(iter(client.list_service_accounts(request=request).pages))

            accounts = paginate(fetch, lambda page: page.accounts, lambda page: page.next_page_token or None)
            return [
                {
                    "email": account.email,
                    "uniqueId": account.unique_id,
                    "displayName": account.display_name,
                    "projectId": account.project_id,
                    "disabled": account.disabled,
                }
                for account in accounts
            ]
        except Exception as exc:  # noqa: BLE001 - optional inventory cannot expose provider exception text
            error = _collection_error(exc, SERVICE_ACCOUNT_COLLECTION, self.project_id)
            if isinstance(error, CollectionGapError):
                raise error from None
            raise _service_account_gap("listing_failed") from None

    def iam_bindings(self) -> list[dict[str, Any]]:
        try:
            policy = self._projects.get_iam_policy(
                request={"resource": f"projects/{self.project_id}", "options": {"requested_policy_version": 3}}
            )
            bindings: list[dict[str, Any]] = []
            for binding in _items(getattr(policy, "bindings", None), IAM_COLLECTION):
                item = {
                    "role": getattr(binding, "role", None),
                    "members": list(_items(getattr(binding, "members", None), IAM_COLLECTION)),
                }
                condition = getattr(binding, "condition", None)
                expression = getattr(condition, "expression", None) if condition is not None else ""
                if not isinstance(expression, str):
                    raise ConnectorAccessError(_READ_FAILED[IAM_COLLECTION.key])
                if expression:
                    item["condition"] = {
                        key: getattr(condition, key, "")
                        for key in ("expression", "title", "description", "location")
                        if getattr(condition, key, "")
                    }
                bindings.append(item)
            return _validated_records(bindings, IAM_COLLECTION)
        except Exception as exc:  # noqa: BLE001 - classified into an operator-safe error
            raise _collection_error(exc, IAM_COLLECTION, self.project_id) from None

    def org_policies(self) -> list[dict[str, Any]]:
        if self._org_policies is None:
            raise CollectionGapError(
                "google-cloud-org-policy is not installed; organization policies were not collected",
                collection=ORG_POLICY_COLLECTION.key,
                reason="client_unavailable",
            )
        policies: list[dict[str, Any]] = []
        try:
            listing = self._org_policies.list_policies(parent=f"projects/{self.project_id}")
            for policy in _items(listing, ORG_POLICY_COLLECTION):
                policies.append(
                    {
                        "name": getattr(policy, "name", ""),
                        "constraint": getattr(policy, "name", "").split("/policies/")[-1],
                        "enforced": _boolean_enforcement(getattr(policy, "spec", None)),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - provider details must not enter stored errors
            raise _collection_error(exc, ORG_POLICY_COLLECTION, self.project_id) from None
        return _validated_records(policies, ORG_POLICY_COLLECTION)

    def effective_org_policy(self, constraint: str) -> dict[str, Any]:
        """Read one constraint's effective policy (``GetEffectivePolicy``).

        Any failure, including 404 and a malformed response, is a gap for that
        constraint so its verdict stays ``not_evaluated``.
        """
        identifier = constraint.removeprefix("constraints/")
        try:
            if self._org_policies is None:
                raise ValueError("org policy client unavailable")
            policy = self._org_policies.get_effective_policy(name=f"projects/{self.project_id}/policies/{identifier}")
            spec = getattr(policy, "spec", None)
            if spec is None or isinstance(policy, (str, bytes, Mapping)):
                raise ValueError("malformed effective policy")
            enforced = _boolean_enforcement(spec)
        except Exception as exc:  # noqa: BLE001 - provider details must not enter stored errors
            error = _collection_error(exc, _effective_collection(identifier), self.project_id)
            if isinstance(error, CollectionGapError):
                raise error from None
            raise _effective_read_failed(identifier, self.project_id) from None
        return {"constraint": f"constraints/{identifier}", "enforced": enforced}

    def assets(self) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        try:
            listing = self._assets.list_assets(request={"parent": f"projects/{self.project_id}"})
            for asset in _items(listing, ASSET_COLLECTION):
                assets.append(
                    {
                        "name": getattr(asset, "name", ""),
                        "asset_type": getattr(asset, "asset_type", ""),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - provider details must not enter stored errors
            raise _collection_error(exc, ASSET_COLLECTION, self.project_id) from None
        return _validated_records(assets, ASSET_COLLECTION)


class GCPFixtureClient:
    """Offline GCP posture client backed by a fixture directory."""

    def __init__(self, fixture_dir: str | Path, *, project_id: str = "fixture-project") -> None:
        self.fixture = Path(fixture_dir)
        self.project_id = project_id

    def iam_bindings(self) -> list[dict[str, Any]]:
        return self._read_collection(IAM_COLLECTION, "bindings")

    def service_accounts(self) -> list[dict[str, Any]]:
        return read_json(self.fixture / "service_accounts.json")

    def org_policies(self) -> list[dict[str, Any]]:
        return self._read_collection(ORG_POLICY_COLLECTION)

    def assets(self) -> list[dict[str, Any]]:
        return self._read_collection(ASSET_COLLECTION, "assets")

    def effective_org_policy(self, constraint: str) -> dict[str, Any]:
        """Read ``effective_org_policies.json``; a missing file or constraint is a gap."""
        identifier = constraint.removeprefix("constraints/")
        try:
            payload = read_json(self.fixture / f"{EFFECTIVE_ORG_POLICY_COLLECTION}.json")
        except (OSError, ValueError):
            raise _effective_read_failed(identifier, self.project_id) from None
        for record in payload if isinstance(payload, list) else []:
            if not isinstance(record, dict):
                break
            if str(record.get("constraint", "")).removeprefix("constraints/") == identifier:
                enforced = record.get("enforced")
                if enforced is None or isinstance(enforced, bool):
                    return {"constraint": f"constraints/{identifier}", "enforced": enforced}
                break
        raise _effective_read_failed(identifier, self.project_id)

    def _read_collection(self, collection: _Collection, key: str | None = None) -> list[dict[str, Any]]:
        try:
            payload = read_json(self.fixture / f"{collection.key}.json")
            if isinstance(payload, dict) and key is not None:
                if payload.get("nextPageToken"):
                    raise ConnectorAccessError(_READ_FAILED[collection.key])
                payload = payload.get(key)
            return _validated_records(payload, collection)
        except (OSError, ValueError):
            raise ConnectorAccessError(_READ_FAILED[collection.key]) from None


def probe_gcp_access(*, credentials: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Prove live, read-only access to the configured project.

    Reads the project IAM policy (``resourcemanager.projects.getIamPolicy``),
    the one read every sync needs. Org Policy and Cloud Asset reads are optional
    at sync time (reported as coverage gaps), so the probe does not require them.
    """
    del options
    project_id = str(credentials.get("project_id") or "").strip()
    if not project_id:
        raise ConnectorConfigError("GCP probe requires project_id")
    try:
        delegated = gcp_credentials(credentials)
        client = GCPClient(project_id, credentials=delegated) if delegated is not None else GCPClient(project_id)
    except ConnectorConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified into an operator-safe error
        raise _collection_error(exc, IAM_COLLECTION, project_id) from None
    bindings = client.iam_bindings()
    return {
        "ok": True,
        "project_id": project_id,
        "capabilities": [IAM_COLLECTION.permission],
        "binding_count": len(bindings),
    }


def collect_gcp_evidence(
    client: GCPClient | GCPFixtureClient,
    *,
    project_id: str | None = None,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
    include_non_human_identities: bool = False,
) -> list[dict[str, Any]]:
    """Collect normalized raw posture evidence from a GCP project.

    Emits, per collection:

    * one IAM role-binding event per role bound on the project policy
      (privileged role -> high open finding for review),
    * one org/project policy event per policy constraint (an unenforced
      expected constraint is an open config finding),
    * one asset-inventory event per discovered resource (-> asset control).

    Every event passes :func:`security_lakehouse.validation.validate_raw_events`.
    """
    now = collected_at or datetime.now(UTC)
    project = _project_slug(project_id or client.project_id)
    rows: list[dict[str, Any]] = []
    gaps: list[CollectionGapError] = []

    def read(method: Any, collection: _Collection) -> list[dict[str, Any]]:
        try:
            return _validated_records(method(), collection)
        except CollectionGapError as gap:
            gaps.append(gap)
            return []

    bindings = read(client.iam_bindings, IAM_COLLECTION)
    for binding in bindings:
        rows.append(_iam_event(project, binding, now, tenant_id))

    policies = read(client.org_policies, ORG_POLICY_COLLECTION)
    policy_rows = [_policy_event(project, policy, now, tenant_id) for policy in policies]
    rows.extend(policy_rows)
    if not any(gap.collection == ORG_POLICY_COLLECTION.key for gap in gaps):
        # The listing returns only policies set on the project; an expected
        # constraint missing from it is inherited or at its default, which the
        # effective policy establishes. A failed read stays not_evaluated.
        listed = {row["attributes"]["constraint"] for row in policy_rows}
        for constraint in sorted(EXPECTED_ENFORCED_CONSTRAINTS - listed):
            unset: dict[str, Any] = {"constraint": constraint, "enforced": None}
            effective = False
            try:
                unset["enforced"] = client.effective_org_policy(constraint).get("enforced")
                effective = True
            except CollectionGapError as gap:
                gaps.append(gap)
            rows.append(_policy_event(project, unset, now, tenant_id, set_on_project=False, effective=effective))

    for asset in read(client.assets, ASSET_COLLECTION):
        rows.append(_asset_event(project, asset, now, tenant_id))

    base_keys = {IAM_COLLECTION.key, ORG_POLICY_COLLECTION.key, ASSET_COLLECTION.key}
    base_gaps = [gap for gap in gaps if gap.collection in base_keys]
    if len(base_gaps) == 3:
        raise ConnectorAccessError("GCP collection failed: " + "; ".join(gap.message for gap in base_gaps))
    if include_non_human_identities:
        binding_available = not any(gap.collection == "iam_bindings" for gap in gaps)
        rows.extend(_service_account_events(client, project, bindings, binding_available, now, tenant_id))
    rows.extend(_gap_event(project, gap, now, tenant_id) for gap in gaps)
    return rows


# Adapted from agent-bom/cloud/gcp_inv/iam.py:_discover_service_accounts,
# revision 95bc4a9c8e50d4bfbce59b91db8f68429cfbf9e5 (Apache-2.0).
# Copyright 2024-2026 Mohamed Wagdy Saad. See NOTICE.
def _service_account_gap(reason: str) -> CollectionGapError:
    return CollectionGapError(
        "GCP service-account metadata unavailable; coverage is incomplete",
        collection="service_accounts",
        reason=reason,
        api="iam.googleapis.com",
        permission="iam.serviceAccounts.list",
    )


def _service_account_events(
    client: GCPClient | GCPFixtureClient,
    project: str,
    bindings: list[dict[str, Any]],
    binding_available: bool,
    now: datetime,
    tenant_id: str,
) -> list[dict[str, Any]]:
    try:
        accounts = client.service_accounts()
        if not isinstance(accounts, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("email"), str)
            or "@" not in row["email"]
            or (row.get("projectId") is not None and row["projectId"] != client.project_id)
            or (row.get("uniqueId") is not None and not isinstance(row["uniqueId"], str))
            or (row.get("displayName") is not None and not isinstance(row["displayName"], str))
            for row in accounts
        ):
            raise ValueError("Invalid GCP service-account metadata")
        identity_ids = [(row.get("uniqueId") or "").strip() or row["email"].strip() for row in accounts]
        if len(set(identity_ids)) != len(identity_ids):
            raise ValueError("Duplicate GCP service-account identity")
    except CollectionGapError as gap:
        return [_gap_event(project, gap, now, tenant_id)]
    except Exception:  # noqa: BLE001 - malformed or denied optional metadata becomes a static coverage gap
        return [_gap_event(project, _service_account_gap("listing_failed"), now, tenant_id)]
    by_member: dict[str, dict[str, dict[str, Any]]] = {}
    for binding in bindings:
        for member in binding.get("members", []):
            prefix, _, email = str(member).partition(":")
            if prefix == "serviceAccount":
                entry = {"role": binding.get("role"), "condition": binding.get("condition") or None}
                by_member.setdefault(email.lower(), {})[canonical_sha256(entry)] = entry
    rows = []
    for account, identity_id in zip(accounts, identity_ids, strict=True):
        email = account["email"].strip()
        project_bindings = by_member.get(email.lower(), {})
        disabled = account.get("disabled")
        rows.append(
            _event(
                project=project,
                collected_at=now,
                tenant_id=tenant_id,
                signal="service_account",
                dedupe_key=canonical_sha256(identity_id),
                event_type="gcp.identity.service_account",
                asset_id=f"gcp:{project}:service_account:{identity_id}",
                asset_type="non_human_identity",
                controls=[],
                status="observed",
                severity="info",
                evidence_ref=f"//iam.googleapis.com/projects/{project}/serviceAccounts/{email}",
                attributes={
                    "identity_id": identity_id,
                    "identity_type": "service_account",
                    "source_scope": client.project_id,
                    "email": email,
                    "name": account.get("displayName") or email,
                    "lifecycle_status": "inactive"
                    if disabled is True
                    else "active"
                    if disabled is False
                    else "unknown",
                    "project_bindings": [project_bindings[key] for key in sorted(project_bindings)],
                    "binding_coverage": "project_policy_observed" if binding_available else "unavailable",
                    "permission_coverage": "not_collected",
                    "last_used_at": None,
                    "usage_coverage": "not_collected",
                },
            )
        )
    return rows


def _gap_event(project: str, gap: CollectionGapError, collected_at: datetime, tenant_id: str) -> dict[str, Any]:
    """A coverage-gap row: an actionable open item that neither passes nor fails a control."""
    return _event(
        project=project,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="collection_gap",
        dedupe_key=gap.collection,
        event_type="gcp.collection_gap",
        asset_id=f"gcp:project:{project}",
        asset_type="collection_scope",
        controls=[],
        status="open",
        severity="low",
        evidence_ref=f"gcp:{project}:collection-gap:{gap.collection}",
        attributes=gap.attributes(),
    )


def _iam_event(
    project: str,
    binding: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    role = str(binding["role"])
    members = sorted(str(m) for m in binding.get("members", []) if m)
    privileged = role in PRIVILEGED_ROLES
    public = bool({"allUsers", "allAuthenticatedUsers"}.intersection(members))
    condition = binding.get("condition") or {}
    binding_key = f"{role}:condition:{canonical_sha256(condition)}" if condition else role
    noteworthy = privileged or public
    # A binding can bind several members; classify each and collapse to a single
    # identity_type when they agree, otherwise mark the binding "mixed" (or
    # "unknown" when there are no members to classify).
    member_types = {classify_identity_type(member=m) for m in members}
    if not member_types:
        identity_type = "unknown"
    elif len(member_types) == 1:
        identity_type = member_types.pop()
    else:
        identity_type = "mixed"
    return _event(
        project=project,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="iam_binding",
        dedupe_key=binding_key,
        event_type="gcp.cloud.iam_binding",
        asset_id=f"gcp:project:{project}:role/{binding_key}",
        asset_type="iam_binding",
        controls=IAM_CONTROLS,
        # Conditions are retained for review; their expressions are not evaluated.
        status="open" if noteworthy else "observed",
        severity="high" if noteworthy else "info",
        evidence_ref=f"//cloudresourcemanager.googleapis.com/projects/{project}:getIamPolicy",
        attributes={
            "role": role,
            "members": members,
            "member_count": len(members),
            "identity_type": identity_type,
            "privileged": privileged,
            "public_members": public,
            "condition": condition,
        },
    )


def _policy_event(
    project: str,
    policy: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
    *,
    set_on_project: bool = True,
    effective: bool = False,
) -> dict[str, Any]:
    resource = str(policy.get("constraint") or policy.get("name") or "")
    identifier = resource.split("/policies/")[-1].removeprefix("constraints/")
    constraint = f"constraints/{identifier}" if identifier else ""
    raw_enforced = policy.get("enforced")
    enforced = raw_enforced if isinstance(raw_enforced, bool) else None
    expected = constraint in EXPECTED_ENFORCED_CONSTRAINTS
    # An expected-on constraint that is not enforced is the finding to raise.
    needs_enforcement = expected and enforced is False
    status = (
        "observed" if not expected else "not_evaluated" if enforced is None else "open" if needs_enforcement else "pass"
    )
    row = _event(
        project=project,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="org_policy",
        dedupe_key=resource,
        event_type="gcp.cloud.org_policy",
        asset_id=f"gcp:project:{project}",
        asset_type="account_config",
        controls=POLICY_CONTROLS,
        status=status,
        severity="medium" if needs_enforcement else "info",
        evidence_ref=f"//orgpolicy.googleapis.com/projects/{project}/policies/{identifier}"
        + (":getEffectivePolicy" if effective else ""),
        attributes={
            "constraint": constraint,
            "enforced": enforced,
            "expected_enforced": expected,
            "needs_enforcement": needs_enforcement,
            "set_on_project": set_on_project,
            "effective": effective,
        },
    )
    if status in BINDABLE_STATUSES:
        row["safeguard_ids"] = [IDENTITY_SAFEGUARD]
    return row


def _asset_event(
    project: str,
    asset: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    name = str(asset["name"])
    asset_type = str(asset.get("asset_type") or "unknown")
    return _event(
        project=project,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="asset",
        dedupe_key=name,
        event_type="gcp.cloud.asset",
        asset_id=f"gcp:asset:{name}",
        asset_type="cloud_resource",
        controls=ASSET_CONTROLS,
        status="observed",
        severity="info",
        evidence_ref=f"//cloudasset.googleapis.com/projects/{project}/assets/{name}",
        attributes={
            "asset_name": name,
            "asset_type": asset_type,
        },
    )


def _event(
    *,
    project: str,
    collected_at: datetime,
    tenant_id: str,
    signal: str,
    event_type: str,
    asset_id: str,
    asset_type: str,
    controls: list[str],
    status: str,
    severity: str,
    evidence_ref: str,
    attributes: dict[str, Any],
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    stable = _stable_suffix(project=project, signal=signal, asset_id=asset_id, dedupe_key=dedupe_key)
    return {
        "event_id": f"gcp-{stable}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": "gcp",
        "event_type": event_type,
        "entity": {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "asset_owner": project,
            "environment": "prod",
            "org": project,
        },
        "severity": severity,
        "status": status,
        "controls": controls,
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_ref,
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": attributes,
    }


def _project_slug(project_id: str) -> str:
    slug = re.sub(r"[^a-z0-9_.:-]+", "-", str(project_id).lower()).strip("-")
    return slug or "gcp-project"


def _stable_suffix(*, project: str, signal: str, asset_id: str, dedupe_key: str | None) -> str:
    """Build a deterministic connector-local id without hashing identity data.

    The pipeline computes the canonical raw evidence hash after collection. These
    IDs only need to be stable for connector upserts and evidence-room links.
    """
    return stable_id_slug(f"{project}:{signal}:{dedupe_key or asset_id}", fallback="gcp")
