# Generation-scoped graph reuse measurements

The [local release profile](RELEASE_PROFILE.md) defines proposed repeatable
latency, memory and progress gates for the bounded 1k/10k workload.

## October 25, 2026: sustained traffic, expiry and process memory

The [bounded capacity receipt](investigation-capacity-2026-10-25.json) records
clean source `6268edbdc625f894859837dc6fabdb8376e54f32`, configuration, input
hashes, correctness checks, per-tenant outcomes and latency distributions. Full
local receipts are fingerprinted; individual read arrays are summarized in the
published receipt to keep its size bounded. All six attempts passed the harness
checks, including colliding source accounts, foreign roots and stale versions.

Measurements used a 10-core ARM64 macOS host with 16 GiB RAM, Python 3.12,
local SQLite and frozen synthetic catalogs. Benchmarks ran sequentially, while
interactive applications and Databricks trial setup were active. Two small SQL
regression runs overlapped the eviction measurement. Host load and OS caches
were uncontrolled; latency differences are not causal performance estimates.

Eight closed-loop clients ran for 30 seconds with approximately 4:1 hot/cold
tenant submissions. The p95 values below include only successful reads. Rejected
requests are reported separately and were not retried.

| Records / tenant | Hot admitted / submitted | Cold admitted / submitted | Hot / cold p95 seconds | Hot / cold maximum success gap seconds | Process peak RSS MiB |
| ---------------- | ------------------------ | ------------------------- | ---------------------- | -------------------------------------- | -------------------- |
| 1,000            | 1,075 / 5,189            | 883 / 1,303               | 0.122 / 0.125          | 1.060 / 1.077                          | 233.7                |
| 10,000           | 936 / 3,722              | 693 / 934                 | 0.144 / 0.145          | 0.188 / 0.245                          | 415.6                |

Both tenants made progress in these finite runs. The hot tenant received 3,629
and 2,127 `429 rate_limited` responses respectively; remaining rejections were
explicit process/tenant admission limits. A success gap includes the beginning
and end of the measured window. This is evidence of observed progress, not a
starvation-freedom guarantee or an approved admission policy.

After 61 seconds without reads, both tenants were read successfully again:
0.422–0.458 seconds at 1k and 1.978–2.070 seconds at 10k. The current cache uses
**60 seconds of idle time**, refreshed on access; expiration is checked lazily
on subsequent reads. The dated October 18 description below predates this
idle-expiry behavior. The final 128 MiB cache snapshot held two models totaling
23.3 MiB at 1k and 121.4 MiB at 10k.

A separate 64 MiB override at 10k retained one 60.7 MiB model. Four clients over
20 seconds admitted 63 of 139 requests, with tenant-capacity rejections for the
rest. Successful p95 was 3.463 seconds; post-idle reads took 5.432–6.786 seconds.
This exercises eviction and rebuild behavior but does not isolate eviction cost
from shared-host contention. The shipped budget remains 128 MiB.

At **100k records per tenant**, one client completed all reads with both shipped
and disabled caching. The shipped cache retained **zero models**. First reads
took 14.219–14.460 seconds, and balanced/skewed p95 was 15.333/15.784 seconds;
process peak RSS was 1,119.7 MiB. Disabled caching peaked at 996.2 MiB, with
balanced/skewed p95 of 17.301/30.707 seconds. These single noisy runs do not
establish a cache speedup: the workload exceeds retention and remains outside
the proposed interactive workload.

Two simultaneous independent HTTP workers, each with two 10k tenants and four
clients, passed their checks. Sampled aggregate RSS peaked at **670.4 MiB**, with
two processes observed concurrently. Each worker retained 121.4 MiB of model
objects. The measurement includes client/server memory in each process, uses
separate SQLite stores, and does not prove shared-store consistency, load-balancer
fairness, failover or a production memory budget.

Reproduce with new output paths; each command retains its full raw receipt:

```bash
uv run --frozen python tools/benchmark_investigation.py --transport http \
  --sizes 1000 10000 --tenants 2 --concurrency 8 --repeats 2 --seed 910 \
  --frozen-catalogs --sustained-seconds 30 --idle-seconds 61 \
  --timeout 900 --max-rss-mib 4096 --out /tmp/sustained.json
uv run --frozen python tools/benchmark_investigation.py --transport http \
  --sizes 100000 --tenants 2 --concurrency 1 --repeats 1 --seed 910 \
  --frozen-catalogs --timeout 900 --max-rss-mib 4096 --out /tmp/100k-cache.json
# Repeat the previous command with --disable-model-cache and a new output path.
uv run --frozen python tools/benchmark_investigation.py --transport http \
  --sizes 10000 --tenants 2 --concurrency 4 --repeats 1 --seed 910 \
  --frozen-catalogs --model-cache-mib 64 --sustained-seconds 20 --idle-seconds 61 \
  --timeout 900 --max-rss-mib 4096 --out /tmp/eviction.json
uv run --frozen python tools/benchmark_graph_replicas.py --rows 10000 \
  --replicas 2 --clients 4 --seconds 20 --timeout 900 --out /tmp/replicas.json
```

Reviewer-approved latency, rejection and memory budgets, representative tenant
mixes, and multi-host deployment qualification remain open in [#910](https://github.com/koda-ai-studio/grc-lake/issues/910).
The console's 500-node layout cap is an implementation limit, not a measured
capacity budget.

## October 18, 2026

These are synthetic local measurements of bounded model reuse, not production
capacity, a tenant-fairness guarantee or an approved latency SLO.

The [disabled-cache baseline](investigation-cache-disabled-2026-10-18.json) and the
[64 MiB experiment](investigation-cache-64-2026-10-18.json) use clean source
`f67217c5533a8963a11af695620be3167f2e1a73`. The [128 MiB direct](investigation-cache-128-2026-10-18.json)
and [128 MiB HTTP](investigation-cache-http-128-2026-10-18.json) runs use clean source
`ad513ef183a924227ac69da2c34a606e2dc08a2f`. Between these revisions, production code changes only
the retention budget from 64 to 128 MiB; the remaining changes are documentation
and response-equivalence tests. Every receipt retains configuration, revision,
source fingerprints, input hashes, individual reads, load averages and resource
observations. All 30 completed attempts across the five receipts passed their
correctness checks. The [64 MiB HTTP experiment](investigation-cache-http-64-2026-10-18.json) is also
retained, including rejections.

Host: macOS ARM64, Python 3.12.13, 10 logical CPUs, 16 GiB physical memory,
local filesystem. Runs were sequential, with no other task-owned benchmark or
test running concurrently. OS caches, other applications and host load were
uncontrolled. These are observed comparisons, not controlled tail guarantees.

## Direct reads

Two tenants, 1k/10k unique records each, seed 910, 1/4/8 worker threads,
three repeats per query and 12 burst reads per attempt. The fixture now freezes
requirement and safeguard catalogs, exercising the same cache eligibility as
published generations. It is still a synthetic normalized-evidence fixture,
not a full assessment pipeline or live-provider dataset. The legacy fixture mode
remains available and bypasses model reuse.

Input hashes, model counts, checks and every recorded response shape/size match
between disabled, 64 MiB and 128 MiB direct runs. Checks include exact record
bindings, source-account collisions across platform tenants, duplicate suppression,
root/control pagination, pinned publication and stale evidence/overlay versions.

| Records / tenant | Workers | Disabled burst p95 s | 128 MiB burst p95 s | Disabled peak RSS MiB | 128 MiB peak RSS MiB |
| ---------------- | ------- | -------------------- | ------------------- | --------------------- | -------------------- |
| 1,000            | 1       | 0.264                | 0.335               | 85.1                  | 102.8                |
| 1,000            | 4       | 1.079                | 0.101               | 134.0                 | 103.3                |
| 1,000            | 8       | 2.169                | 0.551               | 219.2                 | 109.9                |
| 10,000           | 1       | 1.093                | 0.117               | 164.0                 | 290.8                |
| 10,000           | 4       | 6.932                | 0.547               | 368.7                 | 297.3                |
| 10,000           | 8       | 9.662                | 0.762               | 681.2                 | 301.5                |

RSS covers the complete worker, including setup, retained cache and all queries.
The 1k single-worker burst was slower with reuse in this sample, so the
measurements do not show a uniform latency improvement. Retaining models raises
the single-worker baseline memory; avoiding simultaneous
rebuilds lowers the observed peak at higher concurrency. The 128 MiB retention
budget accounts reachable Python object sizes, not allocator overhead, in-flight
builds or total RSS. Each server worker has its own cache.

First-call and repeated-call medians below use the single-worker attempts.
First means the first graph call for each tenant; it is not a cold OS page cache.

| Records / tenant | Disabled first s | 128 MiB first s | Disabled repeat s | 128 MiB repeat s |
| ---------------- | ---------------- | --------------- | ----------------- | ---------------- |
| 1,000            | 0.250            | 0.324           | 0.251             | 0.020            |
| 10,000           | 1.079            | 1.490           | 1.064             | 0.060            |

A cold build adds retention-size accounting. Cache hits still scan the model to
select a neighborhood. A generation, triage, vendor or navigation change,
expiration or eviction can require another full build; the first-call cost must
not be represented as the warm-call cost.

## Retention sizing

The 64 MiB experiment could not retain both 10k tenant models. Alternating
single-worker requests therefore rebuilt models: burst p95 was
1.606 s, worse than the disabled baseline's
1.093 s. The 128 MiB limit admits both models in this
fixture while preserving an eight-entry limit, one model per lake, 60-second
maximum entry age and least-recently-used eviction. Larger or more varied tenant
workloads may still evict or bypass retention. Concurrent callers already waiting
on an oversized build can share its result without retaining it afterward.
These bounds are implementation limits, not reviewed deployment-sizing budgets.

## Authenticated loopback HTTP

One Uvicorn process, default four-slot admission, scratch SQLite and synthetic
API keys. Two repeats produce 28 balanced/skewed burst requests per attempt.
Requests exercise the authenticated tenant's exact colliding asset binding,
invalid/missing credentials, foreign roots and stale generation versions.

| Records / tenant | Clients | Admitted / submitted | Admitted burst p95 s | Process peak RSS MiB |
| ---------------- | ------- | -------------------- | -------------------- | -------------------- |
| 1,000            | 1       | 28/28                | 0.334                | 176.5                |
| 1,000            | 4       | 28/28                | 1.274                | 204.3                |
| 1,000            | 8       | 16/28                | 0.246                | 182.1                |
| 10,000           | 1       | 28/28                | 0.192                | 359.8                |
| 10,000           | 4       | 28/28                | 0.666                | 369.8                |
| 10,000           | 8       | 18/28                | 1.054                | 368.8                |

Only admitted burst reads contribute to p95. Every rejection was
`503 graph_build_capacity`; rejections are not successful graph reads. All
submissions answered and all admission slots released. Cache hits still take
an admission slot, and finite balanced/4:1 bursts do not prove fairness or
starvation freedom. These runs did not repeat 100k timeout/disconnect or
cross-host/proxy qualification; see the [earlier lifecycle measurements](INVESTIGATION.md).

## Reproduce

Use a fresh output path per run. Every attempt runs in a fresh process with a
900-second watchdog, 4 GiB sampled RSS bound and 5 GiB free-disk floor. Samples
are every 250 ms; these are safety stops, not hard OS allocation limits.

```bash
uv sync --frozen --all-extras
uv run --frozen python tools/benchmark_investigation.py --frozen-catalogs \
  --disable-model-cache --seed 910 --tenants 2 --sizes 1000 10000 \
  --concurrency 1 4 8 --repeats 3 --timeout 900 --max-rss-mib 4096 \
  --out /tmp/graph-cache-disabled.json
uv run --frozen python tools/benchmark_investigation.py --frozen-catalogs \
  --seed 910 --tenants 2 --sizes 1000 10000 --concurrency 1 4 8 \
  --repeats 3 --timeout 900 --max-rss-mib 4096 --out /tmp/graph-cache-enabled.json
uv run --frozen python tools/benchmark_investigation.py --transport http \
  --frozen-catalogs --seed 910 --tenants 2 --sizes 1000 10000 \
  --concurrency 1 4 8 --repeats 2 --client-timeout 75 --timeout 900 \
  --max-rss-mib 4096 --out /tmp/graph-cache-http.json
```

Use the recorded revision to reproduce the 64 MiB policy. Disabled mode bypasses
both retention and build coalescing. The default fixture without
`--frozen-catalogs` continues to measure legacy fallback behavior.

[#910](https://github.com/koda-ai-studio/grc-lake/issues/910) remains open for
reviewed budgets, representative workload/topology qualification and tenant
admission policy. Generation-scoped reuse reduces repeated construction work;
it does not provide a persistent neighborhood index or establish production scale.

## Navigation index follow-up

The paired [main baseline](investigation-index-baseline-2026-10-18.json) at
`ac2805f15722527f796275dc29e8059e3b1862ff` and
[indexed reads](investigation-index-indexed-2026-10-18.json) at
`6f7d2bac749a0e19907719ab0382f3fa144d8033` use clean committed source and
identical input hashes. Both retain the existing 128 MiB cache policy.
The latter also retains compact directed adjacency, counts, ordered roots,
default roots and edge positions with each generation model. All twelve attempts
passed the harness correctness checks.

These runs use the **uniform two-control fixture**, two tenants, frozen catalogs,
three repeats, 1k/10k records per tenant and 1/4/8 direct-read workers. They are
separate from the seeded mixed-control measurements above. Both ran on the same
10-core ARM64, 16 GiB macOS host with Python 3.12.13. Shared-host CPU load, OS caches
and allocation are uncontrolled; per-attempt load averages and every read are
retained in the raw reports. These are single paired runs, not statistical
confidence intervals, HTTP throughput or production capacity qualification.

| Records / tenant | Workers | Main burst p95 s | Indexed burst p95 s | Main peak RSS MiB | Indexed peak RSS MiB |
| ---------------- | ------- | ---------------- | ------------------- | ----------------- | -------------------- |
| 1,000            | 1       | 0.090            | 0.047               | 101.1             | 98.9                 |
| 1,000            | 4       | 0.281            | 0.089               | 101.3             | 103.3                |
| 1,000            | 8       | 0.442            | 0.174               | 99.7              | 101.6                |
| 10,000           | 1       | 0.221            | 0.040               | 274.5             | 285.3                |
| 10,000           | 4       | 1.596            | 0.182               | 284.8             | 280.6                |
| 10,000           | 8       | 3.218            | 0.463               | 309.9             | 247.2                |

Warm unfiltered reads avoid rebuilding adjacency and scanning all nodes/edges for
counts, root ordering and output edges. Layer filters still rebuild eligible
membership and degree ordering; search still scans indexed roots. Neighborhood
traversal and exact truncation counts still depend on the reachable graph.

Cold work is more expensive. First-call medians and complete workload wall times
below are from the single-worker attempts; first means the first graph call per
tenant, not a cold OS cache. The full workload includes first, repeated, filtered,
paginated and concurrent reads plus correctness probes that change generations
and overlays. It must not be replaced by a warm-only throughput claim.

| Records / tenant | Main first s | Indexed first s | Main repeat s | Indexed repeat s | Main total wall s | Indexed total wall s |
| ---------------- | ------------ | --------------- | ------------- | ---------------- | ----------------- | -------------------- |
| 1,000            | 1.218        | 0.908           | 0.035         | 0.012            | 10.107            | 8.160                |
| 10,000           | 2.109        | 3.602           | 0.179         | 0.025            | 22.888            | 32.199               |

Reproduce from each source revision using the same Python environment:

```bash
PYTHONHASHSEED=0 PYTHONPATH=src python tools/benchmark_investigation.py \
  --sizes 1000 10000 --tenants 2 --concurrency 1 4 8 --repeats 3 \
  --frozen-catalogs --timeout 180 --max-rss-mib 1536 --min-free-gib 1 \
  --out /tmp/investigation-index-result.json
```

The retention accounting includes the derived indexes and deduplicates shared
node and edge objects. Models that no longer fit are evicted or not retained;
the index change does not raise the cache budget. Total process RSS and active
builds remain outside that accounting. Existing model invalidation, cooperative
cancellation and per-process admission still apply.
