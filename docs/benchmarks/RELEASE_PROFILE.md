# Local graph release acceptance profile

This is a proposed regression budget for a bounded local pilot. Human review of
the limits and receipts is required before treating it as accepted. It does not
qualify production capacity, a deployment SLA, or all graph queries.

The profile uses two tenants with 1,000 and 10,000 synthetic records **per tenant**,
four concurrent closed-loop clients, the shipped cache and admission settings,
frozen catalogs, seed 910, and three repetitions of balanced and skewed bursts.
It then exercises 30 seconds of sustained 4:1 skewed traffic and rereads both
tenants after 61 idle seconds. The measured endpoint is an authenticated graph
neighborhood at depth one, limited to 150 nodes, over local SQLite. Client and
server run in the same process; RSS includes both.

| Check                                                                    | Proposed limit                                   |
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
The first run measured 132–143 ms successful warm p95 and 3.05–3.12 second cold
reads at 10k records per tenant, with 319.6 MiB peak RSS. Shared-host and OS-cache
effects remain uncontrolled. These are observations, not causal speedup claims.

At 100k records per tenant the [earlier measurements](INVESTIGATION_CACHE.md)
retained no models in the shipped cache and took roughly 14–16 seconds for reads.
That size is outside this interactive profile. The console's 500-node cap is not
a validated rendering budget. Full pipeline ingestion, larger neighborhoods,
browser rendering, external databases, shared-store workers and failover require
separate measurements. The earlier two-process memory receipt is informative,
not a shared-store deployment qualification.

Recheck this profile on the final release candidate. Keep published workload
limits and unresolved qualification gaps with the release evidence.
