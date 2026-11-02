# CI posture gate

Versioned examples below target the published v0.3.24 release. Artifact verification and release templates are linked from [release readiness](RELEASE_READINESS.md).

The posture gate is a GitHub Action that asks a GRC Lake deployment for its
current posture and failing control tests, and fails the job when they cross
the thresholds you set. Use it to stop a merge or a deploy when compliance
posture gets worse.

It lives in this repository at
[`.github/actions/posture-gate`](../.github/actions/posture-gate/action.yml),
so any repository can call it. It reads only; it never changes GRC Lake state.
Operational details (running the script outside GitHub, snapshots on a green
deploy, troubleshooting) are in the [CI posture gate playbook](playbooks/CI_POSTURE_GATE.md).

## Try it on sample data

[`examples/github-actions/grc-lake-golden-gate.yml`](../examples/github-actions/grc-lake-golden-gate.yml)
needs no deployment and no secrets. Copy it into `.github/workflows/` of any
repository. It installs GRC Lake on the runner, loads the bundled sample
company, serves it on loopback, and runs the gate twice: a ratchet gate that
passes at the sample's current numbers, and a strict gate that the last step
asserts has failed.

To run the same thing on your machine:

```bash
pip install "grc-lake[server]"
grc-lake fixtures load --company golden --out ./lake --rebase-times
grc-lake serve --server --allow-insecure-no-auth --lake ./lake --port 8787 &

# From a checkout of this repository (needs curl and jq):
GRC_LAKE_URL=http://127.0.0.1:8787 MIN_SCORE=70 ./tools/ci/posture-gate.sh
# exits 1: the sample company has a low score and failing control tests
```

## Gate a real deployment

Create an API key for a user with the `read_only` role (console
**Access → API keys**; see [server auth](SERVER_AUTH.md#api-keys)), then add two repository
secrets: `GRC_LAKE_URL` (for example `https://grc-lake.example.com`) and
`GRC_LAKE_API_TOKEN`. Copy this workflow into `.github/workflows/`:

```yaml
name: GRC Lake posture gate

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  posture:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Evaluate GRC Lake posture
        id: gate
        uses: koda-ai-studio/grc-lake/.github/actions/posture-gate@v0.3.24
        with:
          grc-lake-url: ${{ secrets.GRC_LAKE_URL }}
          api-token: ${{ secrets.GRC_LAKE_API_TOKEN }}
          min-score: "70"
          max-critical-violations: "0"
          max-failing-control-tests: "0"
      - name: Report
        if: always()
        env:
          SCORE: ${{ steps.gate.outputs.posture_score }}
          STATE: ${{ steps.gate.outputs.posture_state }}
        run: echo "GRC Lake posture ${SCORE} (${STATE})" >> "$GITHUB_STEP_SUMMARY"
```

The same file is checked in as
[`examples/github-actions/grc-lake-posture-gate.yml`](../examples/github-actions/grc-lake-posture-gate.yml).
The runner must reach `GRC_LAKE_URL`; for a private deployment, use a
self-hosted runner inside that network. For supply-chain safety, pin the
`uses:` line to the commit SHA of the release tag instead of the tag name.

The legacy `trustops-url` input remains accepted; `grc-lake-url` takes precedence when both are supplied.

## Inputs

| Input                       | Default         | Meaning                                                                         |
| --------------------------- | --------------- | ------------------------------------------------------------------------------- |
| `grc-lake-url`              | required        | Base URL of the deployment, no trailing slash.                                  |
| `api-token`                 | empty           | Bearer API key with read scope. Empty only for a local no-auth server.          |
| `correlation-id`            | `github.run_id` | Sent as `X-Correlation-ID`, so the run appears in the GRC Lake audit trail.     |
| `min-score`                 | `0`             | Minimum posture score, 0 to 100.                                                |
| `max-critical-violations`   | `0`             | Maximum open critical violations.                                               |
| `max-open-violations`       | `-1`            | Maximum open violations of any severity; `-1` skips the check.                  |
| `max-failing-control-tests` | `0`             | Maximum failing control tests after the allowlist; `-1` skips the check.        |
| `allowed-failing-controls`  | empty           | Comma-separated control IDs that may fail without failing the gate.             |
| `framework`                 | empty           | Only count failing control tests for this framework name (for example `SOC 2`). |
| `fail-on-stale-evidence`    | `false`         | `true` also fails the gate when any control has stale or expired evidence.      |

## Outputs

| Output                      | Meaning                                                   |
| --------------------------- | --------------------------------------------------------- |
| `posture_score`             | Posture score returned by GRC Lake.                       |
| `posture_state`             | Posture state label, for example `healthy` or `critical`. |
| `open_violation_count`      | Open violations at evaluation time.                       |
| `critical_violation_count`  | Open critical violations at evaluation time.              |
| `failed_control_test_count` | Failing control tests after the allowlist.                |

## Choosing thresholds

- **Ratchet.** Set each maximum to today's number and lower it as you fix
  things. The gate then fails only on regressions.
- **Known exceptions.** List a control in `allowed-failing-controls` while an
  approved exception is open, and remove it when the exception closes.
- **Per framework.** Use `framework` with the exact framework name GRC Lake reports
  (case-sensitive, for example `SOC 2`) to gate one program, for example a SOC 2
  audit window, without blocking on the others.

The gate needs `curl` and `jq` on the runner; GitHub-hosted Ubuntu runners
have both. It calls `GET /api/v1/posture/current` and, unless
`max-failing-control-tests` is `-1` and there is no allowlist,
`GET /api/v1/control-tests?result=fail`.

## Readiness summary action

The **GRC Lake Readiness** action is the repository's root [`action.yml`](../action.yml),
so a workflow calls it as `koda-ai-studio/grc-lake@<release>`. It ships starting with
v0.3.24. It reads `GET /api/v1/posture/current` once and writes a framework table to
the job summary, runs the same posture gate as above with the same threshold inputs,
and can keep one comment on the pull request up to date. It contacts only
`grc-lake-url` and, when commenting, the GitHub API of the run (`GITHUB_API_URL`).

```yaml
name: GRC Lake readiness

on:
  pull_request:

permissions:
  contents: read

jobs:
  readiness:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
      pull-requests: write
    steps:
      - name: GRC Lake readiness
        id: readiness
        uses: koda-ai-studio/grc-lake@v0.3.24
        with:
          grc-lake-url: ${{ secrets.GRC_LAKE_URL }}
          api-token: ${{ secrets.GRC_LAKE_API_TOKEN }}
          comment-on-pr: "true"
          min-score: "70"
          max-critical-violations: "0"
```

To try it with no deployment, copy
[`examples/github-actions/grc-lake-readiness-summary.yml`](../examples/github-actions/grc-lake-readiness-summary.yml),
which serves the bundled sample company on the runner's loopback.

The table has one row per framework: score, state, passing and total controls,
failing controls, controls not evaluated, and controls affected by a collection gap.
A framework counts as ready only when GRC Lake reports `ready` and every control
passes: a framework with a control that is not evaluated or affected by a
collection gap is never shown or counted as ready. When the lake holds the bundled
sample data, the summary opens with a synthetic data banner; collection gap sources
are named under the table; the gate result and its reasons close the summary. If the
deployment cannot be reached or returns an unusable response, the step fails and
writes no summary.

### Readiness inputs

| Input                       | Default         | Meaning                                                                                        |
| --------------------------- | --------------- | ---------------------------------------------------------------------------------------------- |
| `grc-lake-url`              | required        | Base URL of the deployment.                                                                    |
| `api-token`                 | empty           | Bearer API key with read scope. Empty only for a local no-auth server.                         |
| `correlation-id`            | `github.run_id` | Sent as `X-Correlation-ID`.                                                                    |
| `summary`                   | `true`          | Write the summary to the job summary. The file at `summary-path` is written either way.        |
| `comment-on-pr`             | `false`         | On a `pull_request` run, create or update one pull request comment with the summary.           |
| `github-token`              | `github.token`  | Used only when `comment-on-pr` is `true`; needs `pull-requests: write`.                        |
| `framework`                 | empty           | Show only this framework (exact name, for example `SOC 2`) and gate only its failing tests.    |
| `min-score`                 | `0`             | As in the posture gate.                                                                        |
| `max-critical-violations`   | `0`             | As in the posture gate.                                                                        |
| `max-open-violations`       | `-1`            | As in the posture gate.                                                                        |
| `max-failing-control-tests` | `0`             | As in the posture gate.                                                                        |
| `allowed-failing-controls`  | empty           | As in the posture gate.                                                                        |
| `fail-on-stale-evidence`    | `false`         | As in the posture gate.                                                                        |
| `enforce`                   | `true`          | `false` reports threshold failures as warnings in the summary and never fails the job on them. |

### Readiness outputs

| Output                       | Meaning                                                  |
| ---------------------------- | -------------------------------------------------------- |
| `posture_score`              | As in the posture gate.                                  |
| `posture_state`              | As in the posture gate.                                  |
| `open_violation_count`       | As in the posture gate.                                  |
| `critical_violation_count`   | As in the posture gate.                                  |
| `failed_control_test_count`  | As in the posture gate.                                  |
| `summary-path`               | Path of the rendered Markdown summary on the runner.     |
| `frameworks-ready-count`     | Frameworks in the summary that are ready.                |
| `frameworks-evaluated-count` | Frameworks in the summary, after the `framework` filter. |

### Pull request comment

With `comment-on-pr: "true"` on a `pull_request` (or `pull_request_target`) run, the
action looks for its own comment, identified by the first line
`<!-- grc-lake-readiness -->`, and updates it in place; if there is none, it creates
one. Grant `pull-requests: write` to the job only when you turn commenting on;
otherwise `contents: read` is enough. On any other event the comment is skipped with
a notice. The token is never printed. If GitHub rejects the comment (for example a
read-only token on a pull request from a fork), the step logs a warning and the job
summary and gate result are unaffected. A missing `github-token` is a configuration
error and fails the step.
