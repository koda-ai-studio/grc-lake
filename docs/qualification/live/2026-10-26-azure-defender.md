# Azure Defender for Cloud assessment receipt: 2026-10-26

<a id="azure-posture"></a>

A bounded, read-only pilot against one maintainer-owned Azure test subscription,
run after `azure-posture` started collecting Microsoft Defender for Cloud
assessments and binding a reviewed allowlist of them to safeguards. It records
whether real Azure evidence moves framework (CCF) results. It is not
qualification of other subscriptions, management-group scope, paid Defender
plans, service-principal or managed-identity authentication, or operating
effectiveness.

The live run used the pre-merge connector code from pull request #1076; after the run, only two test constants were renamed so public assessment GUIDs no longer resemble secrets to the secret scanner.

## Setup

- `DefaultAzureCredential` through the maintainer's local `az login` user
  session; not the hosted app-registration path.
- Source: `origin/main` `2b9c47dd` plus the connector change in pull request #1076; only this
  receipt was uncommitted. CPython 3.13.5, `uv run`, azure-identity 1.25.3. Defender
  assessments are read over ARM REST (`api-version=2021-06-01`) with the SDK
  credential's token; no Defender SDK is installed.
- Sequence: `connectors probe`, `connectors configure --state enabled`,
  `connectors sync`, then a second `connectors sync` to check recollection. A new
  local lake outside the repository, deleted after the run.

## Before

Not re-run for this receipt. The [2026-10-24 run](2026-10-24.md#azure-posture)
landed 26 rows (16 role assignments, 8 resources, 2 policy assignments), and the
connector on `2b9c47dd` sets no safeguard binding on any Azure row, so Azure
assessed no safeguard.

## After

| Item              | Result                                                                                                                                                         |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rows              | 80: 54 `azure.security.assessment`, 16 `azure.cloud.role_assignment`, 8 `azure.cloud.resource`, 2 `azure.cloud.policy_assignment`; no coverage gap             |
| Assessment status | 14 `pass` (Healthy), 33 `open` (Unhealthy), 7 `observed` (NotApplicable)                                                                                       |
| Asset types       | 38 on inventoried resources (`cloud_resource`), 16 on the subscription (`account_config`); 0 ambiguous assets                                                  |
| Bound             | 6, all "Secure transfer to storage accounts should be enabled": 4 pass, 2 fail                                                                                 |
| Safeguards        | `SG-DATAPROTECTION-001` fail (6 of 10 applicable assets assessed). `SG-IDENTITY-001`, `SG-LOGGING-001`, `SG-VULNERABILITYMANAGEMENT-001` stay `not_evaluated`. |
| Requirements      | 51 `fail`, 2,145 `not_evaluated`, 86 `unmapped`. Reviewed failures include SOC2-CC6.7, ISO27001-A.8.24 and HIPAA-164.312(e).                                   |
| Recollect         | 80 rows, 19 s                                                                                                                                                  |

Independent check: `az security assessment list` on the same subscription
returned 54 assessments, 14 Healthy, 33 Unhealthy and 7 NotApplicable. Every
resource-scoped assessment resolved to a resource from the inventory listing.

The other 48 assessments are unbound: their keys are not in the allowlist
(Defender plan enablement, security contacts, owner count, storage network
rules and private link, container registry network access). The subscription
has no Key Vault, SQL database or virtual machine, and no disabled or guest
account assessments were returned, so those mappings were not exercised live.

## Limits

One subscription, one user session and one point in time, on Defender's free
foundational CSPM tier. Throttling, page budgets, `nextLink` pagination and a
denied `Microsoft.Security/assessments/read` were exercised only by the offline
tests. Subscription, tenant, principal and resource identifiers and raw evidence
are excluded from this receipt.
