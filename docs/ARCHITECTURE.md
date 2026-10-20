# Architecture

The system is intentionally modular. Ingestion, evidence modeling, control
evaluation, snapshots, lake adapters, API, and UI are separate capabilities with
clear contracts.

Hosting location is independent of storage mode: filesystem and distributed
modes can run on-premises or in the cloud. Source lakes are read-only evidence
inputs; optional warehouse exports are post-assessment projections. Neither
replaces the application's state store. See the
[deployment and lake compatibility matrix](DEPLOYMENT.md#deployment-and-lake-compatibility).

## Filesystem deployment mode

```mermaid
flowchart TB
  subgraph External["Customer systems · read-only collection"]
    Sources["Cloud, identity, code and evidence lakes"]
  end
  subgraph Writer["One writable application replica per lake"]
    Ingest["Validate tenant, normalize status, hash evidence"]
    Rules["Versioned controls and safeguard review overlay"]
    Eval["Local Python evaluation · indexed asset and safeguard joins"]
    Stage["Private generation · controls, CCF, freshness, marts"]
    Seal["Verify artifact hashes · atomic current pointer"]
    API["Authenticated API · pinned generation reads"]
    Ops["Operational DB and audit/review ledgers"]
    Jobs["Durable queue · tenant fairness · bounded child processes"]
    Stream["SSE · tenant/generation coalescing · role redaction"]
  end
  subgraph Storage["Customer-owned storage"]
    Raw["Raw observations"]
    Generations["Retained immutable assessment generations"]
    Snapshots["Snapshots · content hash and generation identity"]
    Sinks["Optional warehouse exports"]
  end
  Clients["Console, CLI and MCP"]
  Sources --> Ingest --> Raw
  Raw --> Eval
  Rules --> Eval --> Stage --> Seal --> Generations
  Generations --> API --> Clients
  API --> Ops
  API --> Jobs --> Ingest
  Jobs --> Eval
  API --> Stream --> Clients
  Generations --> Snapshots
  Generations -->|export after local commit| Sinks
```

Collection credentials are scoped to source reads. API authentication and tenant
routing select one lake before business operations. Source `tenant_id` is
provenance and namespaces CCF asset identities; it is not an authorization claim. Agents consume the same API and can propose changes, while deterministic
rules own assessment results. Imported assertions remain assertions: a hash
establishes stored-byte integrity, not truth of the source observation.

Framework controls and CCF safeguards are separate evaluation lanes. CCF evidence
must explicitly name a safeguard, match its asset applicability, and establish an
outcome. Requirement results require all reviewed safeguard results; pending
mappings and missing evidence prevent a pass. The complete asset population is
not established by the observed-event set.

One evaluation time is shared across freshness and control-test calculations.
Incremental runs reuse normalized rows but still rebuild gold outputs when inputs,
review decisions, rules, or freshness change. Historical OSCAL exports verify the
snapshot hash and its retained generation; unavailable history fails closed.

The warehouse sink runs after local publication. API/CLI results expose local and
export outcomes independently so a sink failure does not conceal the new local
assessment. No cross-store transaction is claimed. Evaluation still holds rows in
memory; streaming source reads, indexed joins, and capped response detail do not
make one evaluation distributed. Local mode enforces one writable replica.
[Distributed mode](DISTRIBUTED.md) adds PostgreSQL-fenced publication, immutable
S3 objects, virtual tenant shards and source/date Parquet partitions; it scales
work across tenants while preserving same-tenant publication ordering.

## Distributed deployment

The same evaluation engine runs behind multiple API replicas and tenant workers.
PostgreSQL coordinates jobs and publication; S3 holds committed evidence objects.
Each replica uses private, disposable scratch storage.

```mermaid
flowchart LR
  Clients["Console · remote MCP · API clients"] --> API["API replicas · private scratch"]
  Sources["Read-only evidence sources"] --> Workers["Tenant workers · private scratch"]
  API --> PG["PostgreSQL primary · jobs, records, writer fences, manifests"]
  Workers --> PG
  Workers -->|upload content-addressed artifacts| S3["S3-compatible object storage"]
  API -->|read committed, hash-verified artifacts| S3
  PG -->|committed manifest| API
```

Workers upload artifacts before committing the manifest in PostgreSQL. A stale
writer fence cannot publish; failed publication leaves the previous generation
visible. Different tenants can run concurrently, while each tenant retains one
publication order. Object-store replication and database failover are operator
responsibilities. See [distributed deployment](DISTRIBUTED.md) for qualification
boundaries and recovery procedures.

## Module Boundaries

| Module                          | Owns                                                     | Does not own                                     |
| ------------------------------- | -------------------------------------------------------- | ------------------------------------------------ |
| Connectors                      | reading evidence from systems                            | control decisions                                |
| Evidence model                  | canonical facts, hashes, freshness                       | UI state                                         |
| Control catalog                 | framework/control metadata                               | raw event parsing                                |
| Evaluation engine               | pass/fail, scores, stale evidence, violations            | storage-specific SQL                             |
| Snapshot service                | point-in-time assessment exports                         | live polling                                     |
| Source readers and export sinks | Supported evidence reads and optional result projections | application state authority or control decisions |
| API                             | JSON contracts for humans and agents                     | rendering-only state                             |
| UI                              | interactive workflow                                     | control truth                                    |

## Implementation and test map

Follow these boundaries when reviewing an assessment. Links point to executable
source and failure-focused tests; they are not a claim that every deployment or
provider has been qualified.

| Layer                        | Owning implementation                                                                                                            | Contract to challenge                                                                                                     | Representative tests                                                                                                                  |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Source collection            | [Ingestion](../src/security_lakehouse/ingestion/), [collection completeness](COLLECTION_COMPLETENESS.md)                         | Read-only source access; incomplete collection remains visible                                                            | [Collection receipts](../tests/test_collection_completeness.py)                                                                       |
| Normalization and provenance | [Pipeline](../src/security_lakehouse/pipeline.py), [raw validation](../src/security_lakehouse/validation.py)                     | Raw observations become hashed, normalized records; provider account identity is not platform authority                   | [Pipeline](../tests/test_pipeline.py), [tenant scope](../tests/test_evaluation_tenant_scope.py)                                       |
| Deterministic evaluation     | [Control verdicts](../src/security_lakehouse/control_verdict.py), [CCF evaluation](../src/security_lakehouse/ccf_evaluation.py)  | Required evidence must belong to the same applicable asset and scope; missing evidence cannot borrow another asset's pass | [Evidence completeness](../tests/test_identity_evidence_completeness.py), [CCF assessments](../tests/test_ccf_control_assessments.py) |
| Assessment publication       | [Assessment service](../src/security_lakehouse/services/assessments.py), [generations](../src/security_lakehouse/generations.py) | Readers pin a sealed generation; failed publication preserves the previous view                                           | [Publication failures](../tests/test_generations.py), [service outcomes](../tests/test_assessment_service.py)                         |
| Authority and execution      | [Authentication](../src/security_lakehouse/auth/), [operation jobs](../src/security_lakehouse/operation_jobs.py)                 | Authenticated tenant and scopes precede business operations; bounded jobs retain outcomes                                 | [Tenant isolation](../tests/test_tenant_isolation.py), [SSO](../tests/test_sso_sessions.py), [jobs](../tests/test_operation_jobs.py)  |
| Human review and export      | [Control assurance](../src/security_lakehouse/control_assurance.py), [workpapers](../src/security_lakehouse/audit_workpapers.py) | Design, sampled operation, population completeness, and human review stay separate                                        | [Workpapers](../tests/test_audit_workpapers.py), [export verification](../tests/test_workpaper_export_validation.py)                  |
| Console and integrations     | [Console](../app/web/src/), [AI inventory](../src/security_lakehouse/ai_governance.py)                                           | Consumers present evidence and outcomes without inventing control truth                                                   | [AI inventory](../tests/test_ai_governance.py), [console worklist](../app/web/e2e/ai-worklist.spec.ts)                                |

### Trace one assessment end to end

1. A connector or imported file supplies raw observations with source and evidence
   references. Validate shape and retain collection-completeness information.
2. Normalize the observations into the selected tenant's lake. Bind evaluation
   to that platform tenant; retain source-account identity as provenance.
3. Evaluate versioned rules and reviewed safeguard mappings. Evaluate freshness,
   evidence types, and asset applicability; preserve unknown and missing states.
4. Stage and seal a generation, verify its artifacts, then publish the current
   pointer or distributed manifest. Readers use that committed generation.
5. Inspect a control's evidence and record the scoped assessment plan and
   population baseline. Build a workpaper from retained inputs; a passing sample
   and an incomplete population can coexist.
6. Export and verify the workpaper and snapshot chain. Keep human review pending
   until an authorized reviewer acts; retain integrity checkpoints separately.

Reproduce these steps with the [control workflow qualification](CONTROL_WORKFLOW_QUALIFICATION.md).
Its negative cases alter evidence, omit sampling windows, introduce conflicting
observations, and attempt foreign-tenant access and export tampering.

### Tradeoffs and operating limits

The filesystem mode offers inspectable artifacts and atomic generation changes,
but requires one writer and retention management. Distributed mode adds database
coordination and object storage; it does not split one tenant's evaluation across
workers. Evaluation materializes rows in memory. Graph caches trade memory for
repeat-read latency, and each process has its own cache. Hashes detect changes
relative to trusted retained records; they cannot establish provider truth or
survive an attacker deleting both history and every local checkpoint.

Use the [threat model](THREAT_MODEL.md), [measured workloads](BENCHMARKS.md), and
[deployment qualification](CURRENT_STATE.md) to assess these tradeoffs. Provider
permissions, representative load, backup recovery, and failover need evidence
from the intended environment before setting production objectives.

## Design Rules

- The evaluation engine must run without the UI.
- The UI must consume API/data contracts, not invent posture.
- Connectors may be added without changing controls.
- Controls may be added without changing connectors.
- Snowflake and ClickHouse are adapters, not hard dependencies.
- Point-in-time snapshots must be reproducible from their retained generation or embedded historical inputs.

### Assessment ownership and export boundary

Server evaluations bind the platform tenant from the authenticated request context
(or the hosted scheduler's tenant lake). A caller cannot override it with another
tenant ID. Source account IDs on normalized observations remain unchanged; they
are not the platform identity that owns the assessment. Local CLI evaluations
retain their explicit tenant ID and the default single-operator behavior.

Warehouse sinks currently use operator-owned process configuration. They are
therefore available only to local operator runs. Hosted connector materialization
and lake evaluation do not inherit those destinations or credentials. Hosted runs
at the warehouse threshold stop with the existing scale-policy error until a
tenant-scoped export destination contract is implemented. This boundary does not
qualify shared Snowflake or ClickHouse schemas for multi-tenant writes.

## Offline reports

`grc-lake dashboard --lake PATH --out REPORT.html` writes a frozen HTML report directly from the pinned lake
assessment. It renders coverage, findings, and expandable control results without
JavaScript, network access, or a console build. The embedded JSON preserves the
recorded assessment for further review; markup-like evidence is escaped without
changing its JSON values. Synthetic evidence remains labeled and sparse coverage
suppresses numeric readiness. The file presents saved results and does not refresh
freshness, authenticate evidence, or verify the ledger; use the verification tools
for those checks. The API-backed console remains available through `serve`.

## Durable operations and live reads

The API accepts bounded snapshot, evaluation, scheduler, and connector requests
into tenant-scoped durable operation rows. Acceptance supports an Idempotency-Key;
a conflicting request with the same key is rejected. Each server process runs a
bounded pool of workers (GRC_LAKE_OPERATION_WORKERS, default 2, at most 16) that
rotates claims between tenants and runs at most one job per tenant at a time, so a
long job does not block other tenants. Admission
serializes each tenant's count-and-insert and caps pending work at 100 operations.

Background execution uses a spawned process with an independent hard deadline
(default 900 seconds; GRC_LAKE_OPERATION_TIMEOUT_SECONDS must be positive and at
most 3600). The parent renews the claim and stops the child on shutdown, cancellation
or claim loss. A filesystem execution lock prevents stale-claim recovery while a
writer is still active. Interrupted work is not replayed: external or committed
side effects may already exist. Inspect domain history before submitting new work.
Queued cancellation guarantees the job was not claimed; cancellation overlapping
execution reports an interrupted outcome. Results and cancellation require the
owner or an administrator with the operation's current write scope.

SSE coalesces reads by tenant, database factory, and generation. Expensive work
holds only a per-key lock, allowing other tenants to build independently. A new
generation invalidates the key; same-generation freshness and database changes
may take up to 60 seconds to appear. The cache retains at most 32 entries, and
unused per-key locks are released. This reduces repeated computation without
claiming that a synthetic benchmark establishes production capacity.

Anonymous request audit belongs to the operator's server/security_audit directory;
authenticated records remain tenant-scoped. Recorded route templates omit path
parameters, including share tokens.

Successful JSON v1 responses declare the shared `data`, `meta`, and `errors`
envelope in OpenAPI, including endpoints that return JSONResponse directly.
Where a resource-specific model is absent, `data` remains generic: the envelope
schema is not a claim that every domain record is fully typed. Schema generation
is idempotent and preserves its input; binary and HTML routes retain their own
media types.
