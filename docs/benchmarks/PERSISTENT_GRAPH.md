# Prepared investigation indexes

An investigation response contains a bounded neighborhood. The underlying inventory
can contain many more records, findings and assets; these are separate cardinalities.
A node limit alone does not bound the work needed to construct or traverse that inventory.

## Prepare before serving a large inventory

After publishing a generation with frozen catalogs, an operator can prepare its
investigation index outside the HTTP request deadline:

```bash
grc-lake graph prepare-index --lake /path/to/lake --timeout-seconds 1800
```

For an authenticated server, use the tenant's lake directory:

```bash
grc-lake graph prepare-index --lake /path/to/lake/tenants/TENANT_ID
```

The command infers the platform tenant from `tenants/TENANT_ID`; an explicit
`--tenant` must agree with that directory. When an application database is
configured, preparation reads that tenant's vendor assessments from the existing,
migrated database. It does not create or migrate application state. Source-account
IDs remain distinct from platform tenant IDs.

The command prints the graph version, node counts, index size and elapsed time.
Preparation reads recorded lake data; it does not contact providers or change
compliance results. The index is derived state in `.graph-index/` beneath the lake.
Keep that directory on a local filesystem that supports POSIX file locking.

The investigation endpoint uses a matching prepared index when normalized input
is at least 8 MiB. Missing or outdated large indexes fall back to the existing
in-memory graph path; an HTTP request does not start a large index build. Repeat
preparation after publishing a generation or changing triage, entity bindings,
vendor assessments, navigation catalogs or installed runtime code. Preparation is
explicit, not an automatic ingestion step. The existing request deadline and
per-process and per-tenant admission limits still apply.

## Integrity, concurrency and resource boundaries

Construction streams evidence through disk-backed scratch tables. A process lock
serializes preparation for one lake, and only a completed index is published.
Cancellation or a failed build does not publish a partial graph. Completed indexes
can be reused after a process restart; each read checks scope and input versions.
The stored graph version and response ordering match the existing builder.

The index identity includes the resolved lake, pinned generation, platform tenant,
vendor snapshot, input file versions and runtime code. Preparation verifies the
sealed generation. A separate receipt detects changed index bytes using hashes for
recent writes and filesystem change identity for settled files. This detects
accidental modification; it is not protection from an operator who can replace both
the index and its receipt. Credentials and filesystem access controls remain required.

The main database and SQLite temporary database each have a 16 GiB page ceiling;
preparation also checks a 2 GiB free-disk floor. These are independent guards, not a
guarantee that a workload fits or a combined disk quota. Database journals and
SQLite sorting files can use additional space. Preparation reserves a fixed 64 MiB scratch page cache to avoid repeatedly
reading uncached disk pages. Query connections use an 8 MiB page cache each; this is not a total process-memory bound. Legacy CCF generations without
a summary projection retain their original full JSON assessment read.

Unfiltered one-hop account and asset views use stored neighbor counts and bounded
selection. Filtered, deeper and control walks can visit many matching records in
SQLite even when the response contains only 150 nodes. They remain subject to the
request deadline. Search and offset paging can also cost more as inventories grow.
Prepared indexes do not establish end-to-end ingestion capacity, fairness across
replicas or a production latency guarantee.

To recover an unreadable index, stop preparation for that lake, retain diagnostic
information, and remove only `.graph-index/index.sqlite` and `.graph-index/index.json`
before running preparation again. Do not remove the lock file while another process
may be using it. Recorded generations remain the source of truth.

## Reproduce a bounded measurement

The harness varies evidence records, scoped assets and failing records independently.
It exercises authenticated loopback HTTP reads for an asset, an account, a deep
starting-point page and a two-hop control view. Two-tenant runs deliberately reuse
source-account and asset IDs and check returned evidence against the platform scope.

```bash
uv run python tools/benchmark_persistent_graph.py \
  --records 1000000 --assets 100000 --findings 1000000 \
  --tenants 2 --repeats 3 --timeout 1800 --max-rss-mib 1536 \
  --out /tmp/prepared-graph-result.json
```

Use a new receipt path for every attempt. The harness retains failed outcomes,
checks a 10 GiB disk floor, enforces a worker time/RSS bound and removes its temporary
lake afterward. Receipts separate preparation time from HTTP latency and include
source fingerprints. This fixture uses normalized synthetic evidence with frozen
catalogs; it does not run collection or the full evaluation pipeline. Increase to
a million distinct assets separately; a million records sharing fewer assets does
not demonstrate that asset cardinality.
