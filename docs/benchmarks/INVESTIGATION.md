# Bounded investigation graph measurements

## October 18, 2026

These synthetic local measurements exercise graph correctness, memory, latency,
HTTP admission and cancellation. They do not establish production capacity,
deployment sizing, tail-latency guarantees or tenant fairness. [#910](https://github.com/koda-ai-studio/grc-lake/issues/910)
remains open for workload budgets and the remaining indexing/fairness work.

The [baseline receipts](investigation-baseline-2026-10-18.json) use clean source
`2926bf513d07e989687b0294880a328e7424c66d`. The
[updated direct](investigation-2026-10-18.json),
[HTTP](investigation-http-2026-10-18.json) and
[100k HTTP](investigation-http-100k-2026-10-18.json) receipts use clean source
`a4af812b2ca52588efc1bd03ed53281df2f9de24`. All retain source fingerprints, configuration,
input hashes, per-request results and resource observations.

Host: macOS ARM64, Python 3.12.13, 10 logical CPUs,
16 GiB physical memory and local filesystem. Browser workloads overlapped the
early baseline; later runs were quieter. OS caches and other applications were
uncontrolled. Latency differences are not a controlled speedup claim.

### Direct reads and memory

Two tenants, seed 910, three repeats per query and 12 burst reads per attempt.
All six attempts in each revision passed exact-binding, tenant/account collision,
duplicate, pagination, pinned-publication and stale/overlay-version checks.
Input hashes, model counts and every recorded response shape/size agree across
the revisions. RSS is the peak of the whole process, including setup and all
query shapes; it is not the incremental memory of one request.

| Records / tenant | Workers | Baseline peak MiB | Updated peak MiB | Baseline burst p95 s | Updated burst p95 s |
| ---------------- | ------- | ----------------- | ---------------- | -------------------- | ------------------- |
| 1,000            | 1       | 78.0              | 72.2             | 0.909                | 0.249               |
| 1,000            | 4       | 132.8             | 118.8            | 2.379                | 1.113               |
| 1,000            | 8       | 172.5             | 168.8            | 3.489                | 1.898               |
| 10,000           | 1       | 873.2             | 159.6            | 1.335                | 1.092               |
| 10,000           | 4       | 917.5             | 383.9            | 5.644                | 6.243               |
| 10,000           | 8       | 1176.2            | 668.3            | 10.559               | 11.966              |

The implementation hashes the same canonical graph encoding in batches of at
most 128 nodes or edges, releases temporary source rows before traversal, reuses
each event fingerprint and derives undirected neighbors from the two directed
indexes. It introduces no cross-request cache. A regression fixture with roughly
24 MiB of JSON used 74.2 MiB of fingerprint scratch memory before the change;
the new implementation passes a 2 MiB scratch bound for that fixture. This is
not a bound on all graph memory or arbitrarily large individual records.
Version tokens retain their existing encoding. Cancellation is checked between
hash batches; file reads and a single batch remain non-interruptible.

### Authenticated loopback HTTP

One authenticated Uvicorn process, scratch SQLite, the default four-build cap,
60-second server deadline and 75-second client timeout. The 1k/10k attempts use
two repeats and 28 balanced/skewed burst requests each; 100k uses one repeat and 14. p95 below includes only admitted burst requests and excludes client executor
queue time. Rejections are reported separately, never counted as successful-read
throughput. All seven attempts passed authentication, binding, duplicate,
foreign-root and stale-version checks, with no held admission slots afterward.

| Records / tenant | Clients | Admitted / submitted | Admitted burst p95 s | Process peak MiB |
| ---------------- | ------- | -------------------- | -------------------- | ---------------- |
| 1,000            | 1       | 28/28                | 0.319                | 145.9            |
| 1,000            | 4       | 28/28                | 1.255                | 191.8            |
| 1,000            | 8       | 12/28                | 1.654                | 184.5            |
| 10,000           | 1       | 28/28                | 1.304                | 228.6            |
| 10,000           | 4       | 28/28                | 9.749                | 417.5            |
| 10,000           | 8       | 8/28                 | 6.450                | 423.4            |
| 100,000          | 1       | 14/14                | 11.702               | 929.4            |

Every natural burst rejection was `503 graph_build_capacity`. The eight-client
attempts below use small fixed-order bursts: balanced submission is 1:1 and
skewed submission is 4:1. The global cap reserves no slots per tenant, so these
results are not a fairness guarantee.

| Records / tenant | Pattern  | Synthetic tenant | Submitted | Admitted | Capacity rejected |
| ---------------- | -------- | ---------------- | --------- | -------- | ----------------- |
| 1,000            | balanced | tenant-0         | 4         | 1        | 3                 |
| 1,000            | balanced | tenant-1         | 4         | 3        | 1                 |
| 1,000            | skewed   | tenant-0         | 16        | 7        | 9                 |
| 1,000            | skewed   | tenant-1         | 4         | 1        | 3                 |
| 10,000           | balanced | tenant-0         | 4         | 2        | 2                 |
| 10,000           | balanced | tenant-1         | 4         | 2        | 2                 |
| 10,000           | skewed   | tenant-0         | 16        | 3        | 13                |
| 10,000           | skewed   | tenant-1         | 4         | 1        | 3                 |

Natural 100k requests completed before the deadline. Separate injected probes
returned `503 graph_build_timeout` after 60.027 seconds
of a cooperative hold, and released the build slot 0.025 seconds
after a synchronized loopback socket disconnect. Recovery returned HTTP 200.
These timings test cancellation and recovery, not ordinary query performance.
The full 100k attempt took 285.7 seconds and peaked at
929.4 MiB. No proxy or cross-host disconnect was tested.

### Budget disposition

The observed single-client 10k p95 remains below the earlier proposed 2.5 seconds.
Concurrent p95 still exceeds that proposal. Memory is lower in these runs, but
the four-build setting is an admission limit, not a reviewed memory budget.
100k remains outside the proposed interactive workload. The graph still builds
the full model before selecting a neighborhood; per-read CPU cost grows with
evidence volume. A generation-scoped index and tenant admission policy require
separate design and correctness validation before stronger claims.

## Workload and reproduction

Two platform-tenant directories reuse a source-account ID, asset names and event
IDs, while evidence-record identity stays tenant-specific. Seed 910 chooses one
to three of seven SOC 2 controls per record, about 20% failures and four asset
types. One exact duplicate per tenant must not add a node. The full catalog is
included. Fixtures are sealed synthetic legacy-compatible generations, not live
provider collection or full-pipeline output.

Direct reads cover first/repeated calls, depths 1 and 3, layer filtering,
matching/nonmatching search, root pagination and safeguard control pagination.
Every response checks bounds, unique IDs, no dangling edges and tenant bindings.
Additional checks cover concurrent generation publication and stale versions.
OS caches are not flushed. Nearest-rank percentiles from these small samples do
not establish tail-latency guarantees. Pipeline measurements are separate in
[CCF_PIPELINE.md](CCF_PIPELINE.md).

Each attempt uses a fresh worker and temporary lake. The parent samples every
250 ms, retains failed/stopped attempts, removes its scratch tree and stops
escalation at the configured wall time, 4 GiB RSS or 5 GiB free-disk floor.
These are sampled watchdogs, not hard OS allocation limits. Use a fresh output
path for each run and adequate scratch storage.

```bash
uv sync --frozen --all-extras
uv run --frozen python tools/benchmark_investigation.py --seed 910 --tenants 2 \
  --sizes 1000 10000 --concurrency 1 4 8 --repeats 3 --timeout 900 \
  --max-rss-mib 4096 --out /tmp/graph-direct.json
uv run --frozen python tools/benchmark_investigation.py --transport http --seed 910 \
  --tenants 2 --sizes 1000 10000 --concurrency 1 4 8 --repeats 2 \
  --client-timeout 75 --timeout 900 --max-rss-mib 4096 --out /tmp/graph-http.json
uv run --frozen python tools/benchmark_investigation.py --transport http --seed 910 \
  --tenants 2 --sizes 100000 --concurrency 1 --repeats 1 --lifecycle-probes \
  --client-timeout 75 --timeout 2400 --max-rss-mib 4096 --out /tmp/graph-http-100k.json
```

## Historical receipts

Earlier runs remain available with their original revisions and limitations:

- October 15: [direct](investigation-2026-10-15.json),
  [HTTP](investigation-http-2026-10-15.json), [100k HTTP](investigation-http-100k-2026-10-15.json).
- October 13: [direct](investigation-2026-10-13.json),
  [100k direct](investigation-100k-2026-10-13.json),
  [HTTP](investigation-http-2026-10-13.json), [100k HTTP](investigation-http-100k-2026-10-13.json).
- October 12: [direct](investigation-2026-10-12.json), [HTTP](investigation-http-2026-10-12.json).

Earlier timeout/resource failures are retained; they are not successful capacity
samples. Python versions, source, admission behavior and host contention differ
across dates, so these are not interchangeable performance baselines.
