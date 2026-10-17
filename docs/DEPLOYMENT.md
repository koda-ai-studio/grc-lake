# Deployment

GRC Lake is an **open-source trust operations platform** you can run on-premises or
in your cloud. The product goal is enterprise-grade continuous
compliance — evidence ingestion, control tests, posture dashboards, trust-center
sharing, and agent APIs — without locking evidence in a vendor silo.

Upgrading from TrustOps? Follow the [rebranding migration guide](REBRANDING.md)
to preserve volumes, release names, secrets and compatibility aliases.

## Runtime boundary

The 0.3.8 container uses a shell-free Wolfi runtime with matching Python and system libraries. Use the Python CLI
directly (`docker exec <container> grc-lake ...`); `/bin/sh`, Bash, package managers,
`readline`, curses, and the optional system-libuuid Python backend are absent.
Standard Python `uuid` operations remain supported. Install additional libraries
in a build stage and qualify the resulting image before deployment. The application
still runs as UID/GID 1100 with the same persistent paths and authenticated API.
Earlier published images retain their original runtimes; see
[release readiness](RELEASE_READINESS.md) and [dependency security](DEPENDENCY_SECURITY.md).

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

## Configuration and scaling tradeoffs

Select a deployment profile before sizing it. These are shipped configuration
examples, not capacity promises or production sizing recommendations. Hosting in
a cloud does not automatically select distributed mode.

| Workload                                 | Starting profile and configuration                                                                                                                                                             | Tradeoff / when to change                                                                                                                                                                |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Evaluation or CI fixture                 | Loopback-only Docker Compose; filesystem and SQLite; no model required                                                                                                                         | Minimal setup. Bundled no-auth mode is for local evaluation, not a shared service.                                                                                                       |
| Small authenticated deployment           | [Self-hosted values](../deploy/examples/self-hosted-values.yaml); one writable replica, persistent lake, OIDC/SAML, coordinated backups                                                        | Simplest operations. Vertical sizing only; `Recreate` updates have downtime. PostgreSQL alone does not remove the single-writer constraint.                                              |
| Concurrent tenants                       | [Distributed API values](../deploy/examples/distributed/api-values.yaml); PostgreSQL + S3; two API replicas; 1 CPU / 2 GiB requested, 2 CPU / 4 GiB limit per API pod                          | More application availability and tenant concurrency; adds database/object-store operations, network I/O and private scratch. Provider failover still needs testing.                     |
| Evaluation queue pressure across tenants | Add the [worker overlay](../deploy/examples/distributed/worker-values.yaml); two worker replicas inherited from API values, one job each; 2 CPU / 4 GiB requested, 4 CPU / 8 GiB limit per pod | Increase replicas or job concurrency only after measuring memory and database/storage pressure. One tenant still has one running job and one in-memory evaluation.                       |
| Read-heavy console/API traffic           | Add the [reader overlay](../deploy/examples/distributed/reader-values.yaml); separate read Service, API-sized resources                                                                        | Isolates read traffic. Each replica has its own cache and hydration cost; readers still need the PostgreSQL primary for auth/audit writes.                                               |
| One large tenant                         | Profile a full and incremental evaluation before raising resource limits                                                                                                                       | More shards or replicas do not divide that evaluation. The server's 100,000-row routing guard remains; warehouse-native evaluation and tenant-scoped server exports are not implemented. |

Use the [distributed setup commands](DISTRIBUTED.md#kubernetes-profiles), including
one scheduler release and explicit shared secret references. The base Helm chart's
100m CPU / 256 MiB request and 1 CPU / 1 GiB limit are defaults, not a production
sizing recommendation. Do not reuse them as evidence that a workload will fit.

For each candidate configuration, measure p50/p95/p99 request latency, queue wait,
full/incremental evaluation time, peak worker RSS, scratch high-water usage,
PostgreSQL connections, and S3 latency/request volume. Include cold caches, uneven
tenant sizes, simultaneous reads and writes, retries, and a restore exercise.
Retain the commit, provider, hardware, dataset bounds and raw results. See
[benchmark procedure](BENCHMARKS.md) and [runtime tuning](DISTRIBUTED.md#tuning-knobs-and-capacity-budget).
No measured production tenant/event-per-second ceiling is established by these profiles.

### Optional model configuration

Control evaluation and the default agent harness need no LLM. Model selection is
independent of filesystem/distributed mode and does not change control verdicts
or human approval requirements.

| Choice                 | Configuration                                                                                                                   | Tradeoff                                                                                                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Deterministic only     | Leave `GRC_LAKE_AGENT_USE_MODEL` unset; provider defaults to `rules_only`                                                       | No inference service, GPU or model-call cost; deterministic facts and proposals remain available.                                                                                           |
| Customer-run inference | `GRC_LAKE_AGENT_PROVIDER=ollama` or `openai_compatible`, explicit model and reachable base URL; enable model calls deliberately | Operator owns model memory/compute, endpoint security and availability. Container loopback refers to that container, not a separate model service. Size inference separately from GRC Lake. |
| Cloud inference        | Supported provider, model and credential settings from [Agent Harness](AGENT_HARNESS.md#bring-your-own-cloud-model)             | Provider latency, quotas, cost and data residency apply. Role-redacted context is still data sent to that provider; approve the destination. Use workload identity where supported.         |

Model calls default to a 20-second provider timeout (clamped to 1–120 seconds),
12,000 context characters and 600 requested output tokens. Start with those
[bounds](AGENT_HARNESS.md#budget-policy); measure output quality, timeout rate and
cost before increasing them. Larger models and prompts do not increase evidence
coverage or make control evaluation distributed.

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

## Cookie-signing hardening (0.3.3)

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
