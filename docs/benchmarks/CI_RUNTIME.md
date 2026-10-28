# CI duration balancing

CI keeps six Python runners and two browser runners. Whole test files are
assigned deterministically to the currently lightest runner, longest estimated
file first. No test, retry, timeout, security gate, or required job is removed.
New files participate automatically using collected test counts and the measured
average time per test. Ordinary local runs are unchanged.

Before execution, each browser runner collects the complete Playwright inventory,
then collects its selected file filters again. The selected inventory must exactly
match the plan; collection errors and empty shards fail. The actual Playwright
exit status remains the job result. This guards against a passing partial selection.

## First hosted measurement

[Run 40556129241](https://github.com/koda-ai-studio/grc-lake/actions/runs/40556129241)
at source `730dc1dc452340c41c1d1c19eb09a3f9cf024795` completed the two
browser steps in 240 and 258 seconds (18 seconds apart). Retained plans select
174 and 223 tests: their disjoint union is all 397 tests across 75 files. Results
contain 396 passes, one skip, no unexpected failures and no flaky retries.

The overall run failed the documentation-index check because this new page lacked
an index link; it was not a passing full-CI result. This single browser measurement
supports improved balance, not a guaranteed workflow runtime. The subsequent
index-link fix leaves the scheduler and recorded weights unchanged.

## Measurement baseline

### Python weights averaged across complete runs (2026-10-27)

The current Python weights average two successful runs with identical inventories:
[release main 40612042954](https://github.com/koda-ai-studio/grc-lake/actions/runs/40612042954)
at `567620f8` and [documentation PR 40614562529](https://github.com/koda-ai-studio/grc-lake/actions/runs/40614562529)
at `b4131f30`. Each contains 7,399 Python cases across 510 modules, including
86 explicit skips. Averaging changes scheduling weights only; it does not change
skip policy, test selection, security gates, retries or timeouts. Browser weights
remain from the earlier hosted refresh below.

| Run                                                     | Full workflow elapsed | Python recorded-load spread before → after |
| ------------------------------------------------------- | --------------------: | -----------------------------------------: |
| Documentation PR 40614562529                            |                 8m04s |                            86.87s → 16.13s |
| Release main 40612042954                                |                 8m12s |                            95.62s → 16.02s |
| Separate candidate PR 40610959661, not used for weights |                 9m09s |                            35.20s → 31.89s |

These are replays of recorded case durations through the unchanged allocator,
not measured workflow improvements. On the separate candidate run, the largest
replayed load changes from 348.15s to 348.83s: better spread does not necessarily
mean a faster critical path. The documentation run's Python shard 2 spent 431s
in tests versus 331–357s for the other shards; its browser steps took 215s and 218s.
The release-main Docker job took 488s, including a 243s image build and 159s real
S3 qualification. Python scheduling alone cannot resolve that Docker bottleneck
or runner queue variability. Consistent sub-eight-minute CI remains unproven.

Use separate directories containing every `pytest-*/pytest-results.xml` artifact
from independently verified successful runs:

```bash
uv run --frozen python tools/update_test_durations.py --expected-reports 6 \
  --run-dir build/timings/first-run --run-dir build/timings/second-run
```

Each directory must have the declared shard count and the same complete test
identities. Failed/error cases, duplicate cases within a run, changed inventories,
repeated directory paths and missing shards reject the refresh before the existing
weights are replaced. Explicit skips remain visible. The importer cannot prove
that local files came from the named GitHub runs: verify source revisions and
successful workflow results before downloading. Single-run JUnit and Playwright
imports keep their existing command syntax.

### Hosted weight refresh (2026-10-27)

The earlier weights came from all six Python and both browser artifacts of
successful main [run 40597238111](https://github.com/koda-ai-studio/grc-lake/actions/runs/40597238111),
source `b834521604e9186b29f81c38394dbcf51291b1b8`. They contain 7,324 Python cases
across 507 modules and 398 browser cases across 75 files. The browser results
have 397 passes, one explicit skip, no unexpected failures, and no flaky retries.
These replace the earlier Python measurements and local browser estimates.

| Successful run                                                                          | Workflow elapsed | Largest job queue delay | Last verification dependency       | Test execution imbalance                      |
| --------------------------------------------------------------------------------------- | ---------------: | ----------------------: | ---------------------------------- | --------------------------------------------- |
| [Main 40597238111](https://github.com/koda-ai-studio/grc-lake/actions/runs/40597238111) |            7m30s |                     32s | Coverage, following Python shard 6 | Python steps 320–391s; browser steps 222–246s |
| [PR 40596499342](https://github.com/koda-ai-studio/grc-lake/actions/runs/40596499342)   |            8m10s |                     52s | Browser shard 2                    | Python steps 271–384s; browser steps 205–257s |

Workflow elapsed is `created_at` to `updated_at` for the completed CI workflow.
Queue delay is the largest job `created_at` to `started_at` interval, after its
dependencies become eligible; it excludes dependency execution time. The PR run
exceeded the target: browser shard 2 started after the web build and finished
52 seconds later than shard 1. These runs are not classified as cold-cache proof.

Replaying the existing allocator against those recorded case durations gives:

| Duration source                       | Python load spread before → after | Browser load spread before → after |
| ------------------------------------- | --------------------------------: | ---------------------------------: |
| Main refresh source                   |                    64.47s → 0.00s |                     21.62s → 0.15s |
| Separate PR run, not used for weights |                  107.25s → 28.08s |                     48.97s → 9.47s |

Load spread is the difference between the largest and smallest sum of recorded
case durations assigned to a shard. It excludes collection, setup, queueing,
shared fixture effects, and other jobs. This replay supports better allocation;
it is not a measured workflow speedup or proof of consistently sub-eight-minute
CI. The separate PR inventory contains 7,351 Python cases across 508 modules;
the allocator estimates newly added modules from their collected case count.
Both inventories remain complete and disjoint under the existing shard checks.
Issue #1111 remains open until repeated full PR/main runs, including cold/warm
cases, establish the runtime target without removing verification.

The Python timing importer rejects failed/error cases, inconsistent report
counts, duplicate cases, and invalid durations. Pass `--expected-reports` to
reject a missing shard before replacing weights. This count check does not
prove that supplied artifacts belong to the right run: verify the successful
source run and download every shard from that run. Explicit test skips remain
visible; refreshing timing weights does not change skip policy or test inventory.

The following successful runs used native browser sharding. Times are the
`Console Playwright smoke` step, not queue time or entire-job duration.

| CI run                                                                             | Browser shard 1 | Browser shard 2 |
| ---------------------------------------------------------------------------------- | --------------: | --------------: |
| [40515293336](https://github.com/koda-ai-studio/grc-lake/actions/runs/40515293336) |           252 s |           167 s |
| [40546672365](https://github.com/koda-ai-studio/grc-lake/actions/runs/40546672365) |           301 s |           159 s |
| [40548803542](https://github.com/koda-ai-studio/grc-lake/actions/runs/40548803542) |           291 s |           204 s |
| [40548974608](https://github.com/koda-ai-studio/grc-lake/actions/runs/40548974608) |           258 s |           196 s |

These show an execution imbalance, not proof that scheduling alone guarantees
an eight-minute workflow. Queue delay, runner availability, build time, and
individual slow files can still dominate. Evaluate complete workflow and individual
step times separately on subsequent runs.

The previous Python weights were regenerated from all six JUnit artifacts of successful
run 40548803542 (503 modules). The initial browser weights come from a complete local run of 397 collected tests (396 passed, one skipped)
against the console artifact from main run 40552460643; they are bootstrap
estimates, not CI performance proof. Browser weights are refreshed from the two retained
`e2e-timings-*` artifacts. Each contains the selected-file plan and Playwright JSON
results, including retry timings; artifacts survive failures for diagnosis and
expire after 14 days. Refresh weights only from successful complete runs.

```bash
uv run --frozen python tools/update_test_durations.py --expected-reports 6 build/junit/*/pytest-results.xml
uv run --frozen python tools/update_test_durations.py --format playwright --expected-reports 2 \
  build/timings/e2e-timings-1/results.json build/timings/e2e-timings-2/results.json
```

The refresh tool rejects duplicate browser cases, failed/incomplete reports and
invalid timing values. Timings affect allocation only; they never define the test
inventory. Retain the source CI run URL when updating recorded weights.
