# Bounded CCF pipeline measurements

## October 18, 2026

[Pipeline receipts](ccf-pipeline-2026-10-18.json) retain nine successful attempts
on clean source `a4af812b2ca52588efc1bd03ed53281df2f9de24`. Host:
macOS ARM64, Python 3.12.13, 10 logical CPUs, 16 GiB memory and local
filesystem. Runs were sequential, with no other task-owned test or benchmark
running concurrently; OS caches and other applications were uncontrolled.
These measurements do not establish production capacity or live-control accuracy.

| Events / assets | Median pipeline s | Seconds range | Peak process MiB range | Retained generation MiB | Counts, labels, integrity |
| --------------- | ----------------- | ------------- | ---------------------- | ----------------------- | ------------------------- |
| 1,000           | 2.265             | 2.263–2.663   | 262.5–263.5            | 24.8–24.8               | 3/3                       |
| 10,000          | 7.652             | 7.392–8.239   | 400.5–407.6            | 104.0–104.5             | 3/3                       |
| 100,000         | 65.845            | 65.562–67.238 | 1676.9–1840.5          | 839.5–840.0             | 3/3                       |

## Workload and method

Seed 42, one platform tenant, two source tenants that reuse asset IDs, one
explicit identity safeguard and three framework tags per event. Five equally
sized cases cover pass, fail, unknown, stale and absent safeguard binding.
100k events therefore produce 80k asset/safeguard outcomes (20k each of pass,
fail, not evaluated and stale); the other 20k assets lack a binding. Each asset
verdict and event ID is compared with predefined labels. This does not establish
complete inventory or exhaustive safeguard/rule coverage.

The evaluation clock is pinned to `2026-10-18T16:00:00+00:00`;
wall time and watchdogs remain real. Each attempt starts a fresh process and
temporary lake. Pipeline time excludes fixture generation and post-verification;
RSS includes them. Retained bytes include generation artifacts, SQLite and
DuckDB marts, and exclude raw intake outside the lake. The parent stops escalation
on failure, after 600 seconds, at 4 GiB sampled RSS or below 5 GiB free disk,
sampled every 250 ms. No limit was reached.

```bash
uv sync --frozen --all-extras
uv run --frozen python tools/benchmark_assessment_pipeline.py --workload ccf \
  --sizes 1000 10000 100000 --repeats 3 --base-time 2026-10-18T16:00:00+00:00
```

## Local PostgreSQL and emulated S3

[Distributed receipts](distributed-2026-10-18.json) exercise four concurrent
synthetic tenants at 1,000 events each on the same source revision, using
postgres (PostgreSQL) 16.14 (Homebrew) and Moto 5.2.3 over loopback HTTP.
PostgreSQL used an isolated UTF-8 temporary cluster, private Unix socket and disabled
TCP listening. The benchmark created and dropped its own database; the cluster
and temporary storage were removed after the run. An [initial SQL_ASCII bootstrap](distributed-setup-failure-2026-10-18.json)
failed during driver initialization before any workload measurement; it is not a
successful capacity sample.

| Synthetic tenant | Publish s | Cold read s | Warm read s | Partition download s | Manifest rows |
| ---------------- | --------- | ----------- | ----------- | -------------------- | ------------- |
| benchmark-0      | 13.831    | 0.683       | 0.098       | 0.020                | 1000          |
| benchmark-1      | 13.823    | 0.703       | 0.101       | 0.018                | 1000          |
| benchmark-2      | 13.857    | 0.671       | 0.100       | 0.022                | 1000          |
| benchmark-3      | 13.876    | 0.671       | 0.110       | 0.011                | 1000          |

All four publications matched the expected manifest count of 1,000 rows each.
Workload wall time was
15.038 seconds and Python/emulator peak RSS was
615.4 MiB; PostgreSQL memory is excluded.
An outer watchdog bounded the process group at 600 seconds, 4 GiB sampled RSS
and a 5 GiB free-disk floor; no bound was reached. Conditional writes,
publication, cold/warm hydration and partition selection were exercised.
This is one host with emulated S3, not real object-store failover, multi-host HA
or a tenant-isolation attack test.

To reproduce, set `TEST_POSTGRES_URL` to a disposable PostgreSQL instance whose
role can create/drop databases. Initialize the cluster with UTF-8 encoding.
The tool creates a unique database and drops it
on exit. Never use a production instance.

```bash
uv run --frozen --all-extras --with 'moto[server,s3]==5.2.3' \
  python tools/benchmark_distributed.py --tenants 4 --rows 1000 \
  --out /tmp/distributed.json
```

## Historical receipts and limits

- October 15: [pipeline](ccf-pipeline-2026-10-15.json) and
  [distributed](distributed-2026-10-15.json) measurements.
- October 3: [corrected pipeline](ccf-pipeline-2026-10-03.json) and
  [initial clock-dependent experiment](ccf-pipeline-initial-clock-2026-10-03.json).
  The latter crossed a freshness threshold: 2,857 expected passes became stale.
  Its failed label check is retained and is not a successful qualification.

Runtime, source, catalogs and host conditions differ across dates. A warehouse
sink does not change local Python evaluation into warehouse-side computation.
Million-event, authenticated-provider, cross-host HA and recovery behavior remain
outside these measurements. See [INVESTIGATION.md](INVESTIGATION.md) for graph
HTTP load and [the validation protocol](../BENCHMARKS.md) for broader qualification.
