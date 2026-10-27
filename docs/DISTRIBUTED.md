# Distributed PostgreSQL and S3 mode

GRC Lake can run multiple API replicas and workers with independent local disks.
PostgreSQL coordinates ownership, application records, job claims and publication;
S3-compatible storage holds immutable evidence objects. This mode is part of OSS
and works for self-hosted or operator-hosted installations. Hosted billing and
signup features do not enable distribution by themselves.

Hosting can be on-premises or in a cloud VM/container/Kubernetes environment.
S3-compatible storage is a protocol requirement, not a requirement to host on AWS.
Compatibility with a particular object-store provider still needs qualification.
Source lakes such as ClickHouse or Snowflake remain separate read-only inputs;
see the [deployment and lake compatibility matrix](DEPLOYMENT.md#deployment-and-lake-compatibility).

## Deployment modes

| Mode                      | Durable state                        | Application topology                                            |
| ------------------------- | ------------------------------------ | --------------------------------------------------------------- |
| Local / small self-hosted | Local lake plus SQLite or PostgreSQL | One writable application replica; `Recreate` rollout            |
| Distributed API           | PostgreSQL primary endpoint plus S3  | Multiple API replicas with private scratch volumes              |
| Distributed worker        | Same PostgreSQL/S3 cluster           | Multiple worker processes, optionally assigned virtual shards   |
| Distributed reader        | Same PostgreSQL/S3 cluster           | Read traffic on a separate Service; tenant mutations return 405 |

A reader still writes authentication and request-audit records to PostgreSQL.
It is not a connection to a read-only PostgreSQL standby. Authentication callbacks
remain available. Local CLI commands do not implicitly publish to a distributed
cluster; use `cluster` commands or the authenticated API. MCP uses remote API mode.

## Shards, partitions and replicas

- **Virtual shards:** tenant IDs hash into 64 stable buckets by default, configurable
  from 1 to 4096 at cluster creation. PostgreSQL registers the shard count and object
  location; changing them on an existing cluster fails closed. Replica count does
  not change a tenant's shard or object keys. Shards route work, not PostgreSQL rows
  across multiple database servers. A tenant remains one consistency boundary.
- **PostgreSQL history partitions:** retained publication manifests use 32 physical
  hash partitions by tenant. A tenant/version lookup prunes to one partition.
  These database partitions are separate from the configurable virtual worker
  shards; they stay within one PostgreSQL cluster and do not add database servers.
- **Worker placement:** workers may claim all shards or an explicit comma-separated
  list using `cluster worker --shards 0,1,2`. Overlapping assignments are safe;
  database claims admit at most one running job per tenant. Claims use nonblocking
  per-tenant locks, so a busy tenant does not serialize unrelated workers. Reassign shard ranges
  by changing worker configuration. There is no automatic shard placement service.
- **Evidence partitions:** each published assessment also produces typed Parquet
  partitions by owning tenant, source and UTC event date. Original source-account
  IDs remain in the evidence rows. Paths encode the source with a digest; the
  manifest retains its original name, row count, size and SHA-256. Conversion uses
  bounded row batches. `cluster partitions` prunes source/date partitions before
  downloading objects. Existing JSONL and assessment APIs retain their contracts.
- **Application replicas:** API and worker pods may run on different machines and
  write different tenants concurrently. Same-tenant lake publication uses an
  expiring lease and a monotonically increasing fence; conflicting immediate
  mutations return 409. Workers wait up to 95 seconds for a busy tenant, covering the 90-second
  lease of a failed owner. A single tenant's
  evaluation is not split across workers.
- **Storage replicas:** PostgreSQL normally has one primary and operator-managed
  standbys; use its primary service endpoint. Object-store replication or erasure
  coding belongs to the S3 service. GRC Lake does not configure either system's
  failover, quorum or durability policy.
- **RAID:** configure it at the host/NAS/storage layer if appropriate. It neither
  coordinates application writers nor substitutes for backups.

## Publication and failure behavior

A worker restores the last committed tenant manifest into private scratch space.
It writes locally, uploads new content-addressed objects with conditional S3
writes, then atomically commits the new manifest pointer and domain SQL changes.
Unchanged verified objects reuse their existing references. Readers discover the
head through PostgreSQL, never an S3 listing or a pod-local pointer.

PostgreSQL checks lease expiry using its own clock. An expired or superseded fence
cannot publish. Upload failures and rejected HTTP mutations roll back domain SQL
and leave the old publication visible. Denied requests remain in the shared audit
sink. Scheduler attempt cadence is committed independently before execution, so
an abandoned publication does not erase an attempted workflow or connector run.
An interrupted job is not automatically replayed: external effects may already
have occurred. Review domain history before submitting a new idempotency key.

This is atomic publication of database state and object references, not a
transaction spanning external email, webhooks or warehouse providers. A network
failure after commit can make the response uncertain; retain the idempotency key
for supported asynchronous operations and inspect their status before retrying.

## Configure a cluster

Install `grc-lake[server,cloud,parquet]` or build the repository's Docker image.
Provision a dedicated PostgreSQL application database and an S3 bucket. One
database belongs to one cluster; sharing it between distinct cluster IDs is rejected. All replicas must share the same cluster
identity, database, bucket, endpoint, region, signing keys and connector secrets.
Credentials use the normal AWS SDK credential chain, including workload identity.

```bash
export GRC_LAKE_DEPLOYMENT_MODE=distributed
export GRC_LAKE_CLUSTER_ID=grc-primary
export GRC_LAKE_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@PRIMARY/grc_lake'
export GRC_LAKE_OBJECT_BUCKET=grc-lake-evidence
export GRC_LAKE_OBJECT_REGION=us-east-1
# For a self-hosted S3 service:
# export GRC_LAKE_OBJECT_ENDPOINT=https://objects.example.com
export GRC_LAKE_COOKIE_SIGNING_KEY='REPLACE_WITH_A_SHARED_RANDOM_SECRET'

grc-lake cluster init --lake /private/scratch
grc-lake serve --server --lake /private/scratch --host 0.0.0.0 --port 8787
# On worker nodes, with the same shared configuration:
grc-lake cluster worker --lake /private/scratch --concurrency 2 --shards all
```

`cluster init` migrates PostgreSQL and checks the bucket's conditional-write
behavior. Startup migrations are serialized by a PostgreSQL transaction lock.
The preflight needs Get/Put/Delete on `clusters/<id>/preflight/`; runtime data needs
Get/Put and multipart-upload permissions under `clusters/<id>/shard=*/`.
S3-compatible services must implement `If-None-Match: *` for PutObject and
CompleteMultipartUpload. Validate the specific provider before production use.
HTTPS is required for configured endpoints; only local testing should set
`GRC_LAKE_OBJECT_ALLOW_HTTP=1`.

Create users and tenant records using the existing authenticated onboarding or
`grc-lake db` commands. To migrate an existing tenant, first quiesce its old writer
and retain a backup of its application database and lake. The source must have a
verified sealed generation matching the existing target tenant ID:

```bash
grc-lake cluster import --lake /private/scratch --tenant-id TENANT_ID --source /old/tenant-lake
grc-lake cluster status --lake /private/scratch --tenant-id TENANT_ID
```

Import refuses a nonempty target publication and server/multi-tenant roots. It
preserves the source. Application identity records are not copied from SQLite by
this command; migrate those to PostgreSQL separately before switching traffic.

## Kubernetes profiles

The chart defaults to local mode. The distributed profiles require customer
Secrets: `grc-lake-database` containing `database-url`, and `grc-lake-signing`
containing `cookie-key`. Override the example cluster ID, bucket and endpoint.
Configure workload identity or supply S3 credential Secret references in `env`.

```bash
helm upgrade --install grc-api deploy/helm/grc-lake \
  -f deploy/examples/distributed/api-values.yaml
helm upgrade --install grc-workers deploy/helm/grc-lake \
  -f deploy/examples/distributed/api-values.yaml \
  -f deploy/examples/distributed/worker-values.yaml --set scheduler.enabled=false
helm upgrade --install grc-readers deploy/helm/grc-lake \
  -f deploy/examples/distributed/api-values.yaml \
  -f deploy/examples/distributed/reader-values.yaml --set scheduler.enabled=false
```

The profiles render two replicas, rolling updates, and bounded private `emptyDir`
volumes. No shared lake PVC is used. Worker deployments have no HTTP Service or
HTTP probes. Route browser/API mutations to the API Service; use the reader
Service for read traffic. Enable `scheduler.enabled` on one release; overlapping
scheduler pods are fenced per tenant. Deploy additional scheduler processes with
`grc-lake scheduler tick --all-tenants` when required. Tenant failures are isolated.
Readiness checks PostgreSQL, writable scratch and S3 bucket reachability. These
checks do not prove provider replication, multipart semantics or failover readiness.

## Query a partition subset

```bash
grc-lake cluster partitions --lake /private/scratch --tenant-id TENANT_ID \
  --source cloud-cspm --start-date 2026-05-01 --end-date 2026-05-31 \
  --out /exports/cspm-may
# For a local verified lake:
grc-lake pipeline export-parquet --lake /local/lake --tenant-id TENANT_ID \
  --partitioned --out /exports/all-evidence
```

Date bounds are inclusive UTC dates. Each downloaded file is checked against the
committed manifest; unavailable or corrupt objects fail closed. An empty match
produces a manifest with zero selected rows. Use the manifest's explicit file list
with an analytical engine; its source field is the original source name, whereas
the directory's `source_hash` component is a digest. Distinct column names prevent
Hive partition discovery from replacing the original evidence `source` values.

## Performance and capacity boundaries

The example resource requests are starting configurations, not certified capacity.
Measure cold reads, warm reads, concurrent writes, queue wait and failover against
your provider and tenant data before selecting production limits.

- Default runtime workspace limit: 20 GiB and 100,000 filesystem entries per tenant.
  The Helm profiles lower the byte limit to 512 MiB. Exceeding a limit fails before
  publication; it does not truncate evidence. Old retained generations count too.
- Each replica admits four workspace requests by default, configurable with
  `GRC_LAKE_WORKSPACE_CONCURRENCY` (1–64). Excess requests receive 503/Retry-After.
  Queue admission, polling and cancellation avoid downloading the tenant lake.
- Compatibility API reads materialize a tenant revision and make a private local
  copy. Each replica caches up to four tenant revisions with least-recently-used
  eviction; a new publication replaces only that tenant's cached revision.
  `GRC_LAKE_READ_CACHE_ENTRIES` sets the entry bound (1–64), and
  `GRC_LAKE_READ_CACHE_BYTES` sets the total cached payload-byte bound (defaults
  to `GRC_LAKE_WORKSPACE_BYTES` and cannot be smaller). Active readers retain
  private copies across eviction. This avoids repeated downloads when tenants
  alternate, but does not eliminate private-copy cost or reuse derived in-memory
  caches across requests. Cold reads and large tenants remain expensive.
  Partition downloads bypass full-lake hydration and prune objects by source/date.
- Evaluation still materializes rows in memory. More tenant shards increase
  concurrency across tenants; they do not make one evaluation distributed or
  bounded in memory. Worker concurrency is 1–16; isolated jobs have deadlines.
- Server-mode `run_lake_eval` retains the 100,000-row routing guard and excludes
  process-wide warehouse sink credentials. More replicas do not bypass that
  policy; tenant-scoped export destinations remain unimplemented. See
  [evaluation routing](AUDIT_SCALE.md#evaluation-routing-at-100k-events).
- Reserve scratch for the cache, active readers/writers, temporary Parquet export
  and free-space headroom. Keep the filesystem's capacity limit above that working
  set and monitor disk pressure. Node-local scratch is disposable.
- Request-rate limits are per replica unless the existing Redis limiter is
  configured. PostgreSQL/S3 alone do not turn them into cluster-wide quotas.
- Historical manifests and immutable objects are retained. Do not apply bucket
  lifecycle deletion to referenced objects. Automatic object garbage collection
  and automatic time-based partition rotation are not implemented.

### Queue fairness and backpressure

Evaluation, connector sync, scheduler ticks and snapshots use the durable
operation queue when submitted with `Prefer: respond-async` (as the console and
remote MCP do). See [operation contracts](OPERATIONS_CONTRACTS.md#background-http-operations).

- **Tenant turns:** select an eligible tenant whose last job started least
  recently, then its oldest queued job. Distributed dispatch uses PostgreSQL time
  and nonblocking per-tenant claim locks. A busy tenant is skipped rather than
  holding the claim lock for unrelated tenants.
- **One active job per tenant:** running and cancelling jobs exclude that tenant
  across distributed workers. Additional slots serve other tenants. This preserves
  same-tenant ordering and publication safety, at the cost of serial work for one tenant.
- **Bounded admission:** each tenant may have at most 100 queued, running or
  cancelling jobs. Excess new submissions return 409; a matching idempotent retry
  returns the existing job. Hydrated HTTP work has a separate per-replica workspace
  admission bound with 503/Retry-After. These are different limits.
- **Failure handling:** queued jobs survive restarts. Running jobs renew a
  90-second lease; bounded retries handle transient database writes. Interrupted
  execution is recorded and is not automatically replayed because provider or
  webhook effects may already have occurred. Supported cancellation and execution
  deadlines release capacity; cancellation does not roll back completed external effects.

This is fairness of **job starts**, not equal CPU time, weighted tenant priorities,
reserved capacity or a guaranteed maximum queue wait. Long jobs are not preempted
to give another tenant a turn; if all slots are busy, new tenants wait for a slot.
Shard-restricted workers are fair only among their eligible tenants, and every
active shard needs worker coverage. There is no global pending-job cap, weighted
fair queue or automatic tenant placement service. Synchronous callers and other
webhook producers do not acquire these asynchronous queue guarantees.

Validate with one tenant submitting a backlog, another running a long job, and
several occasional tenants. Measure queue-wait percentiles **per tenant**, oldest
queued age, completion throughput, active slots, rejected admission and interruption
counts. Verify small tenants continue to start work as slots free up, and repeat
with worker termination and transient PostgreSQL failure. Existing regression tests
cover turn rotation, admission races, long-job isolation, cross-replica claims,
cancellation and lease fencing; target-infrastructure latency and fairness under
sustained load remain separate qualification work.

### Tuning knobs and capacity budget

| Knob                                                                        | Shipped value / scope                                                      | Cost of increasing it                                                                                                                                                                                                  |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `replicaCount`                                                              | Local: 1; distributed example: 2 per release                               | Each pod adds database connections, scratch and a separate cache. Local mode rejects multiple writable replicas.                                                                                                       |
| `distributed.workerConcurrency` / `cluster worker --concurrency`            | Worker overlay: 1; CLI/chart default: 2; allowed 1–16 per worker process   | Concurrent tenant jobs multiply process memory and storage I/O; they do not parallelize one tenant evaluation.                                                                                                         |
| `GRC_LAKE_WORKSPACE_CONCURRENCY`                                            | 4 per API/reader replica; allowed 1–64                                     | More simultaneous hydrated workspaces and private copies; excess admission returns 503 with Retry-After.                                                                                                               |
| `distributed.workspaceBytes` / `GRC_LAKE_WORKSPACE_BYTES`                   | Helm: 512 MiB per tenant; unconfigured runtime: 20 GiB                     | Hard artifact-byte bound, not RAM allocation. Increasing it permits larger materializations and evaluation memory. The separate 100,000-file bound and server row guard still apply.                                   |
| `GRC_LAKE_GRAPH_BUILD_CONCURRENCY` / `GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS` | 4 builds per API/reader process, allowed 1–64; 60 s deadline, `0` disables | More simultaneous investigation-graph builds, each holding a full in-memory model; excess requests return 503 with Retry-After. See [Evidence investigation](INVESTIGATION_GRAPH.md#build-admission-and-cancellation). |
| `GRC_LAKE_GRAPH_TENANT_CONCURRENCY`                                         | Half the process graph limit, rounded down; minimum 1                      | Per authenticated tenant across all credentials. Allowed 1 through the process limit. Tenant saturation returns 503 / `graph_tenant_capacity`; equal limits disable protection against one tenant occupying all slots. |
| `GRC_LAKE_READ_CACHE_ENTRIES`                                               | 4 per replica; allowed 1–64                                                | More tenants may stay warm, subject to the byte bound. Useful only if repeated reads offset storage and copy costs.                                                                                                    |
| `GRC_LAKE_READ_CACHE_BYTES`                                                 | Defaults to workspace byte bound; must be at least that bound              | Total cached payload bytes, separate from active private copies. Four entries do not imply four full-sized tenants fit.                                                                                                |
| `distributed.scratchSize`                                                   | 20 GiB `emptyDir` in chart                                                 | A volume bound, not a capacity reservation or memory guarantee. Size node ephemeral storage too.                                                                                                                       |
| `distributed.virtualShards`                                                 | 64; allowed 1–4096 at cluster creation                                     | Placement granularity only. Immutable cluster identity setting, not an online throughput knob.                                                                                                                         |
| `rateLimit.redisUrl`                                                        | Empty by default; budgets are then per replica                             | Shared Redis adds cluster-wide rate accounting and an operational dependency; it does not shard data or coordinate lake writes.                                                                                        |

Budget scratch for the cache byte bound **plus** active workspace copies, in-flight
publications/exports and safety headroom. Budget worker RAM from measured peak RSS
per representative tenant job multiplied by concurrent jobs, plus parent/runtime
and API overhead. Artifact bytes and input row count are not reliable substitutes
for measured RSS. CPU throttling or out-of-memory kills can erase the benefit of
higher concurrency.

Change one limit at a time. If queue wait grows across many tenants while resources
are idle, test another worker. If one tenant is slow, profile its evaluation and
reduce the selected evidence scope where the assessment allows it; do not treat
more shards as a fix. If cold reads dominate, measure object-store latency and
cache hit rate before adding readers. Recheck latency, correctness, isolation and
recovery after every topology change. See [deployment tradeoffs](DEPLOYMENT.md#configuration-and-scaling-tradeoffs).

## Recovery and validation

Back up PostgreSQL with PITR and retain the referenced object versions together.
Losing only local scratch is recoverable by rehydration. Losing the authoritative
catalog cannot be repaired by guessing object order. Test restore with the same
cluster identity, storage location and signing keys before switching traffic.
Never let two independent PostgreSQL primaries govern the same cluster after a
split-brain event. Operator-managed fencing and failover are required.

The regression suite covers independent API roots, concurrent publication,
expired fences, database connection loss, failed SQL/file mutations, shared audit,
shard-restricted jobs, scheduler-attempt durability, reader isolation, concurrent
startup migrations, partition pruning and spawned-worker publication. Real
PostgreSQL and an S3 HTTP emulator run in the PostgreSQL CI gate. Emulator success
is not qualification of AWS S3, MinIO, Ceph or another production provider.

For a bounded, reproducible local measurement (requires a disposable PostgreSQL
URL in `TEST_POSTGRES_URL` with permission to create test databases):

```bash
uv run --all-extras --with 'moto[server,s3]==5.2.3' \
  python tools/benchmark_distributed.py --tenants 4 --rows 1000 \
  --out /tmp/grc-distributed-benchmark.json
```

This creates and removes its own test database and S3 emulator. The report
separates publication, cold/warm materialization and selected partition download,
and records process peak RSS and workload bounds. It does not measure networked
storage replicas or database failover.

## Container deployment qualification

Build the application image, then run the disposable qualification stack:

```bash
docker build -t grc-lake:qualification .
python3 tools/qualify_distributed.py --image grc-lake:qualification \
  --out /tmp/grc-qualification
```

The output directory must be new. The driver requires Docker Compose and Python
on the host; application dependencies run inside the built image. PostgreSQL 16
and SeaweedFS 4.48 images are pinned by digest. This is a real S3 implementation,
not the Moto emulator used by the smaller protocol tests. All services use a
private Docker network without published host ports, synthetic identities and
fresh disposable volumes. The driver generates temporary credentials and removes
them during cleanup; do not supply production credentials or data.

The run verifies conditional-create races, conditional multipart writes, two
shard-assigned workers, concurrent tenant jobs submitted through two API replicas,
a separate reader, cross-tenant job isolation and verified partition downloads.
It deletes one API replica's scratch volume, restarts dependencies, and kills a
writer before publication. It checks that SQL rolls back, unpublished files stay
invisible, an unexpired lease rejects a competing writer, and a new owner can
publish after the lease expires naturally. The disposable crash-writer process
uses a 20-second lease with a 5-second heartbeat, recorded in the qualification
receipt, to bound CI waiting time. The production 90-second lease and all other
qualification processes retain their defaults. It then restarts a worker and
runs another batch. Successful reads must agree on evidence hashes.

The required Docker CI job runs this qualification against its built image and
retains a sanitized report. The report identifies the application image digest.
This single-host stack qualifies application processes and the tested S3 protocol
behavior. It does not certify PostgreSQL primary failover, replicated SeaweedFS
storage, network partitions between physical machines, production backup recovery
objectives or production capacity. Operators must exercise those properties in their target
infrastructure before rollout.

The driver removes only its uniquely named project and volumes, including after
an assertion fails. If the driver is forcibly killed, use its recorded project
marker for bounded cleanup:

```bash
python3 tools/qualify_distributed.py --cleanup --out /tmp/grc-qualification
```

## Scaling and upgrade operations

Workers select at most 64 eligible tenant candidates per claim, using a persisted
last-start time rather than aggregating all historical jobs. Claims, fairness,
heartbeat renewal and lease recovery use PostgreSQL time, avoiding host clock
skew. Conditional updates preserve concurrent cancellation, and a
per-tenant lock still prevents overlapping execution. Recovery inspects at most
128 stale claims per poll; subsequent polls continue through the backlog. Audit
reads and tenant queue lookups use compound indexes aligned with their filters.

Migration `0029_distributed_scaling` converts retained PostgreSQL publication
history into 32 tenant hash partitions and adds the dispatch/audit indexes. SQLite
keeps ordinary tables. The conversion preserves rows, table ownership and effective
table/column grants; replacement child tables receive no default public grants.
Downgrading copies retained history back into an ordinary table without discarding
rows. This is physical partitioning within one PostgreSQL cluster, not routing
across independent databases.

Schedule a maintenance window, quiesce writers, back up PostgreSQL, and reserve
space for a second copy of retained history before this migration. It holds an
exclusive history-table lock while copying. Nonstandard row-security policies,
triggers, indexes or foreign-key/unique constraints on that table or its partitions cause a
transactional refusal so they are not silently discarded; reconcile those custom
schema extensions with the partition layout before retrying. Application-role
grants should be verified after an operator-managed schema upgrade.

## S3 checksum rejection

Amazon S3 documents `BadDigest` (HTTP 400) when a supplied checksum differs from
its calculated checksum. `InvalidDigest` is a malformed digest. The object-store
adapter's `BadDigest` handling matches that documented error code; this source
check is not a live AWS fault-injection result. See the official
[S3 error responses](https://docs.aws.amazon.com/AmazonS3/latest/API/ErrorResponses.html)
and [PutObject checksum contract](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html).

## Read-only recovery inspection

`grc-lake cluster inspect --tenant-id TENANT --lake /private/scratch` reads the
committed catalog and checks object bytes directly, bypassing replica caches.
It does not migrate the database, initialize cluster records, publish, repair or
delete evidence. Only disposable local download files are written.

The versioned JSON report identifies the catalog revision and manifest hash,
missing objects, integrity failures, storage/resource errors and unresolved jobs.
An available verified job receipt helps inspection; no job is replayed or marked
complete by this command. `ok` means the bounded object check passed;
`recovery_ready` additionally requires no unresolved running/interrupted jobs.
Neither field establishes control compliance or source authenticity.

Default limits are 10,000 objects, 1 GiB of attempted downloads, a 120-second
scheduling deadline and 100 detailed issues/jobs. Override with `--max-objects`,
`--max-bytes` and `--max-seconds`. Exhausted budgets explicitly report incomplete
inspection and return a nonzero exit code. An in-flight S3 request remains subject
to its configured socket timeout/retry budget. Each object's declared size is
reserved before download, including failed integrity checks; verified bytes are
reported separately. Inspection reserves 256 MiB of
scratch headroom and does not silently substitute a cached or older revision.

Writer lease loss is checked before assessment pointer publication, object uploads,
each multipart chunk, and final manifest publication. These cooperative checks
reduce wasted work; the PostgreSQL owner/fence/expiry check remains authoritative.
Unsupported explicit manifest schema versions fail before restoration writes.
Distributed HTTP failures distinguish writer conflicts, missing objects, integrity
failures, resource exhaustion and unavailable storage without exposing provider
exception text. Uncertain execution still requires result/history inspection.

## Qualification backup restoration

The existing `tools/qualify_distributed.py` built-image gate now also seeds
snapshots and durable operation receipts, stops API/reader/worker writers, captures
PostgreSQL plus every object referenced by retained catalog revisions, and removes
only its uniquely named qualification project's original volumes. It recreates
fresh stores, restores the coordinated backup and verifies revision identities,
evidence hashes, snapshot chains, operation receipts and cross-tenant denial.
A deliberately corrupt backup must fail validation before object restoration.

The report records the application image digest, quiesced checkpoint and measured
recovery seconds. It qualifies this single-host synthetic drill, not automatic
primary failover, production RPO/RTO, replicated storage or capacity. The host
retains sanitized reports; temporary database/object backups and credentials are
removed by the driver and its explicit cleanup command. Backup hashes establish
integrity relative to the recorded checkpoint, not independent authenticity.
