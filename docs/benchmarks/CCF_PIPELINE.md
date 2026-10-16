# Bounded CCF pipeline measurements

## Current measurements: October 15, 2026

[Raw CCF receipts](ccf-pipeline-2026-10-15.json) record nine successful attempts
on clean source `79dcb3eabb41429ab79a4d6336b2c1f74d461a82`. Production code and catalog match
`6b9de99c83023495f3e08c1623b590b1e9660e84`; the intervening commit changes graph
benchmark tooling and tests only. Host: macOS ARM64, Python 3.12.13,
10 logical CPUs, 16 GiB memory, local filesystem. No other task-owned test or
benchmark ran concurrently; OS caches and other applications were uncontrolled.
This runtime differs from the historical Python 3.13 run below, so the numbers
are not a controlled before/after comparison.

| Events / assets | Median pipeline seconds | Seconds range | Peak process RSS MiB | Retained generation MiB | Counts, labels, integrity |
| --------------- | ----------------------- | ------------- | -------------------- | ----------------------- | ------------------------- |
| 1,000           | 2.477                   | 2.314–2.988   | 263.1–263.9          | 24.8–24.8               | 3/3                       |
| 10,000          | 8.398                   | 8.000–8.781   | 402.6–404.5          | 103.8–104.0             | 3/3                       |
| 100,000         | 72.431                  | 69.577–73.495 | 1826.0–1840.4        | 839.5–839.5             | 3/3                       |

The workload and label checks are unchanged from the method below: seed 42,
one platform tenant, two colliding source tenants, and five equally sized
outcome cases. The evaluation clock is pinned to `2026-10-15T16:00:00+00:00`.
Each attempt starts a fresh process and temporary lake. All row counts, exact
asset/event verdicts and lake-integrity checks passed. Pipeline time excludes
fixture generation and post-verification; RSS includes them. The parent retains
failed attempts and stops escalation at 600 seconds, 4 GiB sampled RSS, or a
5 GiB free-disk floor. None of these limits was reached in this run.

```bash
uv sync --frozen --all-extras
uv run --frozen python tools/benchmark_assessment_pipeline.py --workload ccf \
  --sizes 1000 10000 100000 --repeats 3 --base-time 2026-10-15T16:00:00+00:00
```

### Local PostgreSQL and emulated S3

[Distributed receipts](distributed-2026-10-15.json) record four concurrent
synthetic tenants at 1,000 events each, using postgres (PostgreSQL) 16.14 (Homebrew),
Moto 5.2.3 over loopback HTTP and the same source
revision. PostgreSQL ran in an isolated temporary cluster over a private Unix
socket with TCP disabled. The benchmark created and dropped its own database;
the cluster was stopped and its temporary files removed after the run.

| Synthetic tenant | Publish (s) | Cold read (s) | Warm read (s) | Partition download (s) | Verified rows |
| ---------------- | ----------- | ------------- | ------------- | ---------------------- | ------------- |
| benchmark-0      | 7.276       | 0.390         | 0.056         | 0.011                  | 1000          |
| benchmark-1      | 7.297       | 0.378         | 0.064         | 0.009                  | 1000          |
| benchmark-2      | 7.308       | 0.360         | 0.062         | 0.010                  | 1000          |
| benchmark-3      | 7.272       | 0.394         | 0.055         | 0.010                  | 1000          |

The run verified 4,000 rows, completed
in 8.088 seconds and reported
632.5 MiB process peak RSS. That process includes
Python and the S3 emulator; PostgreSQL memory is excluded. A parent watchdog
bounded the run at 600 seconds, 4 GiB sampled process-group RSS and 5 GiB free disk.
All were below their limits. The receipt records PostgreSQL and client-library
versions. Conditional writes, publication, cold/warm hydration and partition
selection were exercised; this is one host with emulated S3, not real object-store
failover, multi-host HA, a tenant-isolation attack test, or production capacity.

To reproduce, point `TEST_POSTGRES_URL` at a disposable PostgreSQL instance whose
role may create and drop databases. Do not use a production database. The tool
creates a uniquely named database and drops it on exit.

```bash
uv run --frozen --all-extras --with 'moto[server,s3]==5.2.3' \
  python tools/benchmark_distributed.py --tenants 4 --rows 1000 \
  --out /tmp/distributed.json
```

## Historical measurements: October 3, 2026

Measured October 3, 2026 on clean source commit `a73a9b53d7d5dcca0584a79c5e52b3e72dbcce7d`.
These are synthetic local measurements, not production capacity or live-control
accuracy claims. [Raw corrected results](ccf-pipeline-2026-10-03.json) retain all
nine attempts, input hashes, source fingerprint, environment, and guardrails.

| Events / observed assets | Median pipeline seconds |   Seconds range | Peak process RSS MiB | Retained generation MiB | Counts, labels, integrity |
| -----------------------: | ----------------------: | --------------: | -------------------: | ----------------------: | ------------------------- |
|                    1,000 |                   3.668 |     3.627–3.745 |          269.8–276.7 |               30.0–30.0 | 3/3                       |
|                   10,000 |                  16.300 |   16.165–16.803 |          634.4–687.8 |             159.7–160.0 | 3/3                       |
|                  100,000 |                 166.911 | 141.607–267.414 |        2765.2–3002.3 |           1416.7–1417.2 | 3/3                       |

## Workload and method

One platform tenant, one explicit identity safeguard, three framework tags per
event, seed 42. Two source tenants deliberately reuse asset IDs. Each of five
cases contains 20% of events: pass, fail, unknown, stale, and absent safeguard
binding. Thus 100k events produce 80k asset/safeguard outcomes (20k each of pass,
fail, not evaluated, and stale); the remaining 20k assets lack a binding. Each
asset verdict and event ID is compared with the predefined label set. This does
not establish complete inventory or exhaustive safeguard/rule coverage.

The pipeline evaluation clock is pinned to `2026-10-03T16:41:01.796885+00:00`
so freshness labels remain stable between repeats. Real wall time and resource
watchdogs remain unmodified. Each attempt starts a fresh process and temporary
lake. Pipeline seconds exclude fixture generation and post-run verification;
peak RSS covers the worker, including those operations. Retained bytes include
all generation artifacts, including SQLite and DuckDB marts, and exclude raw
fixture intake outside the lake.

Host: macOS 27.0.1 ARM64, Python 3.13.5, 10 logical CPUs, 16 GiB physical memory.
No other task-owned test/build workload ran during these measurements; OS page
cache and other system applications were not controlled. Runs are sequential,
not cold-cache or concurrent-tenant capacity tests. Watchdog thresholds: 600 s,
4 GiB sampled RSS, and 5 GiB free disk, sampled every 250 ms. Temporary storage is
removed after each attempt. These thresholds are not hard OS allocation limits.

## Reproduce

```bash
uv sync --frozen --all-extras
uv run python tools/benchmark_assessment_pipeline.py --workload ccf --sizes 1000 10000 100000 --repeats 3 --base-time 2026-10-03T16:41:01.796885+00:00
```

Use the recorded source revision for exact fixture hashes. Preserve every failed
or bounded-out attempt. Stop before increasing load if a smaller size fails.
The pipeline remains memory-bound local Python evaluation; a configured warehouse
sink does not change that. Million-event, authenticated-provider, HTTP concurrency,
and cross-host HA behavior were not tested by this harness.

## Retained failed experiment

The [initial clock-dependent run](ccf-pipeline-initial-clock-2026-10-03.json) at
`2075679b1d8f7e40b9c36a15db461dd70d3b0ddb` passed eight attempts but failed the
third 100k label check. The elapsed experiment crossed a connector freshness
threshold: 2,857 expected passes correctly became stale. Counts and integrity
still passed. The harness had fixed labels but used a moving evaluation time.
A regression using an old fixture date reproduced this defect; the corrected
harness pins only the synthetic pipeline clock. The failed run is retained and
is not counted as a successful qualification or a before/after speedup baseline.

See the broader [validation protocol](../BENCHMARKS.md) for live-provider,
isolation, availability, and accuracy requirements.
