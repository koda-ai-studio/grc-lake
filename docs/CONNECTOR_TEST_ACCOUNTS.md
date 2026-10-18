# Connector test accounts

Account options checked **2026-10-11**. Availability, eligibility and terms can
change; verify the linked vendor page before signing up. These are proposed
test environments, not additional claims of live connector qualification.

## Start here

Use a dedicated organization test workspace and synthetic users, assets and
records. The best first additions to an existing AWS/Azure/GCP lab are:

| Account                                                                                      | Useful test                                          | Availability and limitation                                                                                                                                            |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Okta Integrator Free](https://developer.okta.com/docs/reference/org-defaults/)              | Identity/MFA collection and System Log replay        | 10 active users; business email required; deactivation after 90 days without sign-in. Check API scopes separately.                                                     |
| [Jira Free](https://www.atlassian.com/software/jira/pricing)                                 | Issue status, ownership and workflow evidence        | Up to 10 users. Free-plan permission and audit-log limitations mean it cannot qualify every governance scenario.                                                       |
| [Snowflake trial](https://docs.snowflake.com/en/user-guide/admin-trial-account)              | Read-only evidence views, schema mapping and exports | Up to 30 days or the usage balance; no payment information required to start. Keep warehouse auto-suspend enabled.                                                     |
| [Databricks express trial](https://docs.databricks.com/aws/en/getting-started/express-setup) | Unity Catalog views and SQL Statement Execution API  | 14-day serverless trial. Our reader needs a service principal, OAuth M2M, a SQL warehouse and SELECT on evidence views. Confirm these before starting the trial clock. |
| [BambooHR developer/test account](https://documentation.bamboohr.com/docs/getting-started)   | Synthetic employment and offboarding records         | Vendor documentation describes a free developer portal and test-account flow. Confirm test-tenant availability and the authentication method supported by our adapter. |

[Databricks Free Edition](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)
is suitable for exploration, but administrative restrictions make its compatibility
with our M2M connector a prerequisite to check, not an assumption. Empty demo
workspaces also need suitable synthetic evidence views before collection is useful.

## Additional coverage

| Option                                                                                   | What it adds                                         | Gate                                                                                                                                                                                  |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [ClickHouse Cloud trial](https://clickhouse.com/pricing)                                 | Managed telemetry-lake reads and sink round trips    | $300 credits over up to 30 days; the pricing page describes a subsequent pay-as-you-go transition. Confirm billing settings. A self-managed ClickHouse test instance is another path. |
| [Intune trial](https://learn.microsoft.com/en-us/intune/fundamentals/free-trial-sign-up) | Device inventory/compliance through Microsoft Graph  | 30 days; use test devices and an isolated tenant or approved test scope. An empty tenant cannot establish device coverage.                                                            |
| [GitLab Free or Ultimate trial](https://about.gitlab.com/solutions/open-source/join/)    | Repository governance, reviews and security findings | API entitlements vary by tier. The OSS program has eligibility conditions; do not assume public source alone qualifies.                                                               |

Local ClickHouse, Kubernetes and file-backed Parquet tests can complement these
accounts. Keycloak can exercise GRC Lake's OIDC sign-in; it does not replace
Okta, Databricks or their evidence APIs.

## Make each account useful

1. Record the intended connector, permitted account/workspace, expiration and
   human reviewer privately. Follow [credential setup](CONNECTOR_CREDENTIALS.md).
2. Create synthetic positive, failing and missing-evidence cases with a separate
   setup identity. Give the GRC Lake collector read-only access and store only
   approved secret references in its configuration.
3. Test probe → sync → normalize → evaluate → console investigation → MCP/API
   read → export. Compare identities, counts, completeness and frozen results.
4. Test expired/denied access, pagination and replay without altering production
   permissions. Check that unavailable evidence never becomes a pass.
5. Publish sanitized scope and results, keep raw receipts private, and revoke
   disposable access when complete. Update [current state](CURRENT_STATE.md)
   and the [roadmap](../ROADMAP.md) only to the extent established by those checks.

Account creation is not evidence of integration success. Provider setup may
need administrative consent or vendor approval; do not enable paid services,
bulk email/phishing campaigns or real employee/device enrollment for a demo.
