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

## Remaining qualification

No populated system audit window, multi-chunk result, 429 retry, credential expiry,
provider recovery, production scale or failover was exercised. The preview stage
and [follow-up #734](https://github.com/koda-ai-studio/grc-lake/issues/734) remain.
Provider identifiers, hostnames, principal names, credentials and raw evidence
are excluded from this receipt.

Official references: [OAuth U2M](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m),
[Statement Execution API](https://docs.databricks.com/api/statement-execution/v1/execute-statement),
and [Express setup](https://docs.databricks.com/aws/en/getting-started/express-setup).
