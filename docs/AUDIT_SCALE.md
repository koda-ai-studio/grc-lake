# Audit-scale ingestion, evaluation, and synthetic data

GRC Lake evaluates each tenant's evidence in a Python worker process. That process
can run on-premises or in the cloud. Distributed PostgreSQL/S3 mode adds multiple
API replicas and workers across tenants; it does not split one tenant evaluation
across workers or eliminate per-process memory limits. Optional warehouse export
also does not move evaluation into Snowflake, ClickHouse or DuckDB.

## Current scale boundaries

| Layer                | Current implementation                                                                                                          | Remaining limit                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Raw evidence         | Streaming JSONL input helpers and fingerprint-based incremental normalization                                                   | Upserts and evaluation still retain row/index state; memory grows with the tenant dataset                |
| Pipeline             | Incremental runs reuse unchanged bronze/silver rows, then rebuild gold and marts                                                | Full aggregate evaluation is not an incremental SQL warehouse workload                                   |
| Findings and posture | Default inline violation cap of 10,000, full totals and truncation metadata; dashboard detail capped at 100 rows per collection | Bounded responses do not make full evaluation bounded in memory                                          |
| Ingestion status     | Manifest-backed row counts and streaming field histograms                                                                       | Cold reads, old artifacts and large tenants still require work                                           |
| Distributed API      | Multiple replicas and readers with private scratch and bounded revision caches                                                  | Cache misses hydrate tenant artifacts; PostgreSQL primary and object-store capacity remain shared limits |
| Distributed workers  | Tenant shards, bounded concurrency, fenced publication and lease recovery                                                       | One tenant evaluation/write job at a time; one evaluation is not spread across workers                   |
| Synthetic fixtures   | Streaming generator and benchmark commands for bounded experiments                                                              | Generating one million rows does not prove the application can assess them within deployment limits      |

For larger datasets, project finding cardinality with `benchmark plan`, measure
full and incremental runs, and set explicit disk, memory and duration limits.
The 100,000-row policy below is a routing guard, not a measured capacity target.
See [distributed qualification](DISTRIBUTED.md#container-deployment-qualification)
and the [benchmark protocol](BENCHMARKS.md#4-volume-scale-and-performance).

## Synthetic data (audit-scale)

Generate reproducible raw evidence without live connectors:

```bash
# Project cardinality before generating
grc-lake benchmark plan --events 1000000 --controls-per-event 3 --open-ratio 0.12

# Stream 1M events (~360k findings at defaults) to disk
grc-lake fixtures synthesize-scale \
  --count 1000000 \
  --out /tmp/audit-scale/raw.jsonl \
  --controls-per-event 3 \
  --open-ratio 0.12 \
  --seed 42

# Materialize lake + timing
grc-lake benchmark pipeline --raw /tmp/audit-scale/raw.jsonl --out /tmp/audit-scale/lake
```

Controls are sampled from the active catalog. Each open event fans out to `controls_per_event` findings during evaluation.

## Integrity verification memory

Lake verification streams bronze and silver records. It retains hashes, event-ID
counts, and the sorted evidence-set metadata required by the existing digest
format; it no longer retains every parsed evidence payload. Memory still grows
with event count and the largest individual record. Evaluation and mart building
remain separate memory consumers. This optimization does not qualify the default
1 GiB Helm limit for a given dataset; measure the complete workload under its
actual container limit.

## Latency and throughput enhancements

### Incremental materialize (`pipeline.run_pipeline_incremental`)

When a prior `manifest.json` exists, incremental materialize:

- streams raw JSONL and compares each `event_id` fingerprint to `manifest.raw_index`
- upserts only changed/new rows into bronze/silver
- rebuilds gold/marts from the merged silver set (not a full raw replay of unchanged rows)
- records `materialize_mode`, `delta_count`, and `removed_count` on the manifest
- re-evaluates unchanged evidence when a freshness boundary is due
- rebuilds when rules, program settings, connector freshness policies, or the effective safeguard review overlay change

Use split schedules so connector sync stays ingest-only and lake eval runs less often:

```bash
grc-lake connectors configure \
  --lake /lake \
  --connector-id github-security \
  --state enabled \
  --sync-schedule "every 15m" \
  --eval-schedule "every 6h"

grc-lake pipeline eval --lake /lake
grc-lake scheduler tick --lake /lake
```

HTTP/API (same contract as UI, MCP, and agents):

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://grc-lake.example/api/v1/ingestion/eval -d '{"actor":"api"}'

curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://grc-lake.example/api/v1/scheduler/tick -d '{}'
```

MCP tools: `get_ingestion_status`, `list_eval_runs`, `run_lake_eval`, `run_scheduler_tick`, `sync_connector`, `list_connector_runs`.

### Evaluation routing at 100k events

`run_lake_eval` enters the warehouse tier when the larger of raw and silver row
counts is **at least 100,000**. Without an eligible sink, that path refuses the
evaluation. An operator-owned filesystem run can configure Snowflake, ClickHouse
or DuckDB, evaluate in Python, then export the committed generation. `local_result`
and `export_result` distinguish assessment publication from export success.
`gold/lake_scale.json` records the policy and `/api/v1/ingestion/status` exposes it.

Server-mode evaluation deliberately excludes process-wide sink credentials. It
therefore remains blocked at that threshold until tenant-scoped export destinations
are implemented. Adding distributed workers or setting a sink environment variable
on a server does not remove this guard. Direct pipeline/benchmark commands are a
separate entry point; their ability to run a dataset is not proof that the server
will accept it or that memory limits are safe.

### Streaming IO (`security_lakehouse.io`)

- `iter_jsonl` — line-at-a-time reads (no full-file `read_text`)
- `count_jsonl` — row counts without JSON parse
- `jsonl_field_counts` — histogram one field while streaming
- `iter_jsonl_batches` — chunked processing hook for future incremental pipeline stages
- `write_jsonl_from_iterable` — generator-friendly writes for synthesis

### Capped violation rollups (`security_lakehouse.assessment`)

- `build_violations(events=..., max_violations=N)` returns `(rows, summary)`
- `violation_summary` carries `total_count`, `severity_counts`, and `truncated`
- Posture payloads default to at most 10,000 inline violations; large-lake construction can also cap retained detail while preserving totals
- Framework scores use gold `control_posture` aggregates when violations are truncated

### Manifest row counts (`manifest.json`)

After each pipeline run, `row_counts` records bronze/silver/gold cardinalities so `ingestion/status` avoids full-file scans.

## Related docs

- [CONTINUOUS_INGESTION.md](CONTINUOUS_INGESTION.md) — connector loop and watermarks
- [HERO_DATA_LAKES.md](HERO_DATA_LAKES.md) — warehouse adapters and evidence readers
- [FRAMEWORK_COVERAGE.md](FRAMEWORK_COVERAGE.md) — active control catalog size

## Bounded dashboard and cold posture reads

Gold JSON documents are encoded incrementally into atomic temporary files;
JSONL artifacts retain every record. `gold/dashboard_data.json` keeps at most
100 rows per detail collection, with `detail_counts`, `detail_truncated`, and
`detail_limit`. Aggregates still cover the full input. Frozen HTML reports label
sampled control detail explicitly.

The dashboard also holds a compact asset projection (count, names, top ten) for
cold posture reads. Its source digest must match `gold/asset_risk.jsonl` before
reuse. Older lakes, changed source files, and dashboards over 16 MiB use a
streaming asset fallback. Assessment freshness, violation totals, scores, and
snapshot behavior retain their existing contracts.

An October 10, 2026 synthetic run on macOS ARM64 / Python 3.12, using
`fixtures synthesize-scale --count 100000 --seed 42` with two controls per event,
measured the following in separate fresh processes:

| Measurement           |    Before |     After |
| --------------------- | --------: | --------: |
| Pipeline wall time    |   60.07 s |   34.86 s |
| Pipeline peak RSS     |   2.25 GB |   1.59 GB |
| Total gold bytes      | 673.05 MB | 284.03 MB |
| Dashboard JSON        | 389.81 MB |   0.80 MB |
| Cold posture handler  |   10.75 s |    5.61 s |
| Cold posture peak RSS |   1.34 GB |   0.71 GB |

Sizes use decimal units. These are single local synthetic observations, not
production capacity or native AMD64 measurements. Cold handler timing excludes
HTTP transport; its response remains 5.33 MB with the existing inline violation
limit. Full evaluation still keeps raw and normalized events in memory.
