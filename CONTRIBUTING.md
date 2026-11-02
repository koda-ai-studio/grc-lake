# Contributing to GRC Lake

Thanks for helping. Bug reports, docs fixes, connectors, framework packs, and
console polish are all welcome. Issues labeled
[`good first issue`](https://github.com/koda-ai-studio/grc-lake/labels/good%20first%20issue)
are scoped to be finished in one pull request.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
[Governance](GOVERNANCE.md) explains roles and how contributors become
reviewers and maintainers ([current maintainers](MAINTAINERS.md)). Report
security problems privately, as described in [SECURITY.md](SECURITY.md), not in
a public issue.

Repository files, commit messages, issues and pull requests are public. Keep
private audits, working notes, chat transcripts and agent handoffs outside the
repository. Publish product changes, reproducible tests and sanitized examples.

## Find work

Read [current state and coverage](docs/CURRENT_STATE.md), then choose a scoped
[roadmap item](ROADMAP.md#choose-a-contribution). Check open PRs before starting.
Comment on the linked issue with your intended slice, or open an issue for an
untracked proposal. Each contribution should have a clear completion criterion
and public, synthetic reproduction steps. Provider access is optional for most
work; never share credentials or real evidence in an issue. For live integration
work, see [connector test accounts](docs/CONNECTOR_TEST_ACCOUNTS.md).

Ready-to-pick work:

- [Good first issues](https://github.com/koda-ai-studio/grc-lake/issues?q=is%3Aopen+label%3A%22good+first+issue%22):
  scoped connectors and presets that need no vendor account; fixtures are enough.
- [Help wanted: connectors](https://github.com/koda-ai-studio/grc-lake/issues?q=is%3Aopen+label%3A%22help+wanted%22+label%3Aarea-connectors):
  read-only evidence sources requested for common SOC 2 and ISO 27001 evidence, each
  with its target safeguard and done-when checklist. Issues labelled
  [`scaffold-ready`](https://github.com/koda-ai-studio/grc-lake/issues?q=is%3Aopen+label%3Ascaffold-ready)
  start from one command, `grc-lake connectors scaffold <id> --vendor <name> --into-tree`,
  which generates a working, tested Preview connector; you fill in the vendor's
  endpoint and field mapping ([quick start](docs/ADDING_CONNECTORS.md#quick-start-a-first-connector-in-about-30-minutes)).
- [Questions and ideas](https://github.com/koda-ai-studio/grc-lake/discussions):
  ask before you build if the scope is unclear.

Maintainers aim to give a first review within two business days of a pull request
that passes CI. If a review takes longer, comment on the pull request.

## Set up

You need Python 3.11 or later, [uv](https://docs.astral.sh/uv/), Node 22 or
later, and `make`.

```bash
git clone https://github.com/koda-ai-studio/grc-lake.git
cd grc-lake
make uv-sync               # uv sync --frozen --all-extras, same as CI
make pre-commit-install    # pre-commit and commit-message hooks
make web-install           # console dependencies (npm ci)
```

Run `make help` (or just `make`) to list commands and their descriptions. This
does not require Python or Node dependencies and does not start builds or tests.
Python targets run through `uv run --frozen python`, so Ruff, mypy and pytest
come from the lockfile rather than whatever is first on `PATH`. Set
`PYTHON=python` to use an already-activated interpreter instead.

Run the console against the sample company:

```bash
make demo-local            # builds the console, loads the golden fixture, serves :8787
```

Then open <http://127.0.0.1:8787/console/dashboard/>. Authentication is off in
this mode; it is for your machine only. After a console change, run
`make web-build` and restart the server to see it.

`make web-dev` starts the Next.js UI development server at
<http://localhost:5173/console/dashboard/>. It has no API proxy: relative `/api`
requests go to port 5173. Use `make demo-local` above when you need the working
console and Python API together.

If you only need the pre-built console, `docker compose up` runs the published
image with the same sample data; see the [5-minute tutorial](docs/TUTORIAL_5_MIN.md).

## Check your change

Run the checks that match what you touched before you push. CI runs all of them.

| Change                  | Command                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------- |
| Any Python              | `make lint format-check test`                                                         |
| One test file           | `python -m pytest -q tests/test_<name>.py`                                            |
| Catalogs, fixtures, API | `make smoke` (validation, pipeline, generated artifacts, API smoke, tests)            |
| Console (`app/web/`)    | `make web-ci` (install, typecheck, production build), `npm --prefix app/web run lint` |
| Docs images, brand      | `make validate-doc-images validate-brand`                                             |
| Helm, Terraform         | `make deploy-check` (needs `helm` and `terraform`)                                    |
| Everything, as CI does  | `make ci`, then `make pre-commit-run`                                                 |

CI partitions the complete collected Python suite into six groups, balancing
by recorded module duration while keeping each module's fixtures on one runner. To reproduce
a group locally, run `uv run python -m pytest -q -p tools.pytest_shard --ci-shard=1/6`
(replace `1` with the failing group). Ordinary `make test` still runs everything,
serially; a full run takes roughly 25 minutes on a recent laptop. The suite does
not use pytest-xdist, so `pytest -n auto` is not supported.

Install every extra (`make uv-sync`) to get the same verdict as CI. With only
`--extra dev`, tests that need an optional extra (the MCP server, FastAPI,
cloud SDKs) skip instead of failing. CI loads `-p tools.pytest_strict_imports`,
which turns those skips into failures so they cannot pass silently there. Repo-
wide checks such as the Markdown link check read only git-tracked files, so
local caches like `.terraform/` do not affect the result.
The required `smoke` check passes only when every group, the pipeline smoke, hooks,
and security scans pass; failures, cancellations, and skipped dependencies block it. Each group
retains a JUnit report and prints its slowest tests for diagnosing imbalance.

Ruff runs in `quality` and the history secret scan runs in `security`; CI skips
those duplicate pre-commit hooks and caches the remaining hook environments.
Local pre-commit still runs every hook. The security and Docker jobs start
without waiting for the web job; pipeline and browser tests consume its bundle. Python source tests start
independently; installed-wheel tests verify the real bundled console. Docker separately verifies the standalone image build and Compose
quickstart. CodeQL cancels superseded runs for the same branch or pull request.

Write the test first when you fix a bug or add behavior, and check that it
fails without your change. Tests assert on real output, not on "it ran".

For Compose or image changes, build locally with `docker build -t grc-lake:ci .`,
then run `python3 tools/compose_smoke.py --image grc-lake:ci`. Docker Compose
2.24.4 or newer is required. The check uses a fresh project and a dynamic loopback
port, recreates the demo container on the same volume, and removes its containers
and volumes afterward. It also validates the authenticated server profile with
synthetic configuration; it does not start that profile or contact cloud providers.
Diagnostics are saved in `build/compose-smoke/`; use `--output` with a new path
for each repeat so earlier failure evidence remains available. CI runs this check
inside the required `docker-build` job and retains its JSON result and container
log for 14 days, including when the check fails.

## Fuzzing

ClusterFuzzLite exercises strict JSON, raw evidence records, CycloneDX/SPDX
imports, and webhook signatures with Atheris. The pull-request workflow runs four targets independently for at least
75 seconds each; a weekly or manually dispatched batch spends
one hour across the targets. Failures retain crash reproducers, and batch runs
upload available SARIF results to code scanning. This is bounded testing, not a
claim that every input or native dependency is safe.

Replay the checked-in regression seeds without Docker or Atheris:

```bash
uv run --frozen python -m pytest -q tests/test_fuzz_targets.py
```

For coverage-guided local runs, follow the [ClusterFuzzLite Python
instructions](https://google.github.io/clusterfuzzlite/build-integration/python-lang/)
using `.clusterfuzzlite/Dockerfile` and `.clusterfuzzlite/build.sh`. Use a disposable
output directory and container; retain minimized crash inputs and remove the
container/build output after testing. Add a deterministic regression test for
any confirmed crash before fixing its parser or verifier.

See [CI duration balancing](docs/benchmarks/CI_RUNTIME.md) for browser shard
selection, timing artifacts, and the measured baseline.

## Commits and pull requests

- Branch from `main`. One logical change per pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/),
  enforced by the commitizen hook: `feat(connectors): add Jamf device evidence`,
  `fix(console): keep filters on reload`, `docs: explain mapping review`.
  Common types are `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, and `chore`.
- Fill in the [pull request template](.github/pull_request_template.md): what
  changed, why, and the commands you ran.
- Keep claims honest. Do not describe a framework, connector, or control as
  covered or live-verified unless the catalog, tests, and docs back it.
- The repository does not require a DCO sign-off.

### Human review before merge

Every pull request, including dependency updates and changes prepared with AI,
needs approval from a human other than the author before merging. Review the
latest changes, relevant tests, failure behavior, and security impact. Record
approval with GitHub's **Approve** review; a comment, passing CI, or an AI/bot
review does not substitute for that approval. After another push, obtain review
of the updated change before merging.

Keep one required human approval, required checks, stale-review dismissal, and
administrator enforcement enabled. The separate last-push approval rule is
disabled so a two-person team can collaborate on a branch and still review each
other's pull requests; authors cannot approve their own pull requests.
If no independent reviewer is available,
leave the pull request open. Do not use direct pushes or a protection bypass to
work around the missing review. See [Scorecard evidence](docs/SCORECARD_REMEDIATION.md)
for the distinction between current protection and historical review coverage.

## Add a connector

Connectors are read-only evidence collectors. Start with
[Adding connectors](docs/ADDING_CONNECTORS.md): the scaffold command, the
contributor checklist, event-log versus snapshot collection, and how to ship a
connector as a separate Python package. The [connector catalog](docs/CONNECTORS.md)
shows the contract every existing connector follows. Every connector needs a
fixture client, so its tests run offline.

## Add or extend a framework pack

Framework packs are JSON manifests. [Framework packs](docs/FRAMEWORK_PACKS.md)
covers the manifest schema, `make framework-packs`, and how to add a framework;
the [Common Control Framework](docs/COMMON_CONTROL_FRAMEWORK.md) explains how
safeguards map to requirements. New mappings start as `proposed`; only a
person who has checked the requirement text marks one `reviewed`
(see [mapping review](docs/MAPPING_REVIEW.md)).

## Repository layout

| Path                                    | Contents                                                      |
| --------------------------------------- | ------------------------------------------------------------- |
| `src/security_lakehouse/`               | Engine, API, auth, connectors, MCP server, CLI.               |
| `app/web/`                              | Next.js console.                                              |
| `controls/`, `frameworks/`, `mappings/` | Rules, framework catalogs, and mappings.                      |
| `mockup_companies/`                     | Sample companies used as fixtures.                            |
| `tests/`                                | Python tests.                                                 |
| `deploy/`, `compose.yaml`               | Deployment examples.                                          |
| `docs/`                                 | Guides; [architecture](docs/ARCHITECTURE.md) is a good start. |

## License

Contributions are accepted under the [Apache License 2.0](LICENSE), the
project's license.
