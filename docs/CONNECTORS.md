# Connector And Access Model

Already have an Agent-Bom scan? [Import its JSON report](AGENT_BOM_IMPORT.md)
through the current-source CLI with explicit tenant scope and optional control
bindings. This offline evidence path does not add a qualified live connector.

GRC Lake should collect evidence with the smallest viable access boundary.

For ingestion idempotency, unique event IDs, headless/agent vs console surfaces,
and security-finding flow, see
[INGESTION_CONNECTORS_IDEMPOTENCY.md](INGESTION_CONNECTORS_IDEMPOTENCY.md).

## Default path (most teams)

**No customer security data lake required.** Connect read-only to source systems
(GitHub, AWS, Okta, …), sync evidence into GRC Lake's assessment store, then run
control evaluation:

```text
discover scope → probe → enable → sync → eval
```

This is the same agentless model as typical GRC SaaS — scoped tokens and
read-only roles, not agents or broad cloud admin. GRC Lake keeps the assessment
store in storage you operate: a filesystem lake or PostgreSQL plus S3-compatible
object storage in distributed mode. Hosting can be on-premises or in the cloud.
The [deployment and lake compatibility matrix](DEPLOYMENT.md#deployment-and-lake-compatibility)
separates application storage from source readers and optional exports.

Headless setup (curl, CLI, MCP): [playbooks/HEADLESS_CONNECTOR_SETUP.md](playbooks/HEADLESS_CONNECTOR_SETUP.md).

## Connection hub: the next evidence step

The console's **Connections** page separates enabled sources from sources with
recent evidence. Each source names its next step: configure access, enable,
collect, review a failed or empty collection, refresh stale evidence, or inspect
the collected rows. The first action opens that source's existing configuration
and run history; it does not start a collection automatically.

A successful probe is not evidence collection. Configuration-only and skipped
probes are labelled separately from live read-access checks. A failed latest
sync stays visible even when older evidence is still fresh. Zero-row syncs,
unknown counts, and invalid timestamps do not count as recent evidence.

These counters describe recorded collection activity, including demo sources.
They do not prove provider qualification or framework coverage. Run control
evaluation and inspect its evidence before making an assessment claim.

## Access modes (pick one)

| Mode                             | When to use                                                            | Boundary                          |
| -------------------------------- | ---------------------------------------------------------------------- | --------------------------------- |
| **Direct tool API read**         | **Default** — no existing evidence lake                                | scoped token or app installation  |
| Existing security data lake read | You already run a lake or SIEM export ([BYOL](BRING_YOUR_OWN_LAKE.md)) | read-only role                    |
| Managed evidence objects         | Local proof, starter deployments, demos                                | dedicated schema/output directory |

Avoid broad cloud permissions. Connectors should not need admin, delete, owner,
or unrestricted write access to evaluate posture.

## Example existing-lake readers

| Store      | Role                                                | Connector                   |
| ---------- | --------------------------------------------------- | --------------------------- |
| Snowflake  | governed evidence, audit views, retention, RBAC     | `snowflake-evidence-lake`   |
| ClickHouse | telemetry, runtime events, trends, fast aggregation | `clickhouse-telemetry-lake` |

## Catalog

The connector catalog is versioned in:

```text
connectors/catalog.json
```

Validate it with:

```bash
grc-lake connectors validate
```

Each catalog entry also carries **UX metadata** consumed by the console and demo kit:

| Field         | Purpose                                                                        |
| ------------- | ------------------------------------------------------------------------------ |
| `vendor`      | Short vendor label (AWS, GitHub, Snowflake, …)                                 |
| `description` | What evidence the connector ingests                                            |
| `setup_hint`  | Read-only connection guidance shown in `/connectors` and account-linking cards |

`release_stage` is optional: `"preview"` marks an implemented connector that has not
been verified against a live tenant (the console shows a Preview badge); absent or
`"ga"` is the legacy standard release-stage label. It does not prove a successful live run against your provider, permission set, or data shape. Committed fixtures and local tests establish bounded adapter behavior; validate a read-only live collection before relying on its results. `grc-lake connectors validate` rejects any
other value.

Connection field definitions live in `app/web/src/lib/connector-forms.ts`; vendor
marks use registered assets in `app/web/src/lib/connector-brand-logos.ts` with
text fallbacks in `connector-visuals.ts`. See
[Third-Party Asset Policy](THIRD_PARTY_ASSETS.md) for sources and usage terms.

For live Azure, AWS, or Snowflake trials, use the least-privilege runbook in
[`docs/LIVE_CLOUD_POC.md`](LIVE_CLOUD_POC.md). It keeps first-run access
read-only and avoids passwords, human-scoped developer tokens, root keys, and
broad cloud credentials.

For production operation, use
[`docs/CONTINUOUS_INGESTION.md`](CONTINUOUS_INGESTION.md). It describes the
customer-owned identity boundary, probe-gated enablement, scheduler loop,
idempotent raw upserts, API limits, error behavior, and snapshot integrity.

List configured connector contracts:

```bash
grc-lake connectors list
```

## Connector Runner

The catalog contains **31 catalog contracts**: **28 executable adapters** and
3 configuration/access boundaries. Adapters include direct source/API collectors,
existing-lake readers and incremental event-log readers. Boundaries describe
read-only access or managed evidence; they have no standalone sync adapter.

Adapters marked **Preview** carry `"release_stage": "preview"` in the catalog
and a Preview badge in the console. Preview means qualification is limited; it
does not necessarily mean no live run has occurred. Inspect the
[qualification matrix](CONNECTOR_QUALIFICATION.md) for each adapter's offline
tests, bounded live receipts and remaining gaps. Neither a successful probe nor
a bounded live receipt establishes complete provider coverage.

In hosted server mode, secret references must use the tenant's
`GRC_LAKE_TENANT_<TENANT_ID>__` prefix or the operator's
`GRC_LAKE_CONNECTOR_SECRET_REFS` allowlist, and cloud readers need delegated
access (AWS role plus external ID, GCP `impersonate_service_account`, the
customer's own Entra app registration for Azure and Intune, a tenant
kubeconfig). See [Hosted connector credentials](SERVER_AUTH.md#hosted-connector-credentials).

| Connector ID                | Source                  | Runner status                           |
| --------------------------- | ----------------------- | --------------------------------------- |
| `github-security`           | GitHub repo security    | executable                              |
| `gitlab-security`           | GitLab repo security    | executable                              |
| `aws-posture`               | AWS IAM/posture         | executable                              |
| `okta-identity`             | Okta identity/MFA       | executable                              |
| `google-workspace-identity` | Google Workspace users  | executable                              |
| `gcp-posture`               | GCP IAM/posture         | executable                              |
| `azure-posture`             | Azure IAM/posture       | executable                              |
| `jira-ticketing`            | Jira tickets/workflows  | executable                              |
| `intune-devices`            | Intune device posture   | executable                              |
| `bamboohr-personnel`        | BambooHR employment     | executable                              |
| `rippling-personnel`        | Rippling employment     | executable                              |
| `workday-personnel`         | Workday employment      | executable (RaaS report)                |
| `databricks-evidence-lake`  | Databricks UC evidence  | executable existing-lake read (preview) |
| `jamf-devices`              | Jamf Pro device posture | executable (preview)                    |
| `crowdstrike-falcon`        | CrowdStrike Falcon EDR  | executable (preview)                    |
| `snyk-vulnerabilities`      | Snyk vulnerabilities    | executable (preview)                    |
| `kubernetes-cluster`        | Kubernetes config       | executable (preview)                    |
| `training-completion`       | LMS training export     | executable file read (preview)          |
| `snowflake-evidence-lake`   | governed evidence lake  | executable existing-lake read           |
| `clickhouse-telemetry-lake` | telemetry analytics     | executable existing-lake read           |
| `iceberg-parquet-lake`      | Iceberg / Parquet lake  | executable existing-lake read (preview) |
| `bigquery-evidence-lake`    | BigQuery evidence       | executable existing-lake read (preview) |
| `object-storage-evidence`   | object evidence store   | executable existing-lake read           |
| `okta-system-log`           | Okta System Log API     | **implemented** (incremental)           |
| `siem-alerts`               | SIEM/detection exports  | executable existing-lake read           |
| `runtime-gateway`           | runtime policy events   | executable existing-lake read           |
| `identity-provider`         | generic identity source | **contract only** (no sync)             |
| `ticketing`                 | generic ticketing       | **contract only** (no sync)             |
| `managed-local-evidence`    | local starter evidence  | managed evidence object                 |

Every executable runner writes valid raw evidence into:

```text
<lake>/raw/connector_events.jsonl
```

The production lifecycle is intentionally the same for UI, API, CLI, scheduler,
and agents:

1. create a scoped source role, app, or service identity,
2. discover the read scope visible to that identity,
3. probe the exact credential reference and scope,
4. enable only after the probe succeeds,
5. sync manually or by schedule.

### Optional AWS role policy evidence

Enable **Collect IAM role policies** in AWS Posture's Config tab, or configure
`options.include_role_policies: true`. It defaults to false. For the additional
read grants, deploy the CloudFormation role with `IncludeRolePolicies=true` or
set Terraform `include_role_policies = true`. The six actions are `iam:ListRoles`,
`iam:ListAttachedRolePolicies`, `iam:ListRolePolicies`, `iam:GetPolicy`,
`iam:GetPolicyVersion`, and `iam:GetRolePolicy`.

GRC Lake directly adapts Agent-Bom's managed/inline policy reads and policy
normalization at revision `95bc4a9c8e50d4bfbce59b91db8f68429cfbf9e5` (see
[NOTICE](../NOTICE)); no Agent-Bom installation or report is required.
The AWS client uses the existing delegated session and verified account.
[Managed policy versions](https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetPolicyVersion.html)
and [inline role policies](https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRolePolicy.html)
produce one `aws.iam.role_policies` observation per role, scoped by its ARN.

Evidence retains explicit denies, Action/NotAction, Resource/NotResource, and
conditions. `policy_coverage` describes the collected identity policies only.
A successful empty policy list is complete; failed lists/reads and malformed
policies emit collection gaps. Other roles and existing user posture continue.
The observation has no mapped controls or authorization verdict. Trust policies,
permissions boundaries, resource policies, SCPs, effective permissions, and usage
are outside this collection. No Access Advisor jobs are started.

Offline fixtures `roles.json` and `role_policies.json` exercise persistence,
replay, scope boundaries, and safe failures. They do not establish credentialed
AWS qualification.

### AWS multi-account scale

AWS posture uses the same third-party role pattern for one account or hundreds:

| Item          | Scaling rule                                                                                                                            |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Rollout       | Use **CloudFormation StackSets** or **Terraform workspaces** to deploy the same read-only role across target AWS accounts.              |
| Authorization | The deployed role trusts the GRC Lake runtime principal and constrains access with External ID.                                         |
| External ID   | Use **one External ID per deployed role**; GRC Lake includes that exact value in STS AssumeRole.                                        |
| Confirmation  | Default role names can be confirmed by AWS account ID; custom role names use the Role ARN output.                                       |
| Scale surface | **Bulk account import** is the follow-up console/API surface for registering many deployed roles after rollout.                         |
| Sync          | The scheduled sync assumes each registered role, receives short-lived session credentials, and reads only the granted IAM posture APIs. |
| Evaluation    | Raw evidence keeps the AWS account ID attached; deterministic controls evaluate across the combined evidence set.                       |

<p align="center">
  <img src="images/grc-lake-readonly-connections.svg" alt="Read-only connector model: AWS IAM role, GitHub App, Okta token, Snowflake SELECT into GRC Lake ingestion" width="100%">
</p>

Mermaid diagrams: [connector-ingestion.md](diagrams/connector-ingestion.md)

Do not paste passwords, human-scoped developer tokens, root keys, or private
keys into GRC Lake. Use SSO, an assumable role, OAuth, key-pair auth, or a
secret-manager reference. GRC Lake records a non-secret fingerprint so a later
enable action must match the probed access payload.

Probe and enable a fixture-backed GitHub connector:

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id github-security \
  --credentials-json '{"token":"fixture-read-token"}' \
  --options-json '{"org":"acme"}'

grc-lake connectors configure \
  --lake build/lakehouse \
  --connector-id github-security \
  --state enabled \
  --credentials-json '{"token":"fixture-read-token"}' \
  --options-json '{"org":"acme"}'

grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id github-security \
  --repo OWNER/REPO \
  --fixture-dir tests/fixtures/github-governance
```

For live GitHub collection, use a GitHub App installation token from the
selected environment variable or secret manager. The configure payload should
store the reference name, not the raw token:

```bash
export GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN=...  # from your secret manager
grc-lake connectors probe --lake ./lake --connector-id github-security \
  --credentials-json '{"credential_ref":"GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN"}' \
  --options-json '{"org":"OWNER","repo":"OWNER/REPO"}'
grc-lake connectors configure --lake ./lake --connector-id github-security --state enabled \
  --credentials-json '{"credential_ref":"GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN"}' \
  --options-json '{"org":"OWNER","repo":"OWNER/REPO"}'
grc-lake connectors sync --lake ./lake --connector-id github-security --repo OWNER/REPO
```

The minimum GitHub App repository permissions are:

| Permission                   | Access unlocked                                                            |
| ---------------------------- | -------------------------------------------------------------------------- |
| Metadata: read               | Repository identity, visibility, and default branch                        |
| Administration: read         | Branch protection, collaborators, teams, and Actions workflow defaults     |
| Code scanning alerts: read   | Aggregate code-scanning counts by state and severity                       |
| Secret scanning alerts: read | Aggregate secret-scanning counts by state; alert details are not persisted |
| Dependabot alerts: read      | Aggregate dependency-alert counts by state and severity                    |

GRC Lake paginates collaborators, teams and each alert category at 100 records
per page. It fails the sync if a list does not end within 1,000 pages, repeats a
page, or contains malformed items. Exhausted transient HTTP failures also fail
the sync. A 401/403/404 remains an explicitly unavailable signal; inspect those
gaps before using the evidence. Alert evidence contains aggregate counts only;
alert details, secret material and tokens are not persisted. The GitHub probe
resolves the token the way sync does (`credential_ref`, then
`options.token_env`, then `GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN`; a literal
`token` is never used), reads the repository metadata, and makes one request to
each alert endpoint. It reports each signal as `readable`, `forbidden` or
`not_enabled`. An unreadable repository or any other HTTP failure fails the
probe, as it would fail the sync. A green probe still does not establish
collection completeness.
See the [GitHub qualification contract](GITHUB_QUALIFICATION.md) and
[catalog-wide qualification matrix](CONNECTOR_QUALIFICATION.md).

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id github-security \
  --credentials-json '{"credential_ref":"GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN"}' \
  --options-json '{"repo":"OWNER/REPO"}'

grc-lake connectors configure \
  --lake build/lakehouse \
  --connector-id github-security \
  --state enabled \
  --credentials-json '{"credential_ref":"GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN"}' \
  --options-json '{"repo":"OWNER/REPO"}'

GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN=... grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id github-security \
  --repo OWNER/REPO
```

GitLab governance sync (fixture-backed or live token):

```bash
grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id gitlab-security \
  --repo GROUP/PROJECT \
  --fixture-dir tests/fixtures/gitlab-governance

GRC_LAKE_GITLAB_ACCESS_TOKEN=... grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id gitlab-security \
  --repo GROUP/PROJECT
```

Self-managed GitLab: set `GRC_LAKE_GITLAB_API_URL` to your instance API base
(for example `https://gitlab.example.com/api/v4`) before sync.

Snowflake is the read-existing-lake path. The fixture path mirrors the expected
views (`audit_events`, `control_posture`, `asset_risk`, and
`evidence_bundles`) and exercises the same raw-to-gold pipeline:

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id snowflake-evidence-lake \
  --credentials-json '{"account":"fixture","user":"grc-lake_reader","credential_ref":"fixture-sso"}' \
  --options-json '{"warehouse":"GRC_LAKE_READ_WH","database":"GRC_LAKE_SECURITY_LAKE","schema":"EVIDENCE","audit_events":"GRC_LAKE_AUDIT_EVENTS","control_posture":"GRC_LAKE_CONTROL_POSTURE","asset_risk":"GRC_LAKE_ASSET_RISK","evidence_bundles":"GRC_LAKE_EVIDENCE_BUNDLES"}'

grc-lake connectors configure \
  --lake build/lakehouse \
  --connector-id snowflake-evidence-lake \
  --state enabled \
  --credentials-json '{"account":"fixture","user":"grc-lake_reader","credential_ref":"fixture-sso"}' \
  --options-json '{"warehouse":"GRC_LAKE_READ_WH","database":"GRC_LAKE_SECURITY_LAKE","schema":"EVIDENCE","audit_events":"GRC_LAKE_AUDIT_EVENTS","control_posture":"GRC_LAKE_CONTROL_POSTURE","asset_risk":"GRC_LAKE_ASSET_RISK","evidence_bundles":"GRC_LAKE_EVIDENCE_BUNDLES"}'

grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id snowflake-evidence-lake \
  --fixture-dir tests/fixtures/snowflake
```

ClickHouse is the high-velocity telemetry lake reader. The fixture path mirrors
`security.normalized_events` from `deploy/clickhouse/schema.sql` and uses
append-mode ingestion with a high-water cursor:

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id clickhouse-telemetry-lake \
  --credentials-json '{"host":"https://cluster.example.clickhouse.cloud:8443","user":"grc-lake_reader","credential_ref":"GRC_LAKE_CLICKHOUSE_TOKEN"}' \
  --options-json '{"database":"security","table":"normalized_events"}'

grc-lake connectors configure \
  --lake build/lakehouse \
  --connector-id clickhouse-telemetry-lake \
  --state enabled \
  --credentials-json '{"host":"https://cluster.example.clickhouse.cloud:8443","user":"grc-lake_reader","credential_ref":"GRC_LAKE_CLICKHOUSE_TOKEN"}' \
  --options-json '{"database":"security","table":"normalized_events"}'

grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id clickhouse-telemetry-lake \
  --fixture-dir tests/fixtures/clickhouse-telemetry-lake
```

For live ClickHouse collection, point the connector at your cluster HTTP endpoint
and mount the read-only token via `GRC_LAKE_CLICKHOUSE_TOKEN` (or the
`credential_ref` you configured). GRC Lake only issues `SELECT` reads against
the discovered table, keyset-paginated on the composite `(event_time, event_id)`
cursor with `LIMIT` so a large table streams in bounded pages instead of one
unbounded response; rows sharing an `event_time` across a page boundary are never
dropped, and the append-mode merge dedups by `event_id` as a second safety net.

### Alert- and event-export pagination (SIEM, runtime-gateway)

The `siem-alerts` and `runtime-gateway` readers pull an incremental window with a
watermark cursor (`?since=`) and follow server-side pagination within that window:
when a response is a JSON object carrying a `next_cursor` string, GRC Lake requests
the next page with `?cursor=<token>` and repeats until `next_cursor` is absent. An
export that returns a bare JSON array (or an object without `next_cursor`) is read
as a single page, so a non-paginating endpoint still works unchanged.

For live Snowflake collection, install the cloud connector extra and use the
fixed POC objects from [`docs/LIVE_CLOUD_POC.md`](LIVE_CLOUD_POC.md):
`GRC_LAKE_SECURITY_LAKE.EVIDENCE`, `GRC_LAKE_READ_WH`, and `GRC_LAKE_READER`.
For a human POC, use browser SSO. This is not the scheduled-ingestion path.
GRC Lake only issues `SELECT * FROM <view>` reads:

```bash
uv pip install -e ".[cloud]"

SNOWFLAKE_ACCOUNT="$SNOWFLAKE_ACCOUNT" \
SNOWFLAKE_USER="$SNOWFLAKE_USER" \
SNOWFLAKE_AUTHENTICATOR=externalbrowser \
SNOWFLAKE_ROLE=GRC_LAKE_READER \
SNOWFLAKE_WAREHOUSE=GRC_LAKE_READ_WH \
SNOWFLAKE_DATABASE=GRC_LAKE_SECURITY_LAKE \
SNOWFLAKE_SCHEMA=EVIDENCE \
grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id snowflake-evidence-lake
```

Headless jobs should use a non-human service user such as
`GRC_LAKE_INGEST_SVC`, with only `GRC_LAKE_READER` and warehouse `USAGE`.
Snowflake key-pair auth uses a mounted private-key file path, not raw key
contents in connector config:

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id snowflake-evidence-lake \
  --credentials-json '{"account":"'"$SNOWFLAKE_ACCOUNT"'","user":"GRC_LAKE_INGEST_SVC","private_key_ref":"SNOWFLAKE_PRIVATE_KEY_FILE"}' \
  --options-json '{"warehouse":"GRC_LAKE_READ_WH","database":"GRC_LAKE_SECURITY_LAKE","schema":"EVIDENCE","role":"GRC_LAKE_READER","audit_events":"GRC_LAKE_AUDIT_EVENTS","control_posture":"GRC_LAKE_CONTROL_POSTURE","asset_risk":"GRC_LAKE_ASSET_RISK","evidence_bundles":"GRC_LAKE_EVIDENCE_BUNDLES"}'

SNOWFLAKE_ACCOUNT="$SNOWFLAKE_ACCOUNT" \
SNOWFLAKE_USER=GRC_LAKE_INGEST_SVC \
SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT \
SNOWFLAKE_PRIVATE_KEY_FILE="$SNOWFLAKE_PRIVATE_KEY_FILE" \
SNOWFLAKE_ROLE=GRC_LAKE_READER \
SNOWFLAKE_WAREHOUSE=GRC_LAKE_READ_WH \
SNOWFLAKE_DATABASE=GRC_LAKE_SECURITY_LAKE \
SNOWFLAKE_SCHEMA=EVIDENCE \
grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id snowflake-evidence-lake
```

OAuth is also supported when the customer's runtime has a governed token broker:
set `SNOWFLAKE_AUTHENTICATOR=oauth` and inject `SNOWFLAKE_OAUTH_TOKEN` from the
secret manager at process start. The raw value is not written into the lake.

Object storage evidence uses read-only LIST against an S3 prefix and syncs in
**snapshot** mode so removed objects disappear from the lake on the next pull:

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id object-storage-evidence \
  --credentials-json '{"role_arn":"arn:aws:iam::123456789012:role/GrcLakeEvidenceRead"}' \
  --options-json '{"bucket":"grc-lake-evidence","prefix":"bundles/"}'

grc-lake connectors configure \
  --lake build/lakehouse \
  --connector-id object-storage-evidence \
  --state enabled \
  --credentials-json '{"role_arn":"arn:aws:iam::123456789012:role/GrcLakeEvidenceRead"}' \
  --options-json '{"bucket":"grc-lake-evidence","prefix":"bundles/"}'

grc-lake connectors sync \
  --lake build/lakehouse \
  --connector-id object-storage-evidence \
  --fixture-dir tests/fixtures/object-storage-evidence
```

By default the runner rebuilds bronze, silver, gold, marts, and current posture
from the managed raw connector file. Use `--no-materialize` when you only want
to collect raw evidence. Every sync attempt is recorded in
`gold/connector_runs.jsonl`.

## Scheduled Sync

Manual sync proves the connector. Scheduled sync makes the connector part of
continuous posture.

Persist scheduler options on the connector configuration:

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id github-security \
  --credentials-json '{"credential_ref":"GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN"}' \
  --options-json '{"repo":"OWNER/REPO"}'

grc-lake connectors configure \
  --lake build/lakehouse \
  --connector-id github-security \
  --state enabled \
  --credentials-json '{"credential_ref":"GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN"}' \
  --options-json '{"repo":"OWNER/REPO"}' \
  --sync-schedule "every 15m" \
  --repo OWNER/REPO
```

Run the scheduler from cron, Kubernetes `CronJob`, or the local daemon:

```bash
grc-lake scheduler tick --lake build/lakehouse
grc-lake scheduler run --lake build/lakehouse --tick-seconds 60
```

Supported schedule expressions are intentionally small and portable:
`@hourly`, `@daily`, `every Nm`, and `every Nh`. The scheduler records last
fire time in `gold/scheduler_state.jsonl`, writes sync history to
`gold/connector_runs.jsonl`, and uses the same connector runner as
`connectors sync`; it does not use a separate evidence path.

Repository evidence has two concrete collection paths:

```bash
grc-lake repo audit https://github.com/OWNER/REPO --out build/repo-audit.jsonl
GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN=... grc-lake repo governance-sync OWNER/REPO --out build/repo-governance.jsonl
```

In the console, **Onboarding → Start with a public repository** accepts a public
GitHub.com URL. Collection requires `connector_manage` permission, runs as a durable
operation, and publishes through the same assessment pipeline. The result shows
its commit, ref, observation ID and time, with a direct link to the scoped evidence
investigation. Public observations do not establish branch protection, private
alerts or organization policy; authenticated governance remains a separate setup.

The shared CLI/console collector resolves the default branch once to a commit SHA
and reads its tree and file samples at that revision. Metadata and language totals
are observations at collection time, not historical facts pinned by the commit.
Requests use the shared public-address transport with GitHub host and repository
checks on redirects. Reads are limited to 32 top-level requests, a 120-second
collection budget (20 seconds per request), 6 MiB per JSON response, and 200,000
bytes per file sample. Redirects also retain the transport's bounded hop count.
An oversized/truncated tree fails collection; a large source file contributes only
a labelled prefix hash, never its contents or a purported full-file hash. No clone,
package installation or repository code execution occurs.

The API is `POST /api/v1/repositories/public-audit` with `{"repo":"https://github.com/OWNER/REPO"}`.
Use `Prefer: respond-async` and an `Idempotency-Key` for durable acceptance/replay;
provider rate limits and unavailable sources return explicit failures. The console
uses this asynchronous path. It does not accept tokens, tenant IDs or local fixture
paths. Fixture-backed CLI observations are marked synthetic and require a
`commit.json` containing the commit SHA and `commit.tree.sha`, plus the matching
`sha` in `tree.json`.

New GitHub observations normalize owner/repository case and use `github:<owner>`
as their source-account identity in both public audit and governance collection.
This is separate from the authenticated platform tenant. Existing retained
observations keep their original `public` or `customer-managed` identity; no
historical provenance or record bindings are rewritten. Recollect both paths to
use the canonical identity for new observations.

The public audit path requires no credentials. The governance sync path uses a
GitHub App installation token or fixture bundle for private branch rules,
collaborators, teams, workflow permissions, and security-setting summaries.

The validator rejects:

- missing collection mode, access boundary, route, permissions, or freshness SLO
- existing-lake connectors that are not read-only
- direct API connectors that are not scoped-token based
- managed evidence mode without a dedicated schema/boundary
- secret-like field names or token-shaped values in the catalog
- broad permission words such as admin, delete, drop, modify, owner, or root

## Ingestion strategy (velocity + cost)

A compliance data layer that claims _real-time control health_ must justify
**how** each source is ingested, because streaming is not free. Every connector
declares three attributes that drive an auditable ingestion decision (encoded in
`src/security_lakehouse/ingestion/strategy.py`, not prose):

- `velocity`: `high_event_stream` · `medium_api` · `low_current_state`
- `native_connector`: whether a managed/native ingestion connector exists for the source
- `data_shape`: `event_log` · `current_state`

| Velocity            | Native? | Method                                       | Why                                                                                                                                                                                                       |
| ------------------- | ------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `high_event_stream` | any     | **Snowpipe Streaming**                       | Seconds-fresh, serverless, no warehouse COPY; ~50% cheaper than file Snowpipe at high throughput (unified ~0.0037 credits/GB). INSERT-only — upserts handled downstream via Streams/Tasks/Dynamic Tables. |
| `medium_api`        | true    | **Managed/native connector** (e.g. Openflow) | Managed runtime, less code, vendor-managed auth, built-in observability.                                                                                                                                  |
| `medium_api`        | false   | **Committed custom pull**                    | No native connector: watermark + cursor pagination + 429 backoff + idempotent merge.                                                                                                                      |
| `low_current_state` | any     | **Scheduled pull** (hourly/daily)            | Slow churn; streaming would add producer cost + ops for zero freshness benefit the control needs.                                                                                                         |

**Cost discipline:** streaming bills per client-runtime-hour + per-GB and you own
the producer. The strategy makes `high_event_stream` the _only_ path to streaming,
so it is chosen only when a control's `freshness_slo` actually requires sub-minute
data — never claimed where a native connector does not exist.

Inspect the resolved plan per source (a live demo command):

```bash
grc-lake ingestion plan        # table: velocity → method → SLO + cost note
grc-lake ingestion plan --json  # machine-readable
```

## Okta: two velocities, not one

A common misread is "Okta is high-volume, so stream it." Okta actually exposes
**two sources at very different velocities**, and most access _controls_ read the
slow one:

| Source            | data_shape      | velocity            | freshness | ingestion                                                              | feeds                                              |
| ----------------- | --------------- | ------------------- | --------- | ---------------------------------------------------------------------- | -------------------------------------------------- |
| `okta-identity`   | `current_state` | `low_current_state` | 1h        | scheduled pull                                                         | MFA-coverage, orphaned/terminated-account controls |
| `okta-system-log` | `event_log`     | `medium_api`        | 15m       | **implemented** — incremental pull with watermark cursor + 429 backoff | failed-login / auth-anomaly controls (e.g. AC-7)   |

The current-state source (users, factors, policies) changes slowly, so an hourly
scheduled pull is correct and cheapest. The System Log is event-shaped and needs
~15-minute freshness for failed-login controls; it is pulled incrementally with a
high-water cursor (`gold/watermarks.jsonl`) rather than streamed, because the
Okta System Log is a polled API. Modeling them separately keeps each control on
the right freshness/cost path instead of over-provisioning the whole connector to
the strictest SLO.

### Optional non-human identity metadata

Enable **Collect non-human identities** in the Okta Identity drawer to include
OAuth service applications and API-token metadata. It is off by default and
leaves the existing user/MFA/policy collection unchanged. The equivalent CLI
configuration is:

```bash
grc-lake connectors probe --lake ./lake --connector-id okta-identity \
  --credentials-json '{"org_url":"https://your-org.okta.com","credential_ref":"GRC_LAKE_OKTA_TOKEN"}' \
  --options-json '{"include_non_human_identities":true}'
grc-lake connectors configure --lake ./lake --connector-id okta-identity \
  --state enabled \
  --credentials-json '{"org_url":"https://your-org.okta.com","credential_ref":"GRC_LAKE_OKTA_TOKEN"}' \
  --options-json '{"include_non_human_identities":true}'
grc-lake connectors sync --lake ./lake --connector-id okta-identity
```

Supply the API token through the named environment variable or your existing
secret-reference policy. The additional reads are `GET /api/v1/apps` and
`GET /api/v1/api-tokens`, including pagination. They require application and
API-token read authority (`okta.apps.read` and `okta.apiTokens.read` in Okta's
[scope catalog](https://developer.okta.com/docs/api/oauth2)); an SSWS API token
inherits its administrator's authority and is not itself OAuth-scoped.
No write endpoints or credential-value endpoints are called.
Configuration/contract-only probes do not establish provider access; inspect
the first sync and any coverage gaps.

The collector retains identity IDs, labels, owner references, lifecycle and
creation/expiry metadata, and service-app authentication/grant settings. Human
SSO applications are excluded. Client secrets and token values are excluded;
grant types are not treated as permissions, `lastUpdated` is not last use, and
uncollected scopes remain explicitly unknown. The additional rows are scoped
observations with no automatic control bindings or passing-control claims.
Denied or malformed sub-collections produce visible coverage gaps while other
readable evidence is retained.

Filtering and metadata validation reuse the tested implementation from
[Agent-Bom at revision 95bc4a9](https://github.com/koda-ai-studio/agent-bom/blob/95bc4a9c8e50d4bfbce59b91db8f68429cfbf9e5/src/agent_bom/identity/okta_nhi.py),
adapted to GRC Lake's evidence contract. The products remain independent;
GRC Lake does not install or invoke Agent-Bom. Fixture tests demonstrate this
path locally; they do not establish credentialed provider qualification.

## GCP: optional service-account inventory

On an existing GCP connection, open **Config** and enable **Collect service
accounts** under **Schedule and scope**, then test and save the changed options.
The option is off by default; user-facing posture collection keeps its existing
permission requirements. The equivalent option is
`{"include_non_human_identities":true}` in the CLI/API `options` object.

Install `grc-lake[cloud]` for live collection; it includes `google-cloud-iam`.
The additional read uses the IAM API (`iam.googleapis.com`) and requires
[`iam.serviceAccounts.list`](https://docs.cloud.google.com/iam/docs/reference/rest/v1/projects.serviceAccounts/list)
on the configured project. The existing GCP probe verifies project IAM-policy
access; it does not establish access to this optional listing. Inspect the first
sync and its coverage gaps. GRC uses the same delegated service-account
credential as the rest of the connector, with bounded pagination.

The inventory projection and member-to-role joins are adapted from
[Agent-Bom's GCP inventory](https://github.com/koda-ai-studio/agent-bom/blob/95bc4a9c8e50d4bfbce59b91db8f68429cfbf9e5/src/agent_bom/cloud/gcp_inv/iam.py).
Records retain the provider's unique ID (falling back to email), display name,
email, and observed enabled/disabled state. Project-role bindings retain their
conditions. They are not effective-permission decisions, and do not include
inherited policies. An unavailable project policy is explicitly unknown.
Keys, last-use telemetry, and effective permissions are not collected.

Denied, unavailable, or malformed inventory produces a coverage gap while
existing readable posture evidence is retained. The extra records are
observations without automatic control bindings or passing-control claims.
The fixture `tests/fixtures/gcp/service_accounts.json` exercises this path
offline; it does not establish live-provider qualification. Agent-Bom remains
an independent product and is not installed or invoked by GRC Lake.

## Microsoft Entra identity metadata (preview)

`entra-identity` reads service principals of type `Application` or
`ManagedIdentity`, joins their backing application registrations by `appId`,
and records unmatched registrations with credential metadata. The filtering
and join logic is adapted from
[Agent-Bom's Entra collector](https://github.com/koda-ai-studio/agent-bom/blob/95bc4a9c8e50d4bfbce59b91db8f68429cfbf9e5/src/agent_bom/identity/entra_nhi.py).
GRC Lake uses its own evidence records and shared Microsoft Graph transport;
it does not install or invoke Agent-Bom.

Create a connection using the **Microsoft Entra Identities** drawer. Grant
your app registration Microsoft Graph **Application.Read.All** with admin
consent, then enter the Entra tenant ID, client ID, and one secret, certificate,
or federated-token-file reference. These are directory permissions; Azure
subscription Reader access does not provide them. The selected permission is
the least privileged application permission documented for listing
[service principals](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list?view=graph-rest-1.0)
and [applications](https://learn.microsoft.com/en-us/graph/api/application-list?view=graph-rest-1.0).

Only `GET /v1.0/servicePrincipals` and `GET /v1.0/applications` are used, with
selected identity/credential-metadata fields and bounded Graph pagination.
No credential-management endpoints are called. Evidence retains identity IDs,
type, display name, lifecycle state where observed, and the earliest credential
expiry. Credential values, certificate material, and arbitrary provider fields
are excluded from stored evidence. Invalid or missing expiry metadata remains
unknown; timestamps are compared as UTC instants.

Denied or malformed listings produce coverage gaps. Readable identities remain
available, but an unavailable join does not establish that an app is orphaned
or that a principal has no backing registration. Owners, effective permissions,
and last use are not collected. These observations have no automatic control
bindings or passing-control claims.

Hosted collection requires the tenant's app registration and refuses ambient
server credentials. Local collection may use `DefaultAzureCredential`, scoped
to the configured tenant. Configuration-only probes do not establish live
Graph access; inspect the first sync and its coverage gaps.

For a reproducible offline example:

```bash
grc-lake connectors probe --lake ./lake --connector-id entra-identity \
  --credentials-json '{"tenant_id":"22222222-2222-2222-2222-222222222222"}'
grc-lake connectors configure --lake ./lake --connector-id entra-identity \
  --state enabled \
  --credentials-json '{"tenant_id":"22222222-2222-2222-2222-222222222222"}'
grc-lake connectors sync --lake ./lake --connector-id entra-identity \
  --fixture-dir tests/fixtures/entra
```

The fixture path is for a source checkout and all example identities are synthetic. Fixture and fake-client tests establish local
contract behavior, not credentialed provider qualification. The connector stays
in preview pending that qualification.

## Google Workspace: two credential shapes

`google-workspace-identity` accepts either an already-minted access token or the
OAuth material to mint tokens itself. Pick one:

| Shape               | Credentials                                             | When                                                                     |
| ------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------ |
| Static access token | `credential_ref`                                        | Your secret manager already rotates a short-lived Directory access token |
| Unattended refresh  | `refresh_token_ref` + `client_id` + `client_secret_ref` | Scheduled sync with nothing external minting tokens                      |

Both need `customer_id`. The `*_ref` fields name environment variables, never raw
secrets; a `<NAME>_FILE` variant is preferred over the inline value when both are
present. With the refresh shape, GRC Lake exchanges the refresh token at
`oauth2.googleapis.com/token` on first use, near expiry (300s skew), or once on a
401, and the resolved access token stays in memory only.

```bash
grc-lake connectors probe \
  --lake build/lakehouse \
  --connector-id google-workspace-identity \
  --credentials-json '{"customer_id":"C01234567","refresh_token_ref":"GOOGLE_WORKSPACE_REFRESH_TOKEN","client_id":"123-abc.apps.googleusercontent.com","client_secret_ref":"GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET"}'
```

Supplying part of the refresh triple is rejected at probe and enable time with the
specific missing fields, because a partial triple silently falls back to the
static-token path at sync time.

## Microsoft Intune: device posture

`intune-devices` reads `GET /v1.0/deviceManagement/managedDevices` from Microsoft
Graph and emits two current-state events per managed device:

| Event                      | Pass when                                           | Controls                                               |
| -------------------------- | --------------------------------------------------- | ------------------------------------------------------ |
| `intune.device.encryption` | `isEncrypted` is true                               | FEDRAMP-AC-19.5, CMMC-3.1.19, ISO27001-A.8.1           |
| `intune.device.compliance` | `complianceState` is `compliant` and not jailbroken | FEDRAMP-AC-19, CMMC-3.1.18, SOC2-CC6.8, ISO27001-A.8.1 |

`noncompliant`, `conflict`, `error`, or a jailbroken/rooted device is a high-severity
open finding; `inGracePeriod` is low; `unknown` and `configManager` are medium,
because Intune has no verdict to rely on.

**Identity.** An Entra identity with the Graph **application** permission
`DeviceManagementManagedDevices.Read.All` and admin consent. Locally that is
`DefaultAzureCredential` (managed identity, workload identity, or service-principal
environment variables), with `tenant_id` stored and `AZURE_TENANT_ID` overriding it.
To name the customer's own app registration instead, set `client_id` and one of
`client_secret_ref`, `client_certificate_ref`, or `federated_token_file_ref`; hosted
server mode requires this and ignores `AZURE_TENANT_ID` (see
[Hosted connector credentials](SERVER_AUTH.md#hosted-connector-credentials)). Only
references are stored, never a secret value. The tenant needs an active Intune license.

**Data minimization.** The list call uses `$select` for posture fields only.
IMEI, serial number, MAC addresses, phone number, user display name, and admin
notes are never requested. `userPrincipalName` is kept as the join key to
identity-provider users. Pagination follows `@odata.nextLink` only while it stays on
`https://graph.microsoft.com`, so the bearer token is never sent elsewhere.

## BambooHR: employment records

`bamboohr-personnel` reads BambooHR's `employee` dataset
(`POST https://{company_domain}.bamboohr.com/api/v2/datasets/employee/data`,
paged 500 rows at a time) and emits one current-state
`hris.personnel.employment` event per employee. The event shape is vendor-neutral
(`security_lakehouse/hris.py`), so later HRIS connectors emit the same record.

| Requested field            | Lands as            |
| -------------------------- | ------------------- |
| `eeid`                     | `employee_id`       |
| `employeeNumber`           | `employee_number`   |
| `email` (work email)       | `work_email`        |
| `employmentStatus`         | `employment_status` |
| `hireDate`                 | `hire_date`         |
| `terminationDate`          | `termination_date`  |
| `jobInformationDepartment` | `department`        |
| `supervisorEid`            | `manager_id`        |

`is_terminated` is true when the termination date is on or before the collection
date. Events feed FEDRAMP-PS-4, FEDRAMP-PS-5, ISO27001-A.6.5, CMMC-3.9.2, and
HIPAA-164.308(a)(3) as personnel-lifecycle evidence. Whether access was actually
removed is answered by the [offboarding check](#offboarding-check-hr-terminations--idp-accounts).

**PII boundary.** Only the fields above are requested. Names, dates of birth,
government IDs, compensation, addresses, and personal contact details are never
requested. Personnel attributes stay in raw/bronze (silver and gold carry ids and
status only) and are marked `data_sensitivity: confidential`, so auditor and
public-share roles see them redacted.

**Credentials.** BambooHR API keys inherit the permissions of the user who created
them. Create a dedicated user whose access level can view only these fields, and
store its key as a secret reference (`credential_ref`, default
`BAMBOOHR_API_KEY`; a `<NAME>_FILE` variant is preferred). `company_domain` must be
the bare subdomain (`acme` for `acme.bamboohr.com`); anything else is rejected, so
the authenticated request can never be pointed at another host.

## Rippling: employment records

`rippling-personnel` reads `GET https://rest.ripplingapis.com/workers/` (Rippling
REST API, scope `workers.read`, cursor pages of 100 via `next_link`) and emits the
same `hris.personnel.employment` event as BambooHR: `id` → `employee_id`, `number`,
`work_email`, `status`, `start_date` → `hire_date`, `end_date` →
`termination_date`, `department_id`, and `manager_id`.

The workers endpoint cannot select fields, so its response can include date of
birth, gender, compensation ids, and personal email. The connector copies only
the fields above and discards the rest before anything is written. `next_link` is
followed only while it stays on `https://rest.ripplingapis.com`. Store the token as
a secret reference (`credential_ref`, default `RIPPLING_API_TOKEN`).

## Workday: employment records (RaaS)

Workday's public Staffing REST worker resource has no termination date or work
email, so `workday-personnel` reads a tenant-defined custom report published as a
web service (RaaS). Build an advanced report on workers (include terminated
workers) with exactly these column aliases:

| Column             | Content                                 |
| ------------------ | --------------------------------------- |
| `Employee_ID`      | Employee or contingent worker ID        |
| `Work_Email`       | Primary work email                      |
| `Worker_Status`    | Active / terminated status              |
| `Hire_Date`        | Hire date (`YYYY-MM-DD`)                |
| `Termination_Date` | Termination date, empty if none         |
| `Department`       | Supervisory organization or cost center |
| `Manager_ID`       | Manager's employee ID                   |

Enable it as a web service, share it with a read-only integration system user,
and configure `report_url` (the report's `…?format=json` URL), `username`, and
the ISU password as a secret reference (`credential_ref`, default
`WORKDAY_ISU_PASSWORD`). The URL must be https on a Workday domain
(`*.workday.com`, `*.myworkday.com`, `*.myworkdaygov.com`), request
`format=json`, and carry no embedded credentials. Rows are read from the
`Report_Entry` list; other columns are ignored and never stored. The same
PII boundary and `data_sensitivity: confidential` marking apply to all three HRIS
connectors, and all three feed the offboarding check below.

## Databricks evidence lake (preview)

`databricks-evidence-lake` is an existing-lake reader. It runs
`SELECT * FROM` each of the four GRC Lake evidence views in a Unity Catalog
schema through the SQL Statement Execution API (`POST /api/2.0/sql/statements`,
`INLINE` + `JSON_ARRAY`, polling while `PENDING`/`RUNNING`, following
`next_chunk_internal_link` or `next_chunk_index`). No Databricks SDK or driver is installed.

Setup:

1. Run [`deploy/databricks/bootstrap_poc.sql`](../deploy/databricks/bootstrap_poc.sql)
   as a user who can create a catalog and read `system.access.audit`, replacing
   `<trustops-sp-application-id>` with a service principal's application id.
2. Grant that service principal `CAN USE` on one SQL warehouse.
3. Create an OAuth secret for the service principal and store it as a secret
   reference (`client_secret_ref`, default `DATABRICKS_CLIENT_SECRET`).
4. Configure `host`, `warehouse_id`, `catalog`, `schema`, and `client_id`, then
   probe and enable.

GRC Lake mints a one-hour token at `https://<host>/oidc/v1/token`
(`client_credentials`, `scope=all-apis`) for each sync and keeps it in memory.
The reader renews cached tokens before their reported expiry and retries an
unauthorized statement request once with a fresh token. Repeated authorization
failures fail the sync; this does not change the principal's permissions. The
host must be a Databricks workspace domain (`*.cloud.databricks.com`,
`*.azuredatabricks.net`, `*.gcp.databricks.com`); result chunk links may not
leave it; catalog, schema, and view names are strict identifiers quoted with
backticks. The bootstrap views keep the latest 10,000 audit events so a read
bounds row count; actual payload size must still fit the 25 MiB inline result
limit. The bootstrap accepts both audit response field spellings (`status_code`
and `statusCode`). An empty audit window or missing response code does not
establish a passing denied-access review.

The reader checks the [Statement Execution result contract](https://docs.databricks.com/api/statement-execution/v1/statement-execution)
before returning evidence: truncated results, missing data, inconsistent schemas,
row counts or offsets, and unfinished pagination fail the sync. The failed run
records a collection gap and `partial: true`; existing raw evidence, assessments
and watermarks remain unchanged. A declared zero-row result is valid. These checks
apply to both the four standard views and custom lake mappings.

A [bounded trial receipt](qualification/live/2026-10-25-databricks.md) records
OAuth collection and recollection of eight synthetic rows, plus two
`not_evaluated` summaries over an empty system audit log. The adapter remains
Preview: populated system audit logs, multi-chunk results, throttling and
credential expiry still need live qualification.

## Jamf Pro: macOS and iOS device posture (preview)

`jamf-devices` reads the Jamf Pro API (11.32 reference) — `GET /api/v4/computers-inventory`,
`GET /api/v2/mobile-devices/detail` (both paged 100 at a time), and
`GET /api/v1/managed-software-updates/available-updates` — and emits current-state
events per managed Mac and iPhone/iPad:

| Event                     | Pass when                                                                                 | Controls                                                                                 |
| ------------------------- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `jamf.device.encryption`  | FileVault boot volume encrypted (Mac) or `dataProtected` (iOS)                            | FEDRAMP-AC-19.5, CMMC-3.1.19, ISO27001-A.8.1                                             |
| `jamf.device.management`  | Managed, not jailbroken, and checked in within 30 days                                    | FEDRAMP-AC-19, CMMC-3.1.18, SOC2-CC6.8, ISO27001-A.8.1, FEDRAMP-CM-8                     |
| `jamf.device.os_patch`    | OS version is the newest Apple offers for that major version                              | FEDRAMP-SI-2, CMMC-3.14.1, ISO27001-A.8.8, SOC2-CC7.1, CIS-CONTROLS-7, NIST-CSF-PR.PS-02 |
| `jamf.device.screen_lock` | Passcode present and compliant (iOS), or the configured extension attribute is true (Mac) | FEDRAMP-AC-11, CMMC-3.1.10, ISO27001-A.8.1                                               |
| `jamf.device.firewall`    | macOS application firewall enabled                                                        | FEDRAMP-CM-6, CMMC-3.4.2, CIS-CONTROLS-4, ISO27001-A.8.1                                 |

Encryption and management use the same controls as `intune-devices`, so either MDM
satisfies them. An unencrypted disk, an unmanaged or jailbroken device, a missing
passcode, or a macOS major version Apple no longer offers updates for is high; an
available update, a stale check-in, a disabled firewall, or an unenforced screen lock
is medium; encryption in progress is low. Signals Jamf does not report are not
emitted rather than guessed: Jamf inventory has no macOS screen-lock field, so Macs
are evaluated only when you name a computer extension attribute
(`screen_lock_attribute`) that reports it; Apple TV and Apple Watch get only the
management event; and if the API client cannot read the available-updates feed (403
or 404) no patch verdict is emitted.

**Least privilege.** In Jamf Pro, **Settings > System > API roles and clients**:

1. Create an API role with only **Read Computers** and **Read Mobile Devices**.
2. Create an API client with that role, enable it, and generate a client secret.
3. Store the secret in your secret store and configure `base_url`
   (`https://yourcompany.jamfcloud.com`), `client_id`, and `client_secret_ref`
   (default `JAMF_CLIENT_SECRET`).

GRC Lake exchanges the client credentials at `POST {base_url}/api/v1/oauth/token`
for a short-lived bearer token held in memory only, re-mints it once on a 401, and
fails closed after that. No Jamf user account or password is used.

**Data minimization.** Only the GENERAL, DISK_ENCRYPTION, OPERATING_SYSTEM, SECURITY,
and USER_AND_LOCATION sections are requested (EXTENSION_ATTRIBUTES only when a
screen-lock attribute is configured). From them GRC Lake keeps device ID and name,
platform, OS version, encryption, firewall and passcode state, managed and check-in
state, and the assigned user's email (the join key to identity-provider users). IP
addresses, serial numbers, usernames, real names, phone numbers, recovery keys, and
locations are dropped before anything is stored. Every request goes only to the
configured `base_url` through the public-egress guard with 429/5xx backoff.

## CrowdStrike Falcon: sensor coverage and prevention (preview)

`crowdstrike-falcon` reads the Falcon API of one CrowdStrike cloud and emits
current-state endpoint evidence:

| Event                                | Pass when                                                                  | Controls                                                                                  |
| ------------------------------------ | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `crowdstrike.host.sensor`            | The sensor reported within 7 days and is not in reduced functionality mode | SOC2-CC6.8, FEDRAMP-SI-3, CMMC-3.14.2, ISO27001-A.8.7, CIS-CONTROLS-10, NIST-CSF-DE.CM-09 |
| `crowdstrike.host.prevention_policy` | An enabled prevention policy is assigned and applied                       | SOC2-CC6.8, FEDRAMP-SI-3, CMMC-3.14.2, ISO27001-A.8.7                                     |
| `crowdstrike.detections.summary`     | No unresolved critical, high, or medium alerts from the last 30 days       | SOC2-CC7.2, FEDRAMP-SI-4, CMMC-3.14.6, ISO27001-A.8.16, NIST-CSF-DE.CM-09                 |

Reduced functionality mode, a missing, disabled, unapplied, or unknown prevention
policy, and an unresolved critical or high alert are high-severity open findings. A
sensor that has not reported in 7 days, or never reported, is medium.

**Least privilege.** On the Falcon console's API clients and keys page, create an API client with only **Hosts: Read**, **Prevention policies: Read**,
and **Alerts: Read**. Store its secret and configure `cloud` (`us-1`, `us-2`, `eu-1`,
`us-gov-1`, `us-gov-2`), `client_id`, and `client_secret_ref` (default
`CROWDSTRIKE_CLIENT_SECRET`). GRC Lake exchanges the client credentials at
`https://<cloud API host>/oauth2/token` for a short-lived token held in memory only
and re-mints it once on a 401.

**Calls.** `GET /devices/queries/devices-scroll/v1`, then
`POST /devices/entities/devices/v2` (5,000 IDs per call);
`GET /policy/combined/prevention/v1`; and `POST /alerts/combined/alerts/v1` filtered to
`status:!'closed'` within a 30-day window. All requests go to the selected cloud's API
host through the public-egress guard; a 429 waits for `X-RateLimit-RetryAfter` (or
`Retry-After`).

**Data minimization.** Only host ID, hostname, platform, OS and sensor version, first
and last seen, containment status, reduced-functionality flag, and prevention policy
assignment are kept. MAC and IP addresses, serial numbers, user names, and tags are
dropped before storage. From alerts, only ID, status, severity, and creation time are
used, and only to compute the summary counts.

## Snyk: vulnerability issues per project (preview)

`snyk-vulnerabilities` reads the Snyk REST API (`version=2024-10-15`) for every
organization the token can see, or only `options.org_ids`, and emits current-state
vulnerability evidence. Project and issue rows bind
`SG-VULNERABILITYMANAGEMENT-001`. Framework results come from that safeguard's
reviewed crosswalk. The rows' tags (SOC2-CC7.1, ISO27001-A.8.8, NIST-800-53-RA-5,
NIST-800-53-SI-2) all sit inside it.

| Event                        | Outcome                                                                                                                                                                                                  |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `snyk.issue`                 | One per open-source, container, or code vulnerability issue (`package_vulnerability`, `code`). Open is `open` at Snyk's effective severity; resolved is `resolved`; open but ignored is `not_evaluated`. |
| `snyk.project.test_coverage` | One per active project. `pass` only when Snyk tested the project within `options.max_test_age_days` (default 7, at most 90) and the issue listing was complete; otherwise `not_evaluated`.               |
| `snyk.org.summary`           | Observation: project and issue counts, including what was skipped.                                                                                                                                       |
| `snyk.collection_gap`        | An organization, its projects, or its issues could not be read (HTTP 403/404, or the page budget ran out). The sync reports itself partial.                                                              |

Projects are the assets: container OS projects (`apk`, `deb`, `rpm`, `linux`) are
`container_image`, all other project types are `repo`. Both are in the safeguard's
scope. An asset passes only with a passing test-coverage row and no open or
ignored vulnerability. A project without issues therefore passes only when it was
recently tested. A project that was never tested, was last tested outside the
window, or whose latest test counted issues that the issues API did not list stays
`not_evaluated`. The connector does not evaluate remediation deadlines. Issue
rows carry `created_at`, `resolved_at`, `age_days`, severity, and fixability, so
deadline rules can be added later.

Not evaluated, only counted on the org summary: inactive projects, license, IaC
configuration, cloud, custom, and secrets issues, and issues on non-project scan
items (Snyk environments).

**Least privilege.** Use a read-only token. Snyk documents a **Group Viewer**
service account as the way to make a token read-only. Service accounts are an
Enterprise feature, and organization-level service accounts can only be Org
Admin or Org Collaborator. On other plans, use a user token whose custom role
holds only **View Organization**, **View Project**, and **View Project History**.
Store the token and set `credential_ref` (default `SNYK_TOKEN`). Set `region` to
`SNYK-US-01` (default, `api.snyk.io`), `SNYK-US-02` (`api.us.snyk.io`),
`SNYK-EU-01` (`api.eu.snyk.io`), or `SNYK-AU-01` (`api.au.snyk.io`). Any other
value, including a URL, is refused, so the token only ever goes to a Snyk API
host. A token works only in its own region and gets HTTP 401 elsewhere.

**Calls.** `GET /rest/orgs`, `GET /rest/orgs/{org_id}/projects?meta.latest_issue_counts=true`,
and `GET /rest/orgs/{org_id}/issues`, 100 per page, with `Authorization: token …`.
Only the `starting_after` cursor is taken from `links.next`; the request is rebuilt
on the regional host. Each list stops after `options.max_pages` pages (default 200,
at most 1,000) and records a gap rather than a shorter success. HTTP 429 (Snyk
allows 1,620 requests per minute per key) waits for `Retry-After` when sent, else
backs off exponentially. Malformed pages and a next link without a cursor fail the
sync.

**Data minimization.** Kept per issue: ID, key, type, title, severity, status,
ignore flag, created, updated, and resolved times, resolution type, problem and CVE
IDs, fixability flags, and risk score. Descriptions, code flows, file locations,
and dependency coordinates are not stored. Kept per project: name, type, origin,
target file and reference, criticality, lifecycle, environment tags, test
frequency, and last test time (`meta.latest_issue_counts.updated_at`, which Snyk's
migration guide maps to the v1 `lastTestedDate`).

## Kubernetes: cluster configuration baseline (preview)

`kubernetes-cluster` reads cluster configuration with `list` calls only, using the
official Kubernetes Python client
(`pip install 'grc-lake[kubernetes]'`), and emits current-state
events:

| Event                                   | Open when                                                                                               | Controls                                                                                              |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `kubernetes.rbac.cluster_admin_binding` | A (Cluster)RoleBinding grants `cluster-admin` to a non-`system:` subject (CIS 5.1.1)                    | FEDRAMP-AC-6, FEDRAMP-AC-6.5, CMMC-3.1.5, SOC2-CC6.3, ISO27001-A.8.2, NIST-CSF-PR.AA-05               |
| `kubernetes.workload.pod_security`      | Privileged, hostPath, host namespaces (high); root or privilege escalation allowed (medium) (CIS 5.2.x) | FEDRAMP-CM-6, FEDRAMP-CM-7, CMMC-3.4.2, CMMC-3.4.6, ISO27001-A.8.9, CIS-CONTROLS-4, NIST-CSF-PR.PS-01 |
| `kubernetes.namespace.network_policy`   | A namespace has no NetworkPolicy (CIS 5.3.2)                                                            | FEDRAMP-SC-7, CMMC-3.13.1, ISO27001-A.8.22                                                            |
| `kubernetes.workload.image_registry`    | An image is outside `allowed_registries` (medium) or uses `latest`/no tag without a digest (low)        | FEDRAMP-CM-7.5, NIST-CSF-PR.PS-05, CIS-CONTROLS-2                                                     |
| `kubernetes.workload.secret_env`        | Secrets are injected as environment variables (CIS 5.4.1)                                               | FEDRAMP-SC-28, CMMC-3.13.16, NIST-CSF-PR.DS-01                                                        |
| `kubernetes.cluster.audit_logging`      | The kube-apiserver lacks `--audit-policy-file` plus a log or webhook sink (CIS 1.2.16, 3.2.1)           | FEDRAMP-AU-2, FEDRAMP-AU-12, CMMC-3.3.1, ISO27001-A.8.15, NIST-CSF-PR.PS-04, CIS-CONTROLS-8           |

GPU clusters add workload inventory and exposure evidence; see
[Neoclouds and GPU clouds](#neoclouds-and-gpu-clouds-preview).

CIS references are to the CIS Kubernetes Benchmark v1.10. Workloads are evaluated on
their controller's pod template (Deployment, DaemonSet, StatefulSet, CronJob, and
ownerless ReplicaSets, Jobs, and Pods), so a pod is never counted twice. Without
`allowed_registries`, image evidence is recorded as `observed` inventory, never as a
pass. The built-in `cluster-admin` binding to `system:masters` is recorded as
`observed`. System namespaces are not exempted: privileged CNI or CSI DaemonSets in
`kube-system` show as findings, tagged `system_namespace`.

**Audit logging on managed clusters.** EKS, GKE, and AKS do not expose the API server
to the cluster, so no audit-logging event is emitted there; evidence audit logging
through the cloud posture connector instead. Self-managed clusters (kubeadm and
similar) expose the apiserver static pod and are evaluated.

**Least privilege.** Use a kubeconfig for a dedicated identity (optionally a named
`context`; `kubeconfig_ref` names the env var holding its path, default `KUBECONFIG`)
or the in-cluster service account when GRC Lake runs inside the cluster (local and
CLI runs only; hosted server mode requires `kubeconfig_ref`). Bind it to
this get/list-only ClusterRole — never `view`, `edit`, or `cluster-admin`, and no
access to Secrets:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: grc-lake-config-reader
rules:
  - apiGroups: [""]
    resources: ["namespaces", "pods", "services"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets", "replicasets"]
    verbs: ["get", "list"]
  - apiGroups: ["batch"]
    resources: ["cronjobs", "jobs"]
    verbs: ["get", "list"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "list"]
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["clusterrolebindings", "rolebindings"]
    verbs: ["get", "list"]
  # Optional, KServe clusters only. Without it, inference endpoints are a coverage gap.
  - apiGroups: ["serving.kserve.io"]
    resources: ["inferenceservices"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: grc-lake-config-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: grc-lake-config-reader
subjects:
  - kind: ServiceAccount
    name: grc-lake
    namespace: grc-lake
```

**Egress.** The client talks directly to the operator-configured API server. Cluster
endpoints are usually private addresses, so the public-address egress guard used for
SaaS APIs does not apply here. Lists page with `limit`/`continue` and retry 429/5xx
honoring `Retry-After`.

**Data minimization.** Secret objects are never listed. Environment variable values,
container commands and args, IP addresses, labels, and annotations are never stored;
only the names of Secret-backed variables, image references, binding subjects, and
Service types and ports are kept. Service selectors and pod template labels are read
in memory to match Services to GPU workloads, and the KServe visibility label to
detect cluster-local endpoints.

## Neoclouds and GPU clouds (preview)

GPU clouds are assessed with two connectors: `kubernetes-cluster` for managed
Kubernetes on CoreWeave and Nebius (or any cluster running the NVIDIA device plugin),
and `lambda-cloud` for Lambda GPU instances. Both are preview: fixture-tested, not
yet run against a live tenant. Evidence binds to existing CCF safeguards. The
framework requirements it reaches come from each safeguard's reviewed crosswalk, and
proposed mappings are never attested.

### CoreWeave and Nebius managed Kubernetes

The `kubernetes-cluster` connector works unchanged against these clusters. Point
`kubeconfig_ref` at a kubeconfig for a dedicated identity bound to the
`grc-lake-config-reader` ClusterRole above.

- **CoreWeave Kubernetes Service (CKS).** The kubeconfig from the Cloud Console
  embeds an API access token whose expiry and cluster scope are set when the token is
  created. Private clusters have no public API endpoint, so run GRC Lake where it
  can reach the private endpoint.
- **Nebius Managed Kubernetes.** `nebius mk8s cluster get-credentials --id <id>
--external` (or `--internal` from a Nebius VM) writes a kubeconfig that calls the
  `nebius` CLI as an exec credential plugin. The official Kubernetes client runs that
  plugin, so the CLI must be installed and signed in where GRC Lake runs. Local and
  CLI runs accept it. Hosted mode rejects it (see below), so give a hosted
  deployment a kubeconfig carrying a service-account token.

**Hosted mode refuses kubeconfig command plugins.** In hosted server mode, a tenant
kubeconfig whose selected context's user has an `exec` plugin or an `auth-provider`
entry is rejected before the client is built. Either one would make the server run a
local command. GRC Lake parses the file with a safe YAML loader and never executes
it. A path list is merged the way the Kubernetes client merges it. A kubeconfig that
cannot be parsed, or whose selected context is missing, also fails closed. Use a
service-account token or a client certificate instead.

| Event                                       | Asset type            | Result                                                                                                                                                                                                                                                      | Safeguard        |
| ------------------------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| `kubernetes.workload.accelerator_inventory` | `kubernetes_workload` | `observed`: GPU count (`nvidia.com/gpu`, `amd.com/gpu`), InfiniBand (`rdma/ib`), serving runtime (vLLM, Triton, TGI, NVIDIA NIM), and the namespace's NetworkPolicy count as InfiniBand job scope                                                           | none (inventory) |
| `kubernetes.service.network_exposure`       | `network`             | LoadBalancer with a public address and no `loadBalancerSourceRanges` (or `0.0.0.0/0`): open, high when it selects a GPU workload, else medium. Public with restricted ranges, or a private address: pass. NodePort, or no assigned address: `not_evaluated` | `SG-NETWORK-001` |
| `kubernetes.inference.network_exposure`     | `service`             | KServe InferenceService labelled `networking.kserve.io/visibility: cluster-local` or with a `*.svc.cluster.local` URL: pass. External URL or no URL: `not_evaluated`                                                                                        | `SG-NETWORK-001` |

Address scope is read from `status.loadBalancer.ingress[].ip`, not from provider
annotations. CoreWeave, for example, assigns a public address only when the Service
carries `service.beta.kubernetes.io/coreweave-load-balancer-type: public`; judging
the assigned address works the same on every provider. A denied Services or
InferenceService list becomes a `kubernetes.collection.gap` row and the sync is marked
partial. A cluster without KServe (HTTP 404) has no InferenceServices.

### Lambda Cloud (`lambda-cloud`)

Reads `https://cloud.lambda.ai/api/v1` (Lambda Cloud API 1.10.0) with
`Authorization: Bearer <key>`, issuing only `GET`: `/account`, `/instances` (paged by
`page_size`/`page_token`, at most 100 pages), `/firewall-rulesets`,
`/firewall-rulesets/global`, `/ssh-keys`, and `/api-keys`. Requests are paced to one
per second, the documented limit, and retry 429 honoring `Retry-After`. Every request
goes to the fixed host through the public-address egress guard; page tokens are only
sent as query values.

**Credentials.** `credential_ref` names the environment variable or secret file
holding the API key (default `LAMBDA_API_KEY`). Lambda API keys carry full API access
and cannot be scoped, so create a key for a dedicated identity and use it only for
GRC Lake. Listing API keys needs the account's API-key read permission (service
identity keys also need the service-identity read permission); without it, key
hygiene is a coverage gap. A refused firewall or SSH key read is a coverage gap too,
and the affected instance results become `not_evaluated`.

| Event                                    | Asset type         | Result                                                                                                                                                                                                    | Safeguard         |
| ---------------------------------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `lambda_cloud.instance.network_exposure` | `cloud_resource`   | Global ruleset plus the instance's rulesets. `0.0.0.0/0` to all protocols, all ports, SSH (22) or RDP (3389): open/high. Another internet-open TCP/UDP port: open/medium. Otherwise pass. ICMP is ignored | `SG-NETWORK-001`  |
| `lambda_cloud.instance.ssh_access`       | `cloud_resource`   | DSA, or RSA under 2048 bits: open/medium. Strong keys: `observed`, because key strength alone does not establish logical access                                                                           | `SG-IDENTITY-001` |
| `lambda_cloud.identity.api_key`          | `identity_account` | No expiry: open/medium. Unused for 90 days: open/low. Otherwise, or expired: `observed`. The asset is the owning identity                                                                                 | `SG-IDENTITY-001` |

**Data minimization.** Jupyter tokens, public and private IP addresses, host names,
tags, rule descriptions, public key material, and identity display names are dropped
in the client. Only whether an instance has a public IP or a Jupyter URL is kept.

### What GPU cloud APIs cannot show

These stay unassessed or `not_evaluated`. None is reported as a pass.

- **Encryption at rest and in transit.** Neither the Kubernetes API nor the Lambda
  Cloud API exposes disk, filesystem, or InfiniBand fabric encryption settings.
- **InfiniBand fabric isolation.** Fabric partitioning and tenant isolation are
  provider-managed and invisible to both APIs; the inventory records which jobs use
  the fabric.
- **Inference endpoint authentication.** An external KServe URL is `not_evaluated`:
  authentication is enforced by the ingress or service mesh, not the InferenceService.
- **NodePort and pending load balancers.** Reachability depends on node addressing
  and provider networking that the Kubernetes API does not report.
- **Lambda `us-south-1`.** The API reference states that firewall rules do not apply
  there, so exposure is `not_evaluated`. Jupyter URLs are recorded, not judged.
- **Audit logging.** Managed control planes do not expose API server audit settings.
  Lambda keeps account audit events for six months (`GET /audit-events`); this
  connector does not collect them yet.
- **Nebius control-plane API.** Nebius compute instances, VPC security groups, and IAM
  service accounts sit behind REST and gRPC APIs that need a service-account JWT
  exchanged for an IAM token. They are not collected; Nebius evidence comes from its
  managed Kubernetes clusters only.
- **Population completeness.** Only the assets a sync observed are assessed.

**Live qualification.** A live run needs a CKS or Nebius kubeconfig bound to the
ClusterRole above, with a GPU workload, a LoadBalancer Service, and ideally KServe,
plus a Lambda Cloud API key for an account with at least one instance and ruleset.
Record the run in `docs/qualification/connector-evidence.json` before removing the
preview label.

## Training completion: LMS exports (preview)

`training-completion` reads security awareness training assignments and
completions from a CSV or JSON export. Most learning-management and
security-awareness platforms (for example Workday Learning, Cornerstone, Docebo
or a security-awareness vendor's reporting export) can schedule one. The reader
makes no vendor API calls, so it has no provider paging or rate-limit contract.
The operator owns the export's completeness. Each row keeps the export file's
SHA-256 as provenance.

Point `credentials.path` at an export file or a directory of `.csv`/`.json` files
(read non-recursively, at most 50 files of 25 MB each and 200,000 records). The path
must sit under `GRC_LAKE_LAKE_LOCAL_ROOT`, the same allowed root the Parquet reader
uses. In hosted mode each tenant reads only `<root>/<tenant_id>`. Symlinks that leave
the export directory are rejected. To use object storage, sync the export into that
directory, for example with a scheduled `aws s3 sync`. The object-storage connector
lists objects but does not read their contents.

| Column         | Required                      | Content                                                                                           |
| -------------- | ----------------------------- | ------------------------------------------------------------------------------------------------- |
| `person_email` | one of email or `employee_id` | Work email, the join key to HR records                                                            |
| `employee_id`  | one of email or `employee_id` | Matches the HR employee ID or employee number                                                     |
| `course_id`    | yes                           | Course, assignment or campaign ID                                                                 |
| `course_name`  | no                            | Display name                                                                                      |
| `assigned_at`  | no                            | `YYYY-MM-DD` or ISO-8601 (naive times are read as UTC)                                            |
| `due_at`       | no                            | Same format; a past due date on an incomplete assignment makes it overdue                         |
| `completed_at` | when `status` is `completed`  | Same format; must be empty for any other status and not in the future                             |
| `status`       | yes                           | `completed`, `in_progress`, `not_started` or `overdue` (also `complete`, `passed`, `past_due`, …) |
| `score`        | no                            | 0–100                                                                                             |
| `required`     | no                            | `true`/`false` (default `true`); optional courses never pass or fail anyone                       |

```csv
person_email,employee_id,course_id,course_name,assigned_at,due_at,completed_at,status,score,required
ada@example.com,101,SAT-2026,Annual security awareness,2026-01-05,2026-02-05,2026-01-20,completed,92,true
alan@example.com,103,SAT-2026,Annual security awareness,2026-01-05,2026-02-05,,overdue,,true
```

JSON exports use the same field names, as a list of objects or `{"records": [...]}`.
If the export uses other headers, rename them with `options.column_map`, for example
`{"person_email": "User Email", "completed_at": "Completion Date"}`. Other columns
are ignored and never stored. When a person has several rows for one course, the
row with the most recent activity wins.

Validation is strict. An unreadable, non-UTF-8, oversized or empty export fails the
sync, as does an unknown status or invalid date. The error names files, row numbers
and columns, never values. The previous evidence and assessment stay in place.
Attributes are marked `data_sensitivity: confidential`.

**Evaluation.** After a training or HRIS sync, GRC Lake rebuilds one derived row per
person under the derived id `hris-training-coverage`. It joins the export to
`hris.personnel.employment` rows from any HR connector on work email, then
employee ID or number. Only required courses count.

| Person                                                        | Outcome                   | Status          |
| ------------------------------------------------------------- | ------------------------- | --------------- |
| Active, every due course completed within the window          | `completed_within_window` | pass            |
| Any required course overdue                                   | `overdue`                 | open            |
| Latest completion older than the window                       | `completion_expired`      | open            |
| Active in HR, no training record, past the onboarding grace   | `no_training_record`      | open            |
| In the export but not in HR                                   | `not_in_hr_population`    | `not_evaluated` |
| Email and employee ID point at different HR records           | `identity_conflict`       | `not_evaluated` |
| No HR evidence at all: a completion                           | `hr_population_missing`   | `not_evaluated` |
| Terminated, not yet started, inside the grace, or not yet due | counted only              | no row          |

Without HR evidence, overdue training is still open because the training system
reports it. A completion cannot pass, since the population is unknown. The window
(`options.completion_window_days`, default 365, 1–1095) and onboarding grace
(`options.new_hire_grace_days`, default 30, 0–365) are set on the connector.
`options.system` labels the source (default `training-export`).

Person rows use the `user` asset type and bind `SG-TRAINING-001`. Their framework
tags are CMMC-3.2.1, FEDRAMP-AT-2, FEDRAMP-AT-4, NIST-800-53-AT-2,
NIST-800-53-AT-4 and NIST-CSF-PR.AT-01, all maintainer-reviewed members of that
safeguard's crosswalk. Other requirements, such as ISO27001-A.6.3, follow the
crosswalk only once their mapping is reviewed. SOC 2 CC1.4 and CC2.2 are not mapped
to this safeguard. `SG-IDENTITY-001` also accepts `user`, so trained people appear
there as unassessed assets.

One summary row states the result, for example "4 of 5 active personnel completed
required training within the last 365 days". It also carries every count above. Its
`population_completeness` is `hr_population` only when HR evidence exists.

## Retired connectors

The KnowBe4 preview connector (`knowbe4-training`) is removed in the next release
after 0.3.9. It is no longer offered for configuration, access probes, or syncs.
Saved configurations remain in the append-only history but are excluded from
scheduled collection. Explicit calls for that connector ID are rejected.

Previously collected observations, assessments, snapshots and exports remain
available. Retirement does not delete evidence or change recorded control results;
evidence still ages under the normal freshness rules. Remove any external jobs
that call this connector, and revoke its Reporting API token in KnowBe4 if it is
no longer used elsewhere. GRC Lake does not revoke provider credentials.

For training evidence, use the vendor-neutral
[`training-completion`](#training-completion-lms-exports-preview) export reader,
which needs no provider API. Managed local evidence remains available for other
training records and reviews; a submitted document does not by itself establish
training completion or satisfy the control.

## Existing lakes: mappings, Iceberg/Parquet, BigQuery (preview)

The Snowflake, Databricks, and ClickHouse readers can read existing tables
through a lake mapping (`options.mapping` / `options.mappings`) instead of the
GRC Lake views. `iceberg-parquet-lake` reads Iceberg tables through AWS Glue
(including Amazon Security Lake, with OCSF presets by default) or an Iceberg REST
catalog, and Parquet on S3 or an allowed local root. `bigquery-evidence-lake` reads
BigQuery tables with Application Default Credentials. The spec, the OCSF presets,
`lake map --dry-run`, and per-backend least-privilege setup are in
[BRING_YOUR_OWN_LAKE.md](BRING_YOUR_OWN_LAKE.md).

## Offboarding check: HR terminations ↔ IdP accounts

After any sync that writes HR employment rows (`hris.personnel.employment`, from
any HRIS connector) or identity-provider user rows (`okta-identity`,
`google-workspace-identity`), GRC Lake rebuilds one derived row per terminated
employee. It joins HR records to IdP accounts on the lower-cased work email and
writes the result as a snapshot under the derived id `hris-idp-offboarding`
(source `grc-lake-correlation`), so a fixed account clears on the next sync.

| Outcome                    | Meaning                                                        | Status     |
| -------------------------- | -------------------------------------------------------------- | ---------- |
| `active_after_termination` | An account can still sign in after the grace period            | open, high |
| `within_grace_period`      | Still active, but inside the grace period                      | observed   |
| `deprovisioned`            | Every matched account is disabled                              | pass       |
| `no_idp_account_matched`   | No IdP account shares the work email (never counted as a pass) | observed   |

Rows map to SOC2-CC6.2, FEDRAMP-PS-4, FEDRAMP-AC-2.3, ISO27001-A.5.18,
ISO27001-A.6.5, and CMMC-3.9.2, each of which fails on an open violation. Nothing
is produced until both HR and IdP evidence exist, and future-dated terminations are
ignored. The grace period defaults to 1 day; set
`GRC_LAKE_OFFBOARDING_GRACE_DAYS` (0–365) to change it. Attributes (including the
work email and matched account ids) are marked `data_sensitivity: confidential`.
The derive step runs under the same raw-file lock as connector writes, so
concurrent HR and IdP syncs cannot each derive from a partial view.

### Azure response integrity

Azure CLI inventory reads reject scalar responses, malformed rows, empty stdout,
and REST envelopes with an unconsumed continuation. A valid empty JSON array
still represents an empty collection. The subscription probe requires an object
with an identity; SDK records must serialize to objects. Collection errors are
recorded as failed syncs before the prior raw inventory is replaced. These
contracts are exercised offline by
[`test_azure_collection_integrity.py`](../tests/test_azure_collection_integrity.py);
they do not establish live subscription coverage or credential qualification.
