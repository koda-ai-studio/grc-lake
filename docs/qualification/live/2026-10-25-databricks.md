# Databricks trial receipt: 2026-10-25

<a id="databricks-evidence-lake"></a>

One maintainer-owned Express trial workspace and one serverless SQL warehouse
were used for a bounded live transport check. The adapter remains **Preview**.
This is not qualification of a published artifact, production availability,
capacity, or other tenants.

## Source and setup

- Connector and pipeline: clean source `6268edbd`, frozen dependency lockfile.
- Bootstrap: an external candidate of `deploy/databricks/bootstrap_poc.sql`,
  SHA-256 `a8c32fb1fdf3e9d3bc1d3e191f0a04271461dffde9b477ae172e1a75d1c0001a`.
  The candidate SQL is incorporated in this change, with explanatory comments.
- Databricks CLI 1.22.1, downloaded from its official release and checked against
  the published archive checksum. Operator authentication used supported OAuth
  U2M; collection used a separate service principal with OAuth client credentials.
- The operator created the demo catalog, two schemas and eight views, and granted
  the reader catalog/schema use, view-schema SELECT and warehouse CAN USE. Setup
  mutations were separate from the read-only connector runs.
- The reader's one-day secret was stored in a private local file and supplied
  only through a secret reference. It was revoked and the file removed after the
  checks; warehouse shutdown was requested. No payment method or customer cloud
  account was linked for this trial.

## Live results

Each schema passed probe, configuration and two syncs through the real connector
runner, followed by `run_pipeline`. Provider-side SQL counts were reconciled
independently using the operator CLI. The count check therefore used a different
identity from collection; the connector's successful SELECTs establish reader
access to the views.

| View                                 | Synthetic fixture schema | System audit schema |
| ------------------------------------ | ------------------------ | ------------------- |
| Audit events                         | 2                        | 0                   |
| Control posture                      | 2                        | 2                   |
| Asset risk                           | 2                        | 0                   |
| Evidence bundles                     | 2                        | 0                   |
| Total unique rows after recollection | 8                        | 2                   |

The synthetic views contained only the existing repository's Databricks fixtures.
Their outcomes were three observations, three open findings and two passes.
These exercise transport and normalization, not actual security posture. The
new trial's system audit log was empty, so its two summary outcomes were both
`not_evaluated`. Recollection retained the same unique row counts; normalized
counts matched raw counts. The secret value was absent from all lake files.

Both resulting CCF assessments had 2,196 requirements `not_evaluated` and 86
`unmapped`. Neither run produced an attested framework pass. A separate SELECT
against `system.access.audit` using the reader identity was denied, while its
curated views remained readable. This checks that boundary, not every inherited
permission in the workspace.

## Defects found

The original bootstrap failed because the live `response` struct exposed
`status_code`, while the SQL referenced `statusCode`. Serializing the struct and
reading either JSON key supports both shapes without referencing a nonexistent
struct field. The original aggregation also treated an empty denied-access
window as passing. The candidate keeps empty or incomplete windows
`not_evaluated`, while an observed denied request remains open.

Offline regression tests execute all four SELECT projections in DuckDB with
explicit function adapters. Ten cases failed on the original SQL; all thirteen
passed with the candidate. This harness is a bounded semantic check, separate
from the live Databricks execution above.

<a id="databricks-populated-audit"></a>

## Populated audit log run

Later the same day, the same maintainer-owned trial workspace had a populated
system audit log: 462 rows from 16 services, counted by the operator identity.
The committed `deploy/databricks/bootstrap_poc.sql` at source `3235c9ad` was
re-applied unchanged to the system audit schema, with the reader service
principal's grants. Collection used that service principal with a one-day OAuth
secret, supplied only through a secret reference from a private local file.

| Step                  | Result                                                                  |
| --------------------- | ----------------------------------------------------------------------- |
| Probe                 | ok                                                                      |
| Configure             | enabled                                                                 |
| Sync 1                | 928 records, no coverage gaps                                           |
| Sync 2 (recollection) | 928 records, no coverage gaps; 928 unique raw event IDs, 928 normalized |

The 928 records reconcile with the four views: 462 audit events, 2 control
posture rows, 2 asset risk rows and 462 evidence bundles. The operator identity
independently counted 16 audit rows with a response status of 400 or higher; the
lake holds 16 open audit events and 16 matching open evidence bundles, with all
other audit rows `observed`. Control posture had 6 failing and 2 `not_evaluated`
controls. The secret value was absent from every lake file and command output.

The CCF assessment stayed at 2,196 `not_evaluated` and 86 `unmapped`
requirements, because these view-based events carry no `safeguard_ids`; binding
evaluated connector evidence to safeguards is tracked separately. No framework
pass was produced.

Teardown: the secret was revoked, the reader service principal was deleted at
workspace and account level, the `trustops` catalog (views only) was dropped, the
warehouse was stopped and the local secret file and CLI credentials were removed.

<a id="databricks-multichunk"></a>

## Multi-chunk run (2026-10-26)

On the same trial workspace, with source `8b2500cf` (v0.3.14), the committed
bootstrap was re-applied and a separate qualification schema exposed the four
views with the audit view widened to 1,016 real audit rows plus 75,000 rows
explicitly labelled `synthetic-multichunk`. Read in full, that view returned
76,016 rows in **3 result chunks**. A newly created reader service principal was
first refused with HTTP 403 until it was given the workspace
`databricks-sql-access` entitlement; the documented minimum permissions now
include it.

| Step                  | Result                                                        |
| --------------------- | ------------------------------------------------------------- |
| Sync 1                | 77,036 records, no coverage gaps (157 s)                      |
| Sync 2 (recollection) | 77,036 records, no coverage gaps; 77,036 unique raw event IDs |

The 77,036 records equal the provider-side view counts (76,016 + 2 + 2 + 1,016),
all 75,000 synthetic rows arrived, and the 38 audit rows with a response status of
400 or higher arrived as 38 open audit events with 38 matching open bundles. The
secret value was absent from every lake file and output. A first attempt with
100,000 synthetic rows (102,036 events) stopped at the local full-rebuild limit
of 100k events, which asks for an external evidence sink; that is intended
behavior. Teardown matched the earlier runs: secret revoked, reader deleted at
workspace and account level, catalog dropped, warehouse stopped, local credentials
removed.

The populated audit and multi-chunk runs above close those gaps. No live 429 retry, credential expiry,
provider recovery, production scale or failover was exercised. The preview stage
and [follow-up #734](https://github.com/koda-ai-studio/grc-lake/issues/734) remain.
Provider identifiers, hostnames, principal names, credentials and raw evidence
are excluded from this receipt.

Official references: [OAuth U2M](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m),
[Statement Execution API](https://docs.databricks.com/api/statement-execution/v1/execute-statement),
and [Express setup](https://docs.databricks.com/aws/en/getting-started/express-setup).
