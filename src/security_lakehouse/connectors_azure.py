"""Azure cloud-posture evidence collector.

The fourth connector with a real runner. It collects read-only Azure
subscription posture signals — RBAC role assignments, policy assignments, and
resource posture — and emits them in the lake's raw evidence shape so they flow
through the same validate -> write -> pipeline path the ``github-security``,
``okta-identity`` and ``aws-posture`` runners use.

Two clients sit behind one interface, mirroring ``connectors_aws``:

* :class:`AzureClient` — authenticated read-only reads via the Azure SDK
  (``azure-identity`` + ``azure-mgmt-*``). The SDK imports are lazy (inside the
  client) so the base/test install never needs them; CI runs entirely off
  fixtures.
* :class:`AzureCliClient` — authenticated read-only reads via the ``az`` CLI.
  This keeps Azure Cloud Shell usable when the management SDK namespace shifts
  across installed versions.
* :class:`AzureFixtureClient` — reads ``role_assignments.json`` /
  ``policy_assignments.json`` / ``resources.json`` /
  ``security_assessments.json`` from a fixture directory so collection is fully
  testable without live Azure credentials.

Microsoft Defender for Cloud assessments are provider-evaluated verdicts, read
through the ARM REST API (no extra SDK): ``GET
https://management.azure.com/subscriptions/{id}/providers/Microsoft.Security/assessments?api-version=2021-06-01``
(https://learn.microsoft.com/rest/api/defenderforcloud-composite/assessments/list).
Pages carry ``value`` and ``nextLink``; ``properties.status.code`` is
``Healthy``, ``Unhealthy`` or ``NotApplicable``. Reader or Security Reader
grants ``Microsoft.Security/assessments/read``
(https://learn.microsoft.com/azure/defender-for-cloud/permissions).

The collector is strictly read-only and least-privilege: it only ever issues
list/read operations (``roleAssignments/read``, ``policyStates/read``,
``subscriptions/read``, ``Microsoft.Security/assessments/read`` and resource
list reads) and never mutates Azure state.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import (
    CollectionGapError,
    ConnectorAccessError,
    ConnectorConfigError,
    ConnectorOperatorError,
)
from security_lakehouse.connector_ids import stable_id_slug
from security_lakehouse.delegation import azure_credential
from security_lakehouse.execution_mode import in_server_mode
from security_lakehouse.identity import classify_identity_type
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import IncompleteCollectionError, paginate
from security_lakehouse.io import read_json
from security_lakehouse.models import utc_iso
from security_lakehouse.runtime_environment import runtime_env

# Identity/config controls that exist in controls/catalog.json. Verified before
# wiring (SOC2-CC6.1 logical access, ISO27001-A.5.15 access control,
# HIPAA-164.308(a)(4) access management).
IDENTITY_CONTROLS = ["SOC2-CC6.1", "ISO27001-A.5.15", "HIPAA-164.308(a)(4)"]
POLICY_CONTROLS = ["SOC2-CC6.1", "ISO27001-A.5.15"]
RESOURCE_CONTROLS = ["SOC2-CC6.1", "ISO27001-A.5.15"]

# Azure built-in roles that confer broad control-plane authority. A principal
# holding one of these at subscription scope is the noteworthy assignment for an
# auditor to review, so we surface it as an open finding.
PRIVILEGED_ROLE_NAMES = {"owner", "contributor", "user access administrator"}
# Stable provider-defined IDs remain usable when roleDefinitions/read is denied.
# https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged
BUILTIN_PRIVILEGED_ROLES = {
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
    "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
}

ARM_HOST = "management.azure.com"
ARM_TOKEN_SCOPE = "https://management.azure.com/.default"
SECURITY_ASSESSMENTS_API_VERSION = "2021-06-01"
SECURITY_ASSESSMENTS_COLLECTION = "security_assessments"
SECURITY_ASSESSMENTS_PERMISSION = "Microsoft.Security/assessments/read (Reader or Security Reader)"
DEFAULT_ASSESSMENT_MAX_PAGES = 200
ARM_TIMEOUT = 30

# Defender status codes; NotApplicable means the assessment did not run, so it
# is an observation and never a pass. Any other code is an unknown outcome.
ASSESSMENT_STATUS = {"healthy": "pass", "unhealthy": "open", "notapplicable": "observed"}
BINDABLE_STATUSES = {"pass", "open", "not_evaluated"}

IDENTITY_SAFEGUARD_CONTROLS = ("SOC2-CC6.1", "ISO27001-A.5.15", "HIPAA-164.308(a)(4)")
DATA_PROTECTION_CONTROLS = ("SOC2-CC6.7", "ISO27001-A.8.24")
LOGGING_CONTROLS = ("SOC2-CC7.2", "ISO27001-A.8.15", "HIPAA-164.312(b)")
VULNERABILITY_CONTROLS = ("SOC2-CC7.1", "ISO27001-A.8.8")


@dataclass(frozen=True)
class AssessmentSafeguard:
    """A reviewed binding of one built-in Defender assessment to one safeguard."""

    safeguard_id: str
    asset_type: str
    controls: tuple[str, ...]


# Built-in Defender assessment keys, verified against Microsoft's published
# assessment metadata (Microsoft.Security/assessmentMetadata). Bind only where
# the assessment's subject is what the safeguard definition assesses and the
# asset type is one it accepts; every other assessment keeps its verdict
# unbound. Subscription-scoped keys land on the subscription (account_config),
# resource-scoped keys on the resource (cloud_resource).
_IDENTITY = AssessmentSafeguard("SG-IDENTITY-001", "account_config", IDENTITY_SAFEGUARD_CONTROLS)
_DATA_PROTECTION = AssessmentSafeguard("SG-DATAPROTECTION-001", "cloud_resource", DATA_PROTECTION_CONTROLS)
DEFENDER_ASSESSMENT_SAFEGUARDS: dict[str, AssessmentSafeguard] = {
    # Disabled accounts with owner / read and write permissions should be removed.
    "050ac097-3dda-4d24-ab6d-82568e7a50cf": _IDENTITY,
    "a4899b81-b689-4e0d-aa29-45983ab8b7fc": _IDENTITY,
    "1ff0b4c9-ed56-4de6-be9c-d7ab39645926": _IDENTITY,
    "9b4f4dd4-24fc-42ba-9978-2a1cf575d36d": _IDENTITY,
    # Guest accounts with owner / write permissions should be removed.
    "20606e75-05c4-48c0-9d97-add6daa2109a": _IDENTITY,
    "f2864482-b329-4310-8c06-3cf74fe880c5": _IDENTITY,
    "0354476c-a12a-4fcc-a79d-f0ab7ffffdbb": _IDENTITY,
    "009678ce-adce-4c94-9cc8-cfc2bd0c6a06": _IDENTITY,
    # Secure transfer to storage accounts should be enabled (in transit).
    "1c5de8e1-f68d-6a17-e0d2-ec259c42768c": _DATA_PROTECTION,
    # Transparent Data Encryption on SQL databases should be enabled (at rest).
    "651967bf-044e-4bde-8376-3e08e0600105": _DATA_PROTECTION,
    # Diagnostic logs in Key Vault should be enabled.
    "88bbc99c-e5af-ddd7-6105-6150b2bfa519": AssessmentSafeguard("SG-LOGGING-001", "cloud_resource", LOGGING_CONTROLS),
    # Machines should have vulnerability findings resolved.
    "1195afff-c881-495e-9bc5-1486211ae03f": AssessmentSafeguard(
        "SG-VULNERABILITYMANAGEMENT-001", "cloud_resource", VULNERABILITY_CONTROLS
    ),
}

_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9.]{0,63}$")
_SUBSCRIPTION_SCOPE = re.compile(r"/subscriptions/([^/]+)/?", re.IGNORECASE)
_CREDENTIALS_UNAVAILABLE = (
    "Azure credentials are unavailable: DefaultAzureCredential found no usable identity "
    "(run az login, or configure a managed identity or service-principal environment variables)"
)


def _azure_access_error(exc: Exception, subscription_id: str) -> ConnectorOperatorError | None:
    """Map an Azure SDK or CLI failure to an operator-safe error, or ``None``.

    Duck-typed on ``azure.core.exceptions.HttpResponseError`` (``status_code``
    and ``error.code``) so the base install needs no Azure packages. Provider
    text is never copied; only a validated error code is.
    """
    if isinstance(exc, ConnectorOperatorError):
        return exc
    if type(exc).__name__ in {"CredentialUnavailableError", "ClientAuthenticationError"}:
        return ConnectorAccessError(_CREDENTIALS_UNAVAILABLE)
    status = getattr(exc, "status_code", None)
    raw_code = str(getattr(getattr(exc, "error", None), "code", "") or "")
    code = raw_code if _SAFE_ERROR_CODE.match(raw_code) else ""
    if status == 403 or code == "AuthorizationFailed":
        return ConnectorAccessError(
            f"Azure identity cannot read subscription {subscription_id} ({code or 'AuthorizationFailed'}); "
            "assign the Reader role at subscription scope"
        )
    if status == 404 or code in {"SubscriptionNotFound", "InvalidSubscriptionId"}:
        return ConnectorAccessError(
            f"Azure subscription {subscription_id} is not visible to this identity ({code or 'not found'})"
        )
    return None


def probe_azure_access(*, credentials: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Prove live, read-only access to the configured subscription.

    Reads the subscription itself (``Microsoft.Resources/subscriptions/read``)
    through the SDK, or the ``az`` CLI when the SDK is not installed, the same
    fallback sync uses. In hosted server mode the probe authenticates as the
    tenant's app registration (see :func:`security_lakehouse.delegation.azure_credential`)
    and never falls back to the CLI.
    """
    del options
    subscription_id = str(credentials.get("subscription_id") or "").strip()
    if not subscription_id:
        raise ConnectorConfigError("Azure probe requires subscription_id")
    try:
        client = build_azure_client(subscription_id, credentials, dict(runtime_env()))
        subscription = client.subscription()
    except Exception as exc:
        mapped = _azure_access_error(exc, subscription_id)
        if mapped is None:
            raise
        raise mapped from None
    return {
        "ok": True,
        "subscription_id": subscription_id,
        "subscription_state": str(subscription.get("state") or "unknown"),
        "capabilities": ["Microsoft.Resources/subscriptions/read"],
    }


def _require_arm_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != ARM_HOST or parts.netloc != ARM_HOST:
        raise ValueError("Azure security assessments collection incomplete: a link left the ARM host")
    return url


class ArmSecurityAssessmentReader:
    """Read-only, paged ARM list of a subscription's Defender for Cloud assessments.

    Requests go only to ``management.azure.com`` over HTTPS, the first built from
    the subscription id and every ``nextLink`` checked against that host (and
    revalidated on redirects). Pages are bounded; 429 and transient 5xx retry
    with ``Retry-After``. Refusals become a ``security_assessments`` collection
    gap; provider error text and the token are never copied.
    """

    def __init__(
        self,
        subscription_id: str,
        *,
        token_provider: Callable[[], str],
        max_pages: int = DEFAULT_ASSESSMENT_MAX_PAGES,
        timeout: int = ARM_TIMEOUT,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        self.subscription_id = subscription_id
        self.max_pages = max_pages
        self.timeout = timeout
        self._token_provider = token_provider
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"ArmSecurityAssessmentReader(subscription_id={self.subscription_id!r})"

    def assessments(self) -> list[dict[str, Any]]:
        subscription = urllib.parse.quote(self.subscription_id, safe="")
        first = (
            f"https://{ARM_HOST}/subscriptions/{subscription}/providers/Microsoft.Security/assessments"
            f"?api-version={SECURITY_ASSESSMENTS_API_VERSION}"
        )
        return list(
            paginate(lambda link: self._get(link or first), _assessment_page_rows, _next_link, max_pages=self.max_pages)
        )

    def _get(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            _require_arm_url(url),
            method="GET",
            headers={
                "accept": "application/json",
                "authorization": f"Bearer {self._token_provider()}",
                "user-agent": "grc-lake",
            },
        )
        try:
            payload = backoff.http_retry(lambda: self._open(request), sleep=self._sleep)
        except urllib.error.HTTPError as exc:
            raise _assessment_http_gap(exc.code) from None
        if not isinstance(payload, dict):
            raise ValueError("Azure security assessments collection incomplete: a page was not an object")
        return payload

    def _open(self, request: urllib.request.Request) -> Any:
        with netguard.open_guarded(request, timeout=self.timeout, validate=_require_arm_url, label="azure") as resp:
            return json.loads(resp.read().decode("utf-8"))


def _assessment_page_rows(page: dict[str, Any]) -> list[dict[str, Any]]:
    rows = page.get("value")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Azure security assessments collection incomplete: expected an array of objects")
    return rows


def _next_link(page: dict[str, Any]) -> str | None:
    link = page.get("nextLink")
    if link is None or link == "":
        return None
    if not isinstance(link, str):
        raise ValueError("Azure security assessments collection incomplete: malformed nextLink")
    return _require_arm_url(link)


def _assessment_http_gap(status: int) -> CollectionGapError:
    reason = {401: "unauthorized", 403: "permission_denied", 404: "not_found"}.get(status, "read_failed")
    return CollectionGapError(
        f"Azure Defender for Cloud assessments were not collected (HTTP {status})",
        collection=SECURITY_ASSESSMENTS_COLLECTION,
        reason=reason,
        api="Microsoft.Security/assessments",
        permission=SECURITY_ASSESSMENTS_PERMISSION if status in {401, 403} else None,
    )


def _assessment_gap(exc: Exception) -> CollectionGapError:
    """Turn any failed assessment read into an operator-safe coverage gap."""
    if isinstance(exc, CollectionGapError):
        return exc
    if isinstance(exc, IncompleteCollectionError):
        reason, detail = "page_budget_exhausted", "the page budget was exhausted"
    elif isinstance(exc, ValueError):
        reason, detail = "invalid_data", "the response was malformed or incomplete"
    elif isinstance(exc, ConnectorAccessError) and "AuthorizationFailed" in str(exc):
        reason, detail = "permission_denied", "AuthorizationFailed"
    else:
        reason, detail = "read_failed", "read failed"
    return CollectionGapError(
        f"Azure Defender for Cloud assessments were not collected ({detail})",
        collection=SECURITY_ASSESSMENTS_COLLECTION,
        reason=reason,
        api="Microsoft.Security/assessments",
        permission=SECURITY_ASSESSMENTS_PERMISSION if reason == "permission_denied" else None,
    )


def build_azure_client(
    subscription_id: str, credentials: dict[str, Any], env: dict[str, str]
) -> AzureClient | AzureCliClient:
    """The live client for ``subscription_id``: the tenant's app, or locally the ambient identity.

    A delegated credential always uses the SDK. Without one (local mode only;
    server mode raises), the SDK's ``DefaultAzureCredential`` is tried first and
    the ``az`` CLI login is the fallback.
    """
    env = runtime_env(env)
    delegated = azure_credential(credentials, env, label="azure-posture")
    if delegated is not None:
        return AzureClient(subscription_id, credential=delegated)
    try:
        return AzureClient(subscription_id)
    except (ConnectorConfigError, RuntimeError):
        return AzureCliClient(subscription_id)


class AzureClient:
    """Authenticated, read-only Azure subscription client backed by the SDK.

    The ``azure-identity`` / ``azure-mgmt-*`` imports are lazy so installs that
    never touch live Azure do not need them. ``credential`` is the tenant's
    delegated credential; without one, credentials resolve through
    ``DefaultAzureCredential`` (service-principal env vars, managed identity,
    Azure CLI login, etc.), which hosted server mode refuses.
    """

    def __init__(self, subscription_id: str, *, credential: Any = None) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.authorization import (
                AuthorizationManagementClient,
            )

            try:
                from azure.mgmt.resource.resources import ResourceManagementClient
            except ImportError:
                from azure.mgmt.resource import (
                    ResourceManagementClient,
                )
            try:
                from azure.mgmt.resource.policy import PolicyClient
            except ImportError:
                from azure.mgmt.resource import PolicyClient
        except ImportError as exc:  # pragma: no cover - exercised only with live Azure
            raise ConnectorConfigError(
                "azure-posture live collection requires azure-identity and azure-mgmt-* "
                "packages with resource and policy clients; install the cloud extra or use --fixture-dir"
            ) from exc
        self.subscription_id = subscription_id
        if credential is None:
            if in_server_mode():
                raise ConnectorConfigError(
                    "azure-posture in hosted mode requires the tenant's app registration credentials; "
                    "the server never collects with its own Azure identity"
                )
            credential = DefaultAzureCredential()
        self._credential = credential
        self._authz = AuthorizationManagementClient(credential, subscription_id)
        self._policy = PolicyClient(credential, subscription_id)
        self._resources = ResourceManagementClient(credential, subscription_id)

    def subscription(self) -> dict[str, Any]:
        from azure.mgmt.resource.subscriptions import (
            SubscriptionClient,
        )

        return self._as_dict(SubscriptionClient(self._credential).subscriptions.get(self.subscription_id))

    def role_assignments(self) -> list[dict[str, Any]]:
        return [self._as_dict(item) for item in self._authz.role_assignments.list_for_subscription()]

    def role_definitions(self) -> list[dict[str, Any]]:
        scope = f"/subscriptions/{self.subscription_id}"
        return [self._as_dict(item) for item in self._authz.role_definitions.list(scope)]

    def policy_assignments(self) -> list[dict[str, Any]]:
        if self._policy is None:
            raise ConnectorAccessError("Azure policy collection unavailable; assessment was not completed")
        return [self._as_dict(item) for item in self._policy.policy_assignments.list()]

    def resources(self) -> list[dict[str, Any]]:
        return [self._as_dict(item) for item in self._resources.resources.list()]

    def security_assessments(self) -> list[dict[str, Any]]:
        return ArmSecurityAssessmentReader(self.subscription_id, token_provider=self._arm_token).assessments()

    def _arm_token(self) -> str:
        try:
            return str(self._credential.get_token(ARM_TOKEN_SCOPE).token)
        except Exception as exc:
            mapped = _azure_access_error(exc, self.subscription_id)
            if mapped is None:
                raise
            raise mapped from None

    @staticmethod
    def _as_dict(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        as_dict = getattr(item, "as_dict", None)
        if callable(as_dict):
            payload = as_dict()
            if isinstance(payload, dict):
                return payload
        raise ValueError("Azure SDK returned a non-object collection record")


class AzureCliClient:
    """Authenticated, read-only Azure subscription client backed by ``az``.

    Azure Cloud Shell already has a logged-in ``az`` session. Using subprocess
    argument arrays avoids shell expansion, and all commands are read-only list
    calls scoped to the configured subscription.
    """

    def __init__(self, subscription_id: str, *, executable: str = "az") -> None:
        if in_server_mode():
            raise ConnectorConfigError("the az CLI login is the server's own identity and is not used in hosted mode")
        self.subscription_id = subscription_id
        resolved = shutil.which(executable)
        if resolved is None:
            raise ConnectorConfigError(
                "azure-posture live access requires the Azure SDK (cloud extra) or the az CLI on PATH"
            )
        self._az = resolved

    def subscription(self) -> dict[str, Any]:
        rows = self._run_json(["account", "show"], single_object=True)
        return rows[0]

    def role_assignments(self) -> list[dict[str, Any]]:
        return self._run_json(["role", "assignment", "list", "--include-inherited"])

    def role_definitions(self) -> list[dict[str, Any]]:
        return self._run_json(["role", "definition", "list"])

    def policy_assignments(self) -> list[dict[str, Any]]:
        return self._run_json(["policy", "assignment", "list"])

    def resources(self) -> list[dict[str, Any]]:
        return self._run_json(["resource", "list"])

    def security_assessments(self) -> list[dict[str, Any]]:
        return self._run_json(["security", "assessment", "list"])

    def _run_json(self, args: list[str], *, single_object: bool = False) -> list[dict[str, Any]]:
        cmd = [self._az, *args, "--subscription", self.subscription_id, "--output", "json"]
        try:
            completed = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConnectorAccessError("azure CLI command timed out during azure-posture collection") from exc
        except subprocess.CalledProcessError as exc:
            detail = _scrub_cli_error(exc.stderr)
            if "az login" in detail:
                raise ConnectorAccessError(
                    "azure CLI is not logged in; run az login for the subscription before syncing"
                ) from exc
            if "AuthorizationFailed" in detail:
                raise ConnectorAccessError(
                    f"Azure identity cannot read subscription {self.subscription_id} (AuthorizationFailed); "
                    "assign the Reader role at subscription scope"
                ) from exc
            raise RuntimeError(f"azure CLI command failed during azure-posture collection: {detail}") from exc

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ConnectorAccessError("azure CLI returned invalid JSON during azure-posture collection") from exc
        if single_object:
            if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not payload["id"].strip():
                raise ValueError("Azure subscription response must be an object with an identity")
            return [payload]
        if isinstance(payload, dict):
            # A paged REST envelope is not an exhausted CLI inventory. Never
            # publish its first page as the complete subscription snapshot.
            if payload.get("nextLink") or payload.get("next_link"):
                raise ValueError("Azure collection returned an unconsumed continuation")
            payload = payload.get("value")
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise ValueError("Azure collection response must contain only object records")
        return payload


class AzureFixtureClient:
    """Offline Azure client backed by a fixture directory."""

    def __init__(
        self, fixture_dir: str | Path, *, subscription_id: str = "00000000-0000-0000-0000-000000000000"
    ) -> None:
        self.fixture = Path(fixture_dir)
        self.subscription_id = subscription_id

    def role_assignments(self) -> list[dict[str, Any]]:
        return self._read_list("role_assignments.json")

    def role_definitions(self) -> list[dict[str, Any]]:
        return self._read_list("role_definitions.json")

    def policy_assignments(self) -> list[dict[str, Any]]:
        return self._read_list("policy_assignments.json")

    def resources(self) -> list[dict[str, Any]]:
        return self._read_list("resources.json")

    def security_assessments(self) -> list[dict[str, Any]]:
        payload = self._read("security_assessments.json")
        return (
            _assessment_page_rows(payload)
            if isinstance(payload, dict)
            else self._read_list("security_assessments.json")
        )

    def _read(self, name: str) -> Any:
        path = self.fixture / name
        return read_json(path) if path.exists() else []

    def _read_list(self, name: str) -> list[dict[str, Any]]:
        payload = self._read(name)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []


def collect_azure_evidence(
    client: AzureClient | AzureCliClient | AzureFixtureClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    """Collect normalized raw posture evidence from an Azure subscription.

    Emits, per collection:

    * one role-assignment event per RBAC assignment (-> identity controls; an
      Owner / Contributor / User Access Administrator assignment at subscription
      scope is a high open finding for review),
    * one policy-assignment event per Azure Policy assignment (-> policy
      controls; a disabled enforcement mode is an open finding),
    * one resource event per subscription resource (-> resource controls),
    * one Defender for Cloud assessment verdict per assessed resource; keys in
      :data:`DEFENDER_ASSESSMENT_SAFEGUARDS` bind to their safeguard. An
      unreadable assessment list is a coverage gap, never an empty success.

    Every event passes :func:`security_lakehouse.validation.validate_raw_events`.
    """
    now = collected_at or datetime.now(UTC)
    subscription = _subscription_slug(client.subscription_id)
    rows: list[dict[str, Any]] = []

    role_name_by_id = _role_definition_name_map(client)
    for assignment in client.role_assignments():
        event = _role_assignment_event(subscription, assignment, now, tenant_id, role_name_by_id)
        if event is not None:
            rows.append(event)

    for assignment in client.policy_assignments():
        event = _policy_assignment_event(subscription, assignment, now, tenant_id)
        if event is not None:
            rows.append(event)

    inventoried: dict[str, str] = {}
    for resource in client.resources():
        event = _resource_event(subscription, resource, now, tenant_id)
        if event is not None:
            rows.append(event)
            resource_id = event["attributes"]["resource_id"]
            inventoried.setdefault(resource_id.lower(), resource_id)

    try:
        assessments = client.security_assessments()
    except (RuntimeError, ValueError, OSError) as exc:
        rows.append(_gap_event(subscription, _assessment_gap(exc), now, tenant_id))
    else:
        for assessment in assessments:
            event = _assessment_event(subscription, assessment, now, tenant_id, inventoried)
            if event is not None:
                rows.append(event)

    return rows


def _assessment_event(
    subscription: str,
    assessment: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
    inventoried: dict[str, str],
) -> dict[str, Any] | None:
    props = _props(assessment)
    assessment_id = str(assessment.get("id") or "").strip()
    key = str(assessment.get("name") or "").strip().lower()
    if not assessment_id or not key:
        return None
    details = props.get("resourceDetails") or props.get("resource_details") or {}
    details = details if isinstance(details, dict) else {}
    resource_id = str(details.get("id") or details.get("Id") or "").strip()
    source = str(details.get("source") or details.get("Source") or "").strip()
    raw_status = props.get("status")
    status_body: dict[str, Any] = raw_status if isinstance(raw_status, dict) else {}
    code = str(status_body.get("code") or "").strip()
    status = ASSESSMENT_STATUS.get(code.lower(), "not_evaluated")

    subscription_scope = _SUBSCRIPTION_SCOPE.fullmatch(resource_id)
    if subscription_scope:
        asset_id, asset_type = f"azure:subscription:{_subscription_slug(subscription_scope[1])}", "account_config"
    elif source.lower() == "azure" and resource_id.startswith("/"):
        canonical = inventoried.get(resource_id.lower(), resource_id)
        asset_id, asset_type = f"azure:resource:{_id_slug(canonical)}", "cloud_resource"
    else:
        # On-premises machines and SQL servers carry no Azure resource id.
        asset_id, asset_type = f"azure:assessed-host:{_id_slug(assessment_id)}", "host"

    mapping = DEFENDER_ASSESSMENT_SAFEGUARDS.get(key)
    if mapping is not None and mapping.asset_type != asset_type:
        mapping = None
    row = _event(
        subscription=subscription,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="security_assessment",
        dedupe_key=assessment_id,
        event_type="azure.security.assessment",
        asset_id=asset_id,
        asset_type=asset_type,
        controls=list(mapping.controls) if mapping else [],
        status=status,
        severity="medium" if status == "open" else "info",
        evidence_ref=assessment_id,
        attributes={
            "assessment_id": assessment_id,
            "assessment_key": key,
            "display_name": str(props.get("displayName") or props.get("display_name") or "").strip(),
            "status_code": code or None,
            "status_cause": status_body.get("cause"),
            "status_change_date": status_body.get("statusChangeDate") or status_body.get("status_change_date"),
            "resource_id": resource_id or None,
            "resource_source": source or None,
            "mapped_safeguard_id": mapping.safeguard_id if mapping else None,
        },
    )
    if mapping is not None and status in BINDABLE_STATUSES:
        row["safeguard_ids"] = [mapping.safeguard_id]
    return row


def _gap_event(subscription: str, gap: CollectionGapError, collected_at: datetime, tenant_id: str) -> dict[str, Any]:
    """A coverage-gap row on its own scope asset, so no evidence asset gains a second type."""
    return _event(
        subscription=subscription,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="collection_gap",
        dedupe_key=gap.collection,
        event_type="azure.collection_gap",
        asset_id=f"azure:collection-scope:{subscription}",
        asset_type="collection_scope",
        controls=[],
        status="open",
        severity="low",
        evidence_ref=f"azure:{subscription}:collection-gap:{gap.collection}",
        attributes=gap.attributes(),
    )


def _role_assignment_event(
    subscription: str,
    assignment: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
    role_name_by_id: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    props = _props(assignment)
    assignment_id = str(assignment.get("id") or assignment.get("name") or props.get("scope") or "").strip()
    if not assignment_id:
        return None
    role_definition_id = str(props.get("role_definition_id") or props.get("roleDefinitionId") or "").strip()
    role_name = str(props.get("role_definition_name") or props.get("roleDefinitionName") or "").strip()
    if not role_name and role_definition_id:
        # The SDK role_assignments payload carries only the role definition id
        # (a GUID path), never the display name; resolve it from the role
        # definition catalog so privileged-role detection has a name to match.
        role_name = _resolve_role_name(role_definition_id, role_name_by_id or {})
    principal_id = str(props.get("principal_id") or props.get("principalId") or "").strip()
    principal_type = str(props.get("principal_type") or props.get("principalType") or "Unknown").strip()
    scope = str(props.get("scope") or f"/subscriptions/{subscription}").strip()
    privileged = role_name.lower() in PRIVILEGED_ROLE_NAMES
    subscription_scope = scope.lower().rstrip("/") == f"/subscriptions/{subscription}".lower()
    broad_scope = (
        subscription_scope
        or scope == "/"
        or bool(re.fullmatch(r"/providers/microsoft\.management/managementgroups/[^/]+/?", scope.lower()))
    )
    noteworthy = privileged and broad_scope
    return _event(
        subscription=subscription,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="role_assignment",
        dedupe_key=assignment_id,
        event_type="azure.cloud.role_assignment",
        asset_id=f"azure:role-assignment:{_id_slug(assignment_id)}",
        asset_type="identity_role_assignment",
        controls=IDENTITY_CONTROLS,
        status="open" if noteworthy else "observed" if role_name else "not_evaluated",
        severity="high" if noteworthy else "info",
        evidence_ref=assignment_id,
        attributes={
            "assignment_id": assignment_id,
            "role_name": role_name,
            "role_definition_id": role_definition_id,
            "principal_id": principal_id,
            "principal_type": principal_type,
            "identity_type": classify_identity_type(principal_type=principal_type),
            "scope": scope,
            "privileged_role": privileged if role_name else None,
            "subscription_scope": subscription_scope,
            "broad_scope": broad_scope,
        },
    )


def _policy_assignment_event(
    subscription: str,
    assignment: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
) -> dict[str, Any] | None:
    props = _props(assignment)
    assignment_id = str(assignment.get("id") or assignment.get("name") or "").strip()
    if not assignment_id:
        return None
    display_name = str(props.get("display_name") or props.get("displayName") or assignment.get("name") or "").strip()
    enforcement = str(props.get("enforcement_mode") or props.get("enforcementMode") or "Default").strip()
    scope = str(props.get("scope") or f"/subscriptions/{subscription}").strip()
    enforced = enforcement.lower() == "default"
    return _event(
        subscription=subscription,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="policy_assignment",
        dedupe_key=assignment_id,
        event_type="azure.cloud.policy_assignment",
        asset_id=f"azure:policy-assignment:{_id_slug(assignment_id)}",
        asset_type="cloud_policy",
        controls=POLICY_CONTROLS,
        # A policy assignment that is not enforcing is the noteworthy one.
        status="observed" if enforced else "open",
        severity="info" if enforced else "medium",
        evidence_ref=assignment_id,
        attributes={
            "assignment_id": assignment_id,
            "display_name": display_name,
            "enforcement_mode": enforcement,
            "is_enforced": enforced,
            "scope": scope,
            "policy_definition_id": props.get("policy_definition_id") or props.get("policyDefinitionId"),
        },
    )


def _resource_event(
    subscription: str,
    resource: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
) -> dict[str, Any] | None:
    resource_id = str(resource.get("id") or "").strip()
    if not resource_id:
        return None
    name = str(resource.get("name") or "").strip()
    resource_type = str(resource.get("type") or "").strip()
    location = str(resource.get("location") or "").strip()
    return _event(
        subscription=subscription,
        collected_at=collected_at,
        tenant_id=tenant_id,
        signal="resource",
        dedupe_key=resource_id,
        event_type="azure.cloud.resource",
        asset_id=f"azure:resource:{_id_slug(resource_id)}",
        asset_type="cloud_resource",
        controls=RESOURCE_CONTROLS,
        status="observed",
        severity="info",
        evidence_ref=resource_id,
        attributes={
            "resource_id": resource_id,
            "resource_name": name,
            "resource_type": resource_type,
            "location": location,
            "subscription_id": subscription,
        },
    )


def _role_definition_name_map(
    client: AzureClient | AzureCliClient | AzureFixtureClient,
) -> dict[str, str]:
    """Map Azure role definition ids -> display names, keyed for tolerant lookup.

    Resolution is best-effort: a least-privilege reader may lack
    ``roleDefinitions/read``, and not every client version exposes the SDK
    surface, so any failure yields an empty map and role names stay blank rather
    than failing the whole collection. Each definition is indexed by its full
    resource id, by its GUID name, and by the GUID tail of its id so an
    assignment's ``role_definition_id`` matches regardless of which form it
    carries.
    """
    getter = getattr(client, "role_definitions", None)
    if not callable(getter):
        return {}
    try:
        definitions = getter()
    except Exception:  # noqa: BLE001 - best-effort enrichment, never fatal
        return {}
    mapping: dict[str, str] = {}
    for definition in definitions or []:
        if not isinstance(definition, dict):
            continue
        props = _props(definition)
        name = str(props.get("role_name") or props.get("roleName") or "").strip()
        if not name:
            continue
        full_id = str(definition.get("id") or "").strip().lower()
        guid = str(definition.get("name") or "").strip().lower()
        if full_id:
            mapping[full_id] = name
            mapping[full_id.rsplit("/", 1)[-1]] = name
        if guid:
            mapping[guid] = name
    return mapping


def _resolve_role_name(role_definition_id: str, role_name_by_id: dict[str, str]) -> str:
    key = role_definition_id.lower()
    short = key.rsplit("/", 1)[-1]
    return role_name_by_id.get(key) or role_name_by_id.get(short) or BUILTIN_PRIVILEGED_ROLES.get(short, "")


def _props(item: dict[str, Any]) -> dict[str, Any]:
    """Return the SDK ``properties`` sub-object, accepting flat fixtures too.

    Azure SDK ``as_dict`` payloads nest most fields under ``properties``; small
    fixtures may inline them at the top level, so we merge both views with the
    nested properties taking precedence.
    """
    merged: dict[str, Any] = {k: v for k, v in item.items() if k != "properties"}
    nested = item.get("properties")
    if isinstance(nested, dict):
        merged.update(nested)
    return merged


def _event(
    *,
    subscription: str,
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
    stable = _stable_suffix(subscription=subscription, signal=signal, asset_id=asset_id, dedupe_key=dedupe_key)
    return {
        "event_id": f"azure-{stable}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": "azure",
        "event_type": event_type,
        "entity": {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "asset_owner": subscription,
            "environment": "prod",
            "org": subscription,
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


def _subscription_slug(subscription_id: str) -> str:
    slug = re.sub(r"[^a-z0-9_.:-]+", "-", str(subscription_id).lower()).strip("-")
    return slug or "azure-subscription"


def _id_slug(value: str) -> str:
    return stable_id_slug(str(value), fallback="azure", keep="tail")


def _stable_suffix(*, subscription: str, signal: str, asset_id: str, dedupe_key: str | None) -> str:
    """Build a deterministic connector-local id without hashing identity data.

    The pipeline computes the canonical raw evidence hash after collection. These
    IDs only need to be stable for connector upserts and evidence-room links.
    Azure resource IDs share long common prefixes (the subscription and provider
    path) and carry their distinguishing name in the tail, so the slug keeps the
    tail when it exceeds the length cap, plus a digest so two resources that
    share a tail (same name, different resource group) stay distinct.
    """
    return stable_id_slug(f"{subscription}:{signal}:{dedupe_key or asset_id}", fallback="azure", keep="tail")


def _scrub_cli_error(stderr: str | None) -> str:
    message = " ".join(str(stderr or "").split())
    if not message:
        return "no stderr"
    return message[:300]
