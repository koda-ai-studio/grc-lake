# Bounded investigation graph measurements

The direct-function workload below and the [authenticated HTTP workload](#authenticated-loopback-http)
measure separate paths. Neither establishes production capacity or distributed fairness.

These synthetic local measurements exercise the production graph function on
normalized evidence files. They do not qualify HTTP admission, distributed job
fairness, authenticated providers, or production capacity. See
[#910](https://github.com/koda-ai-studio/grc-lake/issues/910) for the remaining
server and deployment qualification work.

## Workload

Each of two platform-tenant directories has two source accounts. The accounts
reuse both asset names and event IDs, while records bind to one of two distinct SOC 2 requirements.
Every fifth record fails; the others pass. One exact duplicate record is appended
per tenant and must not add a graph node. The full current catalog is included.
Input bytes and hashes, graph node counts by kind, returned node/edge counts, serialized
JSON sizes, hardware, source revision and configuration are retained in JSON.
Serialized bytes describe the direct response encoding, not HTTP wire traffic.

Each size/concurrency attempt starts a fresh process. It measures the first call
for each tenant, repeated reads, depths 1 and 3, layer filtering, search and root
pagination. Catalog and OS caches are not flushed; a later tenant can reuse
catalog state warmed by an earlier tenant. A round-robin burst submits reads for
both tenants to a bounded thread pool. Queue delay is that executor's delay,
not the server scheduler's. p50/p95/p99 use nearest-rank samples; small sample
counts do not establish tail-latency guarantees.

Every read checks the response bound, unique node IDs, no dangling edges and
platform-tenant isolation. Separate checks verify exact source-account record
bindings, duplicate handling, root-page disjointness, stale-version rejection,
operational-overlay version rejection, and a pinned read while another thread
publishes a new generation. Generations are sealed in legacy-compatible mode
with synthetic normalized records, not produced by a full collection/evaluation
pipeline. Pipeline measurements are a separate workload below.

## Resource and failure limits

The parent samples worker RSS and free disk every 250 ms. It kills and reaps the
worker at the configured memory, disk or wall-time bound, retains the stopped
attempt and completed-read receipts, removes only its temporary scratch tree,
and stops before increasing load. These are sampled watchdogs, not hard OS
allocation limits or reviewer-approved capacity budgets. Earlier development attempts remain in private local receipts; a timeout is
never a successful sample.

## Recorded results: October 12, 2026

Graph harness revision `1ab40fac8268c74bcb071a21ba27527e3da24488`; production graph code is unchanged from main `a13593ec`. [Raw graph receipts](investigation-2026-10-12.json) include all five final attempts.

Host: macOS 27.0.1 ARM64, Python 3.13.5, 10 logical CPUs, 16 GiB RAM, local filesystem. Other system applications and OS caches were not controlled. No other task-owned benchmark or cleanup ran during these final measurements.

| Unique records per tenant | Workers | Full model nodes per tenant | Read p50 seconds | Read p95 seconds | Worker peak RSS MiB | Correctness |
| ------------------------: | ------: | --------------------------: | ---------------: | ---------------: | ------------------: | ----------- |
|                     1,000 |       1 |                       4,605 |            0.152 |            0.170 |               142.2 | passed      |
|                     1,000 |       4 |                       4,605 |            0.640 |            0.872 |               169.6 | passed      |
|                    10,000 |       1 |                      24,405 |            0.807 |            0.901 |               362.1 | passed      |
|                    10,000 |       4 |                      24,405 |            3.486 |            3.629 |               429.6 | passed      |

Each successful row includes 12 concurrent read samples, six per tenant. The response limit was 150 nodes; returned edge counts and byte sizes are recorded per query. Peak RSS includes preparation, correctness checks, and retained Python allocations. More threads increased read latency on this host; these measurements do not establish a useful production concurrency limit.

The **100,000-record** attempt stopped at **180.1 seconds**, after 18 completed reads, with sampled peak RSS **1373.4 MiB**. The full workload and its post-read correctness checks did not complete. Concurrency 4 was not attempted at that size, and the process returned exit 1. This is a retained safety stop, not a passing 100k capacity result.

### Separate CCF pipeline workload

[Pipeline receipts](ccf-current-main-2026-10-12.json) were collected on production source `a13593ec` with development dependencies only: optional DuckDB and PyArrow were not installed. Three fresh processes per size preserved row counts, integrity and expected CCF outcomes/source-account boundaries. Medians were **1.361 seconds / 142.0–149.0 MiB peak RSS** at 1k events and **4.690 seconds / 263.7–264.5 MiB** at 10k. Pipeline elapsed time excludes fixture creation and post-run checks; RSS includes them. These results are not directly comparable to older all-extras runs and do not establish HTTP admission or concurrent evaluation capacity.

## Reproduce

```bash
uv sync --frozen --extra dev
uv run python tools/benchmark_investigation.py --sizes 1000 10000 100000 \
  --tenants 2 --concurrency 1 4 --repeats 3 --timeout 180 \
  --max-rss-mib 2048 --out /tmp/graph-measurements.json
uv run python tools/benchmark_assessment_pipeline.py --workload ccf \
  --sizes 1000 10000 --repeats 3 --base-time 2026-10-12T16:00:00+00:00
```

Use a new output path for each graph run. No provider credentials or real tenant
data are used. No graph index/cache design or production budget is approved by
these measurements. Further qualification needs HTTP-level concurrency and
scheduler fairness, representative topology shapes and reviewed workload budgets;
object-store failover and restore remain separate deployment exercises.

## Authenticated loopback HTTP

`--transport http` starts one Uvicorn server on an ephemeral loopback port inside
the watchdog worker. It creates a disposable SQLite database and synthetic
platform tenants with separate API keys. The production authentication,
rate limiter, tenant binding, graph route, and JSON response path are exercised.
Operator configuration is cleared inside that worker; no external databases or
provider accounts are used. No evaluation jobs are submitted.

Every measured request reads the first account's `asset-0` at depth 1 and checks
the exact evidence-record binding, duplicate suppression, response bounds, and
tenant/source-account isolation. Separate probes reject missing/invalid
credentials, foreign tenant roots, and a stale version after publication.
Each attempt measures a first request per tenant, a balanced burst, and a burst
with four submissions for tenant 0 per submission for every other tenant.
`--repeats 2` submits four requests per tenant in the balanced burst and
16/four in the two-tenant skewed burst. Completion order, per-tenant latency,
client executor delay, response-body bytes, CPU, and peak RSS are retained.
HTTP errors and timeouts fail the attempt and retain preceding measurements.

```bash
uv run python tools/benchmark_investigation.py --transport http \
  --sizes 1000 10000 --tenants 2 --concurrency 1 4 --repeats 2 \
  --timeout 180 --max-rss-mib 2048 --out /tmp/graph-http-measurements.json
```

Client and server share a process and host; CPU/RSS include both. Client queue
delay is not server scheduler delay, and finite bursts with a 4:1 submission
mix do not prove starvation freedom or job-queue fairness. Default rate limits
and thread-pool settings apply. The output records dependency versions and the
query configuration. Small sample counts do not establish tail guarantees.
Response-body bytes exclude HTTP headers. This workload does not qualify TLS,
remote network behavior, distributed admission, live-provider recovery, or
reviewer-approved production budgets. The parent watchdog kills the entire
worker, including the server thread, and removes only its temporary scratch tree.
