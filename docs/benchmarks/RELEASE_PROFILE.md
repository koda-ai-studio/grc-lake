# Local graph release acceptance profile

The maintainer accepted this bounded local pilot profile on October 25, 2026.
The decision is recorded in the linked receipt. It does not qualify production
capacity, a deployment SLA, or all graph queries; independent code review remains
a separate merge gate.

The profile uses two tenants with 1,000 and 10,000 synthetic records **per tenant**,
four concurrent closed-loop clients, the shipped cache and admission settings,
frozen catalogs, seed 910, and three repetitions of balanced and skewed bursts.
It then exercises 30 seconds of sustained 4:1 skewed traffic and rereads both
tenants after 61 idle seconds. The measured endpoint is an authenticated graph
neighborhood at depth one, limited to 150 nodes, over local SQLite. Client and
server run in the same process; RSS includes both.

| Check                                                                    | Acceptance limit                                 |
| ------------------------------------------------------------------------ | ------------------------------------------------ |
| First read and post-expiry read, each tenant                             | At most 5 seconds                                |
| Sustained successful-read p95, including client queue delay, each tenant | At most 500 ms                                   |
| Longest interval without a successful read, including window boundaries  | At most 2 seconds per tenant                     |
| Peak process RSS                                                         | At most 1 GiB                                    |
| Correctness and completion                                               | All required checks and both workload sizes pass |

Explicit `429 rate_limited` and `503` process/tenant admission rejections remain
visible as rejected requests, with their counts and admission fractions. They
are never successful reads. Transport errors, graph-build timeouts and other
HTTP failures fail acceptance. This profile does not promise an admission rate
under unlimited offered load. Latency distributions alone do not establish
throughput or fairness.

## Reproduce

Use a clean checkout, the frozen dependency environment and new receipt paths.
Run attempts sequentially without other task-owned builds or test suites.

```bash
uv run --frozen python tools/benchmark_investigation.py --transport http \
  --sizes 1000 10000 --tenants 2 --concurrency 4 --repeats 3 --seed 910 \
  --frozen-catalogs --sustained-seconds 30 --idle-seconds 61 \
  --timeout 900 --max-rss-mib 2048 --out /tmp/graph-profile-1.json
uv run --frozen python tools/check_performance_acceptance.py \
  --revision "$(git rev-parse HEAD)" /tmp/graph-profile-1.json
```

The 2 GiB watchdog is a safety stop; the acceptance limit is 1 GiB. Repeat with
new output paths and retain every result, including failures. The checker rejects
wrong revisions, dirty measured source, incomplete scopes and non-finite metrics.
It checks receipts; it does not itself rerun the benchmark or attest their origin.

## Evidence and limits

The [October 25 profile receipt](release-profile-2026-10-25.json) retains source,
configuration, host characteristics, raw receipt hashes and summarized outcomes.
Two initial sequential runs passed these limits. At 10k records per tenant,
successful warm p95 ranged from 67–143 ms, cold reads from 1.85–3.12 seconds,
and peak RSS from 319.6–415.9 MiB. Shared-host and OS-cache effects remain
uncontrolled. These are observations, not causal speedup claims. Raw receipt
hashes retain both attempts; faster later results do not replace the first run.

A third run on candidate `488dbc4cf7737ea3074f2d9854803c1eba1ede5c` also
passed, using Python 3.13.5 (the earlier runs used 3.12.13). At 10k records per
tenant, successful warm p95 was approximately 40 ms, first reads 1.15–1.18 seconds,
and peak RSS 457.0 MiB. Under sustained overload, admission fractions were 15.6%
for the hot tenant and 61.7% for the cold tenant; most rejections were explicit
rate limits. Both tenants completed more than 1,500 reads, with maximum success
gaps below 154 ms. At 1k records per tenant the overload admission fractions were
7.9% (hot) and 31.1% (cold). These observations do not promise that every submitted
request will be admitted or establish a speedup across Python versions or host
conditions. The acceptance decision was recorded at 18:57 UTC, on the two initial
runs; this third run was measured at 18:59 UTC, after it, and is supplementary
evidence rather than part of the approved basis.

At 100k records per tenant the [earlier measurements](INVESTIGATION_CACHE.md)
retained no models in the shipped cache and took roughly 14–16 seconds for reads.
That size is outside this interactive profile. The console's 500-node cap is not
a validated rendering budget. Full pipeline ingestion, larger neighborhoods,
browser rendering, external databases, shared-store workers and failover require
separate measurements. The earlier two-process memory receipt is informative,
not a shared-store deployment qualification.

Recheck this profile on the final release candidate. Keep published workload
limits and unresolved qualification gaps with the release evidence.
