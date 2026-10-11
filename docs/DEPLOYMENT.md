# Deployment

GRC Lake is an **open-source trust operations platform** you can run on-premises or
in your cloud. The product goal is enterprise-grade continuous
compliance — evidence ingestion, control tests, posture dashboards, trust-center
sharing, and agent APIs — without locking evidence in a vendor silo.

Upgrading from TrustOps? Follow the [rebranding migration guide](REBRANDING.md)
to preserve volumes, release names, secrets and compatibility aliases.

## Deployment models

| Model           | Who runs it                                  | Best for                                                         |
| --------------- | -------------------------------------------- | ---------------------------------------------------------------- |
| **OSS local**   | You, on a laptop or CI runner                | Contributors, evaluators, pipeline proofs                        |
| **Self-hosted** | You, on-premises or in a cloud VPC / cluster | Teams that need data residency, custom connectors, full control  |
| **Hosted mode** | An operator you choose                       | Teams that want a live URL without running Kubernetes themselves |

Application state lives in storage you operate: a filesystem lake with SQLite or
PostgreSQL in local mode, or PostgreSQL plus S3-compatible storage in distributed
mode. Source lakes and optional warehouse exports are separate integrations;
Snowflake or ClickHouse does not replace the application state store. Configured
connectors, exports, model integrations and sharing determine data egress.

## Deployment and lake compatibility

Hosting location does not select the storage mode. Both filesystem and distributed
modes can run on-premises or in the cloud; OSS includes both.

| Choice                         | Supported implementation                                                                                    | Qualification boundary                                                                                                                                  |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application hosting            | VM, container, or Kubernetes; Docker/Helm templates and EKS reference Terraform                             | Operator provisions infrastructure, TLS, identity and backups; AKS/GKE have no dedicated Terraform module here                                          |
| Filesystem mode                | One writable application replica, filesystem evidence, SQLite or PostgreSQL operational state               | A cloud VM or PVC can hold the filesystem; shared disks do not make multi-writer operation safe                                                         |
| Distributed mode               | Multiple API replicas and tenant workers, PostgreSQL primary, S3-compatible object storage, private scratch | Cross-tenant concurrency; one tenant evaluation still runs on one worker. See [qualification limits](DISTRIBUTED.md#container-deployment-qualification) |
| Existing OSS/self-managed lake | ClickHouse tables or supported Iceberg/Parquet layouts; object-storage and SIEM evidence adapters           | Requires the matching reader, schema and credentials; an arbitrary SQL engine or object-store protocol is not automatically supported                   |
| Existing cloud lake            | Snowflake, Databricks, BigQuery, supported Iceberg/Parquet and S3 evidence                                  | Databricks, BigQuery and Iceberg/Parquet readers are preview; mapped-table mode is experimental. See [reader status](BRING_YOUR_OWN_LAKE.md)            |
| Optional exports               | Snowflake, ClickHouse and DuckDB sinks from an operator-owned filesystem run                                | Post-assessment projection; server-mode export needs tenant-scoped destination support and is currently rejected                                        |

Readers copy the selected evidence into GRC Lake's assessment storage while
preserving the source system. Source compatibility is separate from framework
mapping coverage and does not certify live-provider accuracy or deployment scale.
See [supported evidence lakes](HERO_DATA_LAKES.md) and the generated
[framework coverage matrix](FRAMEWORK_COVERAGE.md).

<p align="center">
  <img src="images/grc-lake-readonly-connections.svg" alt="Read-only connections vs vendor SaaS evidence boundary" width="92%">
</p>

Diagrams: [deployment-models.md](diagrams/deployment-models.md) · [connector-ingestion.md](diagrams/connector-ingestion.md)

```text
Sources (AWS, Azure, GCP, GitHub, Okta, Snowflake, …)
  -> read-only connectors
  -> bronze / silver / gold lake (your storage)
  -> deterministic control tests + snapshots
  -> console, API, trust-center shares, agents
```

### OSS local

Fastest path to evaluate the product, with Docker Compose v2:

```bash
docker compose up
```

Open `http://127.0.0.1:8787/console/dashboard/`. It serves the bundled sample
company with authentication off, on `127.0.0.1` only. The
[5-minute tutorial](TUTORIAL_5_MIN.md) covers the pip and source paths.

From a source checkout the console must be built first (`make web-install
web-build`, Node 22+); without that build `/console/` is a 404.

### Python and MCP

The wheel includes the CLI and static console. Optional extras select runtime
dependencies; they are not separate hosted services:

```bash
pip install 'grc-lake[server,mcp]'
GRC_LAKE_LAKE=./lake grc-lake-mcp
```

`grc-lake-mcp` speaks stdio to an MCP client. It can read the operator's local
lake or call an authenticated GRC Lake API using `GRC_LAKE_API_URL` and
`GRC_LAKE_API_KEY`. The HTTP server and console use `grc-lake serve
--server`; configure [server auth](SERVER_AUTH.md) before exposing them.
The Docker image also includes MCP, but its default command starts the HTTP
server. Neither package publication nor container publication creates a cloud
service.

### Self-hosted

Self-hosted shape: Helm chart on EKS/AKS/GKE (or Docker Compose for small pilots),
**one writable application replica in local mode**, OIDC/SAML for humans, API keys for agents,
persistent `/lake`, scheduler-driven
connector syncs, and token-scoped trust-center links.

| Component | Typical POC                        | Production hardening                               |
| --------- | ---------------------------------- | -------------------------------------------------- |
| Runtime   | Helm on a small managed cluster    | Private nodes, workload identity, external secrets |
| Auth      | One tenant, OIDC/SAML              | SCIM lifecycle, enforced SSO, least-privilege RBAC |
| State     | Encrypted PVC at `/lake`           | Backup/restore, per-tenant prefixes                |
| Evidence  | Read-only cloud/service identities | Customer IaC owns roles, grants, rotation          |

Local mode rejects read-only lakes and multiple application replicas, even with
RWX storage or PostgreSQL. Local updates have downtime. Opt-in
[distributed PostgreSQL/S3 mode](DISTRIBUTED.md) supports multiple API, worker and
reader replicas with private scratch storage. See the
[topology boundary](runbooks/HA_READ_REPLICAS.md). EKS has reference Terraform;
AKS/GKE use the same chart with operator-provisioned infrastructure.

Runbook: [Shareable POC Hosting](SHAREABLE_POC_HOSTING.md),
[deploy/README.md](../deploy/README.md),
[Server Auth](SERVER_AUTH.md).

### Hosted mode

Hosted mode is the same GRC Lake binary and chart, run by an operator for
several tenants. There is no public managed service; operators enable the
hosted features with environment flags. Each tenant's connector secrets resolve
only under its own prefix, and cloud readers need delegated access: see
[hosted connector credentials](SERVER_AUTH.md#hosted-connector-credentials). See [COMMERCIAL_HOSTED.md](COMMERCIAL_HOSTED.md) for the
gated commercial features (invites, usage limits, SCIM 2.0, Stripe billing).

Evaluator flow: [Shareable Demo](SHAREABLE_DEMO.md).

## Shipped capabilities

| Capability                                  | GRC Lake                                                                                |
| ------------------------------------------- | --------------------------------------------------------------------------------------- |
| Continuous control tests from integrations  | Implemented connectors + scheduler; live qualification varies by source                 |
| Executive dashboard + framework readiness   | Yes                                                                                     |
| Trust center / customer sharing             | Yes (scoped tokens)                                                                     |
| Policy/policy-template library              | MVP (8 bundled templates + adopt/publish)                                               |
| Auditor workflow / audit project management | MVP (audit room + audit readiness API)                                                  |
| Vendor risk questionnaires                  | MVP (bundled questionnaire templates)                                                   |
| OSS + self-hosted                           | **Yes**                                                                                 |
| Customer-owned evidence lake                | Supported read-only readers and mappings; see the compatibility matrix above            |
| Distributed API and workers                 | Opt-in PostgreSQL/S3 mode; cross-tenant concurrency, with per-tenant evaluation limits  |
| Governed control exceptions                 | Expiring, independently approved acceptance; does not turn a failed control into a pass |

See [Release Readiness](RELEASE_READINESS.md) and [Product Walkthrough](PRODUCT_WALKTHROUGH.md)
for shipped vs planned detail.

## Choosing a path

```text
Need to fork, air-gap, or pass strict data-residency review?
  -> Self-hosted (Helm / your cloud)

Want a live demo link for evaluators this week?
  -> Local fixtures + SHAREABLE_DEMO.md

Already centralize security evidence in Snowflake, Databricks, ClickHouse,
Iceberg/Parquet (Amazon Security Lake), BigQuery, or a SIEM lake?
  -> Existing-lake read mode + GRC Lake assessment on top (BRING_YOUR_OWN_LAKE.md)
```

## Next steps

| Goal                                         | Doc                                                  |
| -------------------------------------------- | ---------------------------------------------------- |
| Run locally in 5 minutes                     | [README.md](../README.md#quick-start)                |
| Read the lake you already run                | [BRING_YOUR_OWN_LAKE.md](BRING_YOUR_OWN_LAKE.md)     |
| Host a shareable POC                         | [SHAREABLE_POC_HOSTING.md](SHAREABLE_POC_HOSTING.md) |
| Evaluator demo script                        | [SHAREABLE_DEMO.md](SHAREABLE_DEMO.md)               |
| Framework packs (SOC 2, NIST AI RMF, custom) | [FRAMEWORK_PACKS.md](FRAMEWORK_PACKS.md)             |
| Architecture                                 | [ARCHITECTURE.md](ARCHITECTURE.md)                   |

For self-hosted support inquiries, open a GitHub discussion or issue on the
repository.

## Partitioning, sharding, replicas and disks

| Capability                | Current support                                         | Deployment responsibility                                                 |
| ------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------- |
| Local evidence lake       | One writable application and scheduler owner per lake   | Operator supplies persistent storage and coordinated backups              |
| ClickHouse partitions     | Reference tables partition by month and tenant          | Operator provisions and operates ClickHouse                               |
| Parquet partitions        | Distributed exports partition by tenant/source/UTC date | Export layout and analytical engine determine pruning                     |
| Iceberg export            | Unpartitioned format-v2 target tables                   | Partitioned target tables are rejected by the exporter                    |
| Application shards        | Stable tenant virtual shards in distributed mode        | Operator assigns worker shard ranges; no automatic placement              |
| Application replicas      | Local: one writer; distributed: multiple replicas       | Distributed mode requires configured PostgreSQL and S3; see its runbook   |
| Database/storage replicas | Backend-specific infrastructure capability              | Operator configures replication, failover and restore testing             |
| RAID                      | No application-managed RAID                             | Host, NAS/SAN or cloud storage layer; redundancy does not replace backups |

OSS local, self-hosted and operator-hosted deployments use the same application
constraints. Hosted mode is an operating model, not a distributed storage mode.

## Cookie-signing hardening (0.3.3 candidate)

Version 0.3.3 requires `GRC_LAKE_COOKIE_SIGNING_KEY` and, when
OIDC is enabled, `GRC_LAKE_SESSION_SECRET` to contain at least 32 bytes after
trimming whitespace. Generate independent random secrets with `openssl rand -hex 32`
and keep them in your existing secret manager. Length validation cannot establish
randomness; repeated or guessable strings are not appropriate secrets.

Browser-session, SAML request-correlation, and OIDC state cookies use explicit
HMAC-SHA-256 signatures. Upgrading from the previous SHA-1 cookie format signs
users out and invalidates in-progress SSO handshakes: users must sign in again,
and pending SSO attempts must restart. There is no legacy SHA-1 verification
fallback. API keys, evidence hashes, database session-token digests, cookie
expiry, SameSite, HttpOnly and Secure settings are unchanged. This change is
not included in the published 0.3.2 release.
