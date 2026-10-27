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

## Measurement baseline

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

The Python weights were regenerated from all six JUnit artifacts of successful
run 40548803542 (503 modules). The initial browser weights come from a complete local run of 397 collected tests (396 passed, one skipped)
against the console artifact from main run 40552460643; they are bootstrap
estimates, not CI performance proof. Browser weights are refreshed from the two retained
`e2e-timings-*` artifacts. Each contains the selected-file plan and Playwright JSON
results, including retry timings; artifacts survive failures for diagnosis and
expire after 14 days. Refresh weights only from successful complete runs.

```bash
uv run --frozen python tools/update_test_durations.py build/junit/*/pytest-results.xml
uv run --frozen python tools/update_test_durations.py --format playwright \
  build/timings/e2e-timings-1/results.json build/timings/e2e-timings-2/results.json
```

The refresh tool rejects duplicate browser cases, failed/incomplete reports and
invalid timing values. Timings affect allocation only; they never define the test
inventory. Retain the source CI run URL when updating recorded weights.
