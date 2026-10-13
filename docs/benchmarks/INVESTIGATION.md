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

Since schema `grc.investigation_benchmark.v2`, the first source account ID
(`shared-account-a`) is identical in every platform tenant, so an asset root ID
is the same string in each tenant. Isolation is checked by exact evidence-record
identity: every returned evidence node must belong to the requesting tenant's
own synthetic records. `--seed N` replaces the uniform two-control shape with a
deterministic mix of seven SOC 2 requirements (one to three per record), about
20% failures and four asset types; the seed fixes the same topology for every
tenant. Omitting `--seed` keeps the original uniform shape. Receipts from
October 12 predate this and used tenant-prefixed account IDs.
Input bytes and hashes, graph node counts by kind, returned node/edge counts, serialized
JSON sizes, hardware, source revision and configuration are retained in JSON.
Serialized bytes describe the direct response encoding, not HTTP wire traffic.

Each size/concurrency attempt starts a fresh process. It measures the first call
for each tenant, repeated reads, depths 1 and 3, layer filtering, a matching and
a non-matching search, root pagination, and safeguard control pagination (first
and second five-control pages of one framework). The burst also records its
wall time and completed reads per second. Each attempt retains the host's load
averages before and after. Catalog and OS caches are not flushed; a later tenant can reuse
catalog state warmed by an earlier tenant. A round-robin burst submits reads for
both tenants to a bounded thread pool. Queue delay is that executor's delay,
not the server scheduler's. p50/p95/p99 use nearest-rank samples; small sample
counts do not establish tail-latency guarantees.

Every read checks the response bound, unique node IDs, no dangling edges and
platform-tenant isolation. Separate checks verify exact source-account record
bindings under the colliding account, that each tenant's identical root ID binds
a different record, duplicate handling, root-page and control-page disjointness, stale-version rejection,
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
tenant/source-account isolation. Since schema v2 that root ID is identical for
every tenant (colliding source account); the first requests must bind a
different, tenant-owned record per tenant. Separate probes reject missing/invalid
credentials, foreign tenant roots (the non-colliding account), and a stale version after publication.
Each burst also records wall time and completed requests per second.
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

### HTTP results: October 12, 2026

Clean harness revision `c6a6c22cf4e1ff348d4faab1e286f8a5b1ea4ef0`; application code is unchanged from main `96d6226a`. [Raw HTTP receipts](investigation-http-2026-10-12.json) retain all four attempts. The host is the same macOS ARM64 machine described above. No other task-owned benchmark or test suite ran during these measurements. Other applications and OS caches were uncontrolled.

| Records per tenant | Clients | Balanced p95 seconds, tenants 0 / 1 | Skewed p95 seconds, tenants 0 / 1 | Combined peak RSS MiB |
| -----------------: | ------: | ----------------------------------: | --------------------------------: | --------------------: |
|              1,000 |       1 |                       0.321 / 0.261 |                     0.322 / 0.314 |                 202.3 |
|              1,000 |       4 |                       1.088 / 1.083 |                     1.079 / 1.092 |                 233.2 |
|             10,000 |       1 |                       1.254 / 1.258 |                     1.275 / 1.264 |                 339.6 |
|             10,000 |       4 |                       5.423 / 5.193 |                     5.684 / 5.091 |                 519.9 |

All 120 timed requests across the four attempts returned HTTP 200 and passed the binding/isolation checks. All authentication, foreign-root, and stale-version probes passed. The bursts completed four/four balanced and 16/four skewed requests per attempt; no saturation or timeout was observed at these sizes. Error/timeout retention is exercised separately by injected-failure tests.

At 10k, four clients increased request latency and total attempt time: 41.8 seconds with one client and 42.9 seconds with four; these totals include setup, correctness probes, and shutdown. The four-sample tenant p95 values are sample maxima. Client queue distributions and completion timestamps are in the raw receipts. These observations do not set production budgets or demonstrate scheduler fairness.

## Recorded results: October 13, 2026

Schema v2 workload: colliding source account, `--seed 910`, two platform tenants.
Direct and 1k/10k HTTP receipts ran on clean harness revision `8112cd64`; the
100k HTTP receipt ran on `f7c93527`, which only stops a busy-server shutdown
from masking the request failure. Production graph code is unchanged from main
`87427fc4`. Each receipt records an empty working-tree diff and no untracked
sources. Host: macOS 27.0.1 ARM64, Python 3.13.5, 10 logical CPUs, 16 GiB RAM,
local APFS filesystem, legacy-compatible sealed generations, scratch SQLite for
HTTP. The host was shared with unrelated workloads that this harness did not
control. The one-minute load average was 7–23 during the direct 1k–100k
(1 and 4 worker) attempts and **30–38** during every HTTP attempt. Load is
retained per attempt.

Raw receipts:
[direct 1k/10k](investigation-2026-10-13.json),
[direct 100k](investigation-100k-2026-10-13.json),
[HTTP 1k/10k](investigation-http-2026-10-13.json),
[HTTP 100k](investigation-http-100k-2026-10-13.json).
Watchdogs: 4 GiB sampled RSS, 5 GiB free-disk floor, 900 s (1k/10k) or 2,400 s
(100k) per attempt; three direct repeats at 1k/10k and two at 100k.

### Direct graph function

| Records/tenant | Workers | Model nodes/tenant | Sequential read p50 / p95 s | Burst latency p50 / p95 s | Burst reads/s | Peak RSS MiB | Process CPU s | Retained disk MiB | Load avg (1 min) | Result                |
| -------------: | ------: | -----------------: | --------------------------: | ------------------------: | ------------: | -----------: | ------------: | ----------------: | ---------------: | --------------------- |
|          1,000 |       1 |              4,769 |                 0.21 / 0.23 |               0.19 / 0.23 |         5.192 |          154 |            14 |               1.1 |     12.8 to 11.7 | passed                |
|          1,000 |       4 |              4,769 |                 0.21 / 0.23 |               0.76 / 0.85 |         5.325 |          183 |            15 |               1.1 |     11.7 to 10.7 | passed                |
|          1,000 |       8 |              4,769 |                 0.21 / 0.23 |               1.49 / 1.81 |         4.569 |          203 |            15 |               1.1 |     10.7 to 10.2 | passed                |
|         10,000 |       1 |             26,340 |                 1.27 / 1.92 |               0.96 / 1.09 |         1.036 |          339 |            81 |              11.0 |     10.2 to 11.0 | passed                |
|         10,000 |       4 |             26,340 |                 2.69 / 5.03 |              9.52 / 10.77 |         0.402 |          570 |           109 |              11.0 |     11.0 to 23.3 | passed                |
|         10,000 |       8 |             26,340 |                 1.81 / 5.58 |              9.19 / 11.71 |         0.729 |          826 |           104 |              11.0 |     23.3 to 16.7 | passed                |
|        100,000 |       1 |            242,074 |               11.23 / 12.96 |              9.39 / 10.10 |         0.106 |        1,662 |           553 |             110.5 |      16.7 to 6.9 | passed                |
|        100,000 |       4 |            242,074 |                9.65 / 10.34 |             46.21 / 91.83 |         0.059 |        3,731 |           537 |             110.5 |      6.9 to 14.0 | passed                |
|        100,000 |       8 |            242,074 |               19.60 / 87.61 |                         — |             — |  4,097 (cap) |             — |                 — |     14.0 to 30.1 | stopped: RSS watchdog |

Sequential reads cover every query below for both tenants (56 at 1k/10k, 38
at 100k). Bursts are 12 reads at 1k/10k and eight at 100k, so p95 is a sample
maximum. Retained disk is the synthetic lakes, including tenant 0's replacement
generation; no graph-derived index is written. Every completed attempt passed
every check: response bounds, no dangling edges, tenant evidence identity under
the colliding account, exact bindings, duplicate suppression, root and control
pagination, pinned read during concurrent publication, stale-version and
overlay-version rejection.

Median single-worker latency by query shape, in seconds:

| Records/tenant | first | repeat | depth1 | depth3 | layers | search | search_miss | roots_page2 | controls_page1 | controls_page2 |
| -------------: | ----: | -----: | -----: | -----: | -----: | -----: | ----------: | ----------: | -------------: | -------------: |
|          1,000 |  0.22 |   0.21 |   0.21 |   0.21 |   0.18 |   0.19 |        0.17 |        0.19 |           0.19 |           0.19 |
|         10,000 |  0.98 |   1.12 |   1.14 |   1.15 |   1.06 |   1.40 |        1.50 |        1.27 |           0.97 |           0.94 |
|        100,000 | 10.94 |  11.23 |  11.69 |  10.83 |   9.96 |  11.75 |       10.05 |       10.31 |           9.52 |           9.47 |

Responses stay bounded. Typical reads return 150 nodes and 149 edges (about
125 KB of direct JSON); a search returns 150/295, a search miss 0/0 (about
630 bytes) and a control page 7/10 (about 9.5 KB). Cost tracks evidence volume,
not response size or query shape. A search with no match, or a seven-node control
page, costs the same as a full 150-node neighborhood. A repeated read is not
meaningfully faster than the first. This matches the known design: each request builds the
whole tenant model before selecting a neighborhood, with no cache.

### Authenticated loopback HTTP (contended host)

| Records/tenant | Clients | Balanced p50 / p95 s | Skewed p95 s, tenant 0 / 1 | Balanced / skewed req/s | Peak RSS MiB | Load avg (1 min) | Result                                    |
| -------------: | ------: | -------------------: | -------------------------: | ----------------------: | -----------: | ---------------: | ----------------------------------------- |
|          1,000 |       1 |          1.23 / 2.82 |                2.21 / 2.13 |           0.676 / 0.614 |          230 |     30.1 to 36.7 | passed                                    |
|          1,000 |       4 |          2.31 / 2.78 |                2.84 / 2.72 |           1.573 / 1.532 |          258 |     36.7 to 37.8 | passed                                    |
|          1,000 |       8 |          3.63 / 3.91 |                4.16 / 4.14 |           2.047 / 1.975 |          308 |     37.8 to 37.7 | passed                                    |
|         10,000 |       1 |          7.74 / 9.96 |                7.92 / 8.83 |           0.125 / 0.136 |          359 |     37.7 to 34.7 | passed                                    |
|         10,000 |       4 |        14.35 / 15.35 |              15.36 / 14.42 |           0.278 / 0.281 |          572 |     34.7 to 30.8 | passed                                    |
|         10,000 |       8 |        30.04 / 30.08 |                          — |                       — |            — |     30.8 to 30.6 | failed: all 8 balanced requests timed out |
|        100,000 |       1 |                    — |                          — |                       — |            — |     30.6 to 33.8 | failed: first request timed out           |

Single-client 10k latency was about six times the October 12 HTTP result on the
same machine (7.7 s versus 1.25 s), so these rows describe behavior under heavy
external CPU contention. They are not used for the budgets below. Every passing
attempt completed all submitted requests for both tenants (4/4 balanced, 16/4
skewed) and passed authentication, foreign-root, colliding-root and stale-version
probes.

### Saturation and failure behavior

- **Memory grows with concurrent builds.** Each additional concurrent graph read
  added about 70–77 MiB at 10k and about 690 MiB at 100k. Eight concurrent
  100k reads crossed the 4 GiB watchdog during the burst after all 38 sequential
  reads had passed. The attempt was killed, retained and stopped progression.
- **More workers did not add throughput.** Burst throughput was flat at 1k and
  fell at 10k and 100k (0.106 to 0.059 reads/s at 100k). Graph construction is
  CPU-bound Python in one process. Concurrency mainly increases latency and memory.
- **HTTP timeouts are collective, not partial.** At 10k with eight clients,
  all eight requests hit the 30 s client timeout together. No request was
  rejected with 429 or 503, and no request completed.
  At 100k, the first request timed out. The server kept computing the abandoned
  request. In the first 100k attempt on `8112cd64`, the loopback server could
  not stop within 10 s, and that shutdown error replaced the timeout in the
  receipt. `f7c93527` preserves the original failure; the published 100k
  receipt is the rerun.
- **No product correctness failure was observed** at any size or concurrency.
  Stops and failures were resource or time limits only. An earlier run on
  harness `620f83c8` failed closed at 1k because the harness's control-paging
  discovery read was itself capped at 150 nodes. `8112cd64` fixes that harness
  defect.

### Proposed budgets: measured, pending reviewer approval

These are proposals from the lower-contention direct measurements and the
October 12 HTTP results for this single-process local configuration. They are
not production capacity claims and are not approved.

| Budget                                | Proposed value                              | Evidence                                                                   |
| ------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------- |
| Interactive graph workload per tenant | ≤ 10,000 unique evidence records            | 10k single-worker read p95 1.92 s direct; 1.25–1.26 s HTTP on October 12   |
| Single-client graph read p95, ≤ 10k   | ≤ 2.5 s                                     | as above                                                                   |
| Concurrent graph reads per process    | ≤ 4, with peak RSS ≤ 1 GiB at ≤ 10k records | 570 MiB at 4 workers, 826 MiB at 8                                         |
| 100k records per tenant               | Outside the interactive budget              | Every query shape p50 9.5–11.7 s; 1.66 GiB for one read, 3.73 GiB for four |
| Concurrency or throughput claim       | None                                        | No throughput gain from added workers                                      |

Supporting 100k records per tenant interactively would require per-read cost to
decouple from evidence volume, for example the generation-scoped index or cache
in [#910](https://github.com/koda-ai-studio/grc-lake/issues/910). A bounded admission limit on concurrent graph builds would also be
needed to keep memory predictable. Neither is approved or implemented here.

### Reproduce

```bash
uv run python tools/benchmark_investigation.py --seed 910 --tenants 2 \
  --sizes 1000 10000 --concurrency 1 4 8 --repeats 3 --timeout 900 \
  --max-rss-mib 4096 --out /tmp/graph-direct.json
uv run python tools/benchmark_investigation.py --seed 910 --tenants 2 \
  --sizes 100000 --concurrency 1 4 8 --repeats 2 --timeout 2400 \
  --max-rss-mib 4096 --out /tmp/graph-direct-100k.json
uv run python tools/benchmark_investigation.py --transport http --seed 910 \
  --tenants 2 --sizes 1000 10000 --concurrency 1 4 8 --repeats 2 \
  --timeout 900 --max-rss-mib 4096 --out /tmp/graph-http.json
```

Run sizes separately so a stop at one size does not prevent the next. Use an
otherwise idle host for budget-grade numbers. Pass `--scratch` to place the
temporary lakes on a volume with enough free space.
