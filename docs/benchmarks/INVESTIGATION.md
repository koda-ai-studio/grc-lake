# Bounded investigation graph measurements

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

## Reproduce

```bash
uv sync --frozen --extra dev
uv run python tools/benchmark_investigation.py --sizes 1000 10000 \
  --tenants 2 --concurrency 1 4 --repeats 3 --out /tmp/graph-small.json
uv run python tools/benchmark_investigation.py --sizes 100000 \
  --tenants 2 --concurrency 1 4 --repeats 1 --timeout 180 \
  --max-rss-mib 2048 --out /tmp/graph-large.json
uv run python tools/benchmark_assessment_pipeline.py --workload ccf \
  --sizes 1000 10000 --repeats 3 --base-time 2026-10-12T16:00:00+00:00
```

Use a new output path for each graph run. No provider credentials or real tenant
data are used. No graph index/cache design or production budget is approved by
these measurements. Further qualification needs HTTP-level concurrency and
scheduler fairness, representative topology shapes and reviewed workload budgets;
object-store failover and restore remain separate deployment exercises.
