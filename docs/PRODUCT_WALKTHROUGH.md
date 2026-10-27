# Product Walkthrough

GRC Lake runs on infrastructure you operate: your laptop, a single host, or your
Kubernetes cluster. There is no managed service. This page gets the demo running
and maps each console page to the job it does. What is shipped versus planned
lives in the [roadmap](../ROADMAP.md).

## First run

| Step            | Command                                                                               | Result                                                                                                                                    |
| --------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Install         | `uv sync --frozen --extra dev --extra server`                                         | The `grc-lake` CLI and server dependencies.                                                                                               |
| Load the demo   | `uv run grc-lake fixtures load --company golden --out build/lakehouse --rebase-times` | Bronze, silver, and gold lake files, the SQLite mart, and synthetic demo tasks, risks, a policy, vendor assessments, and metrics history. |
| Check posture   | `uv run grc-lake assessment status --lake build/lakehouse`                            | Scores, failing controls, and findings in the terminal.                                                                                   |
| Freeze evidence | `uv run grc-lake assessment snapshot --lake build/lakehouse --reason vendor_review`   | An immutable `gold/snapshots/assessment-*.json`.                                                                                          |
| Open the app    | `make demo-local`                                                                     | The console at `http://127.0.0.1:8787/console/dashboard/`.                                                                                |

The demo fixture is synthetic and includes failing controls on purpose, so the
findings, evidence, and remediation pages have something to show. `make
demo-local` disables authentication; a shared environment needs
[server auth](SERVER_AUTH.md).

## Console map

The navigation follows the flow: collect evidence, evaluate it, resolve what
fails, then review and export.

| Group           | Page           | What you do there                                                                     |
| --------------- | -------------- | ------------------------------------------------------------------------------------- |
| Overview        | Overview       | Read the assessment score, control pass rate, open findings, and evidence to refresh. |
| Overview        | Insights       | Follow posture and findings trends over time.                                         |
| Collect         | Connections    | Connect a read-only source: test, enable, sync.                                       |
| Collect         | Evidence       | Inspect normalized evidence rows and verify each row's hash.                          |
| Governance      | Access reviews | Run access certification campaigns.                                                   |
| Governance      | Vendor risk    | Record vendor questionnaires and assessments.                                         |
| Evaluate        | Controls       | See each control's result and the evidence behind it.                                 |
| Evaluate        | Frameworks     | Check requirement coverage and readiness gates per framework pack.                    |
| Evaluate        | Mapping review | Approve, reject, or send back safeguard-to-requirement mappings, with a logged trail. |
| Resolve         | Findings       | Triage failing checks: assign, set a due date, record a note.                         |
| Governance      | Risk register  | Track risks with severity, owner, and status.                                         |
| Governance      | Policies       | Publish policies from templates and collect acknowledgments.                          |
| Governance      | AI governance  | Review AI assets and their governance controls.                                       |
| Evaluate        | Crosswalk      | Compare how requirements line up across frameworks.                                   |
| Evaluate        | Graph          | Trace framework → control → evidence → asset paths.                                   |
| Resolve         | Remediation    | Work tasks, evidence requests, and exceptions.                                        |
| Resolve         | Workflows      | Build and run automation on a canvas.                                                 |
| Resolve         | Agents         | Review agent runs and approve or reject their proposed decisions.                     |
| Review & export | Audit room     | Check audit readiness, freshness SLAs, snapshots, and blocking gaps.                  |
| Review & export | Trust center   | Share scoped, expiring views with auditors and customers.                             |
| Review & export | Audit log      | Read the record of who did what.                                                      |
| Settings        | Access & keys  | Manage users, invitations, and API keys.                                              |
| Settings        | Deploy         | Deployment guidance for your environment.                                             |

## Five-minute tour

These steps use the synthetic source demo, including deliberately failing checks.
The screenshots are captured from the 0.3.17 candidate; use the release notes
for the version you install.
Framework marks and control-family icons retain the same identity across
overviews, review workspaces and the graph. Provider marks identify recorded
sources; none of these marks implies certification or vendor endorsement.

1. **Overview → Sources & operations:** inspect a source's recorded outcome and
   open its evidence. A successful access test is separate from a successful sync.
2. **Findings → Inspect:** read impact, linked controls and evidence, then the
   suggested next action. Triage does not change the underlying verdict.
3. **Graph → Evidence investigation:** select a starting point, inspect an exact
   record, then double-click or press Shift+Enter to explore. Try depth controls,
   Expand graph workspace and Roll up. The graph shows recorded relationships.
4. **AI governance → Inspect:** compare a model's owner, environment, signals
   and next action. Follow its linked controls, open its filtered evidence and
   clear the asset filter to return to the evidence list.
5. **Access reviews → Audit room:** inspect pending review requirements, then
   assessment freshness and gaps. Approval needs an eligible human session;
   a no-auth synthetic demo cannot establish that authority. Export or share only
   the intended assessment scope.

[Current coverage](CURRENT_STATE.md) separates fixture tests, live qualification,
reviewed mappings and measured capacity. Refresh screenshots with
`make demo-screenshots` against the same built source and synthetic lake.

## Additional views

Open the [control families](images/grc-lake-demo-control-families.png) and
[crosswalk](images/grc-lake-demo-crosswalk.png) captures to inspect the taxonomy
and mapping views. The [README](../README.md#product-tour) highlights evidence
investigation and the AI asset worklist.

## Hosted live demo

The [live demo](https://koda-ai-studio.github.io/grc-lake/) is this console as
a static site on GitHub Pages. It replays API responses recorded from the
golden fixture, so it needs no server and stays read-only: writes show a
read-only notice, the live stream is off, and a view the recorder did not
capture says it is not available in the demo. A banner shows when the
snapshot was recorded. Relative times age from that date.

The `pages` workflow rebuilds it on every push to `main` and weekly. To
reproduce it locally:

```bash
uv sync --frozen --extra dev --extra server
make web-install web-build
(cd app/web && npx playwright install chromium)
bash tools/record_demo_snapshot.sh            # writes app/web/demo-snapshot/
npm --prefix app/web run build:demo           # writes app/web/demo-site/
npm --prefix app/web run test:demo-site       # serves it at /grc-lake/ and clicks through
```

`build:demo` sets `NEXT_PUBLIC_DEMO_SNAPSHOT=1` and
`CONSOLE_BASE_PATH=/grc-lake/console`. The regular `npm run build` contains
none of the replay code, and its copy step refuses a demo build, so the
Python package never ships one. The recorder visits every route listed in
`app/web/scripts/demo_routes.mjs`, opens the main drawers, then replays each
detail request for every record of the same kind and records two levels of
graph drill-down. Add a route there when you add a console page; the
`test:demo` check fails until you do.

## Headless

Every page reads the same `/api/v1` resources that agents and CI use:

```bash
curl -s http://127.0.0.1:8787/api/v1/posture/current | jq .data.posture
curl -s 'http://127.0.0.1:8787/api/v1/control-tests?result=fail&limit=10' | jq .
grc-lake connectors list
grc-lake frameworks review --help
```

See the [agent API](api/AGENT_API.md), [headless GRC](HEADLESS_GRC.md), the
[connector catalog](CONNECTORS.md), and the [deployment guide](../deploy/README.md).
