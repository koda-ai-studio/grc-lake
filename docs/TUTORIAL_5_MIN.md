# Five-minute console tour

Use synthetic evidence to find a failing control, inspect its evidence and
mapping, and export a frozen assessment. The tour needs no provider account or
credentials. Allow additional time for installation; the five minutes describe
the walkthrough, not a measured clean-machine setup time.

## 1. Start GRC Lake with sample data

Pick one. These examples use the published **v0.3.22** release.

**Docker Compose** (Docker with Compose v2):

```bash
git clone --branch v0.3.22 --depth 1 https://github.com/koda-ai-studio/grc-lake.git
cd grc-lake
docker compose up
```

**pip** (Python 3.11 or later):

```bash
python -m venv .venv
source .venv/bin/activate
pip install "grc-lake[server]==0.3.22"
grc-lake fixtures load --company golden --out ./lake --rebase-times
grc-lake serve --server --allow-insecure-no-auth --lake ./lake --host 127.0.0.1 --port 8787
```

Open <http://127.0.0.1:8787/console/dashboard/>. The **golden** sample company
contains synthetic cloud, repository, identity, and AI-governance evidence.
The sample is deliberately unhealthy: failures and missing evidence are part of
the exercise. Counts depend on the catalog and evidence freshness at evaluation.

Authentication is off and the demo listens on loopback. Keep it for local sample
data; use [authenticated deployment](DEPLOYMENT.md) before connecting real evidence.
For unreleased source changes, follow [Contributing](../CONTRIBUTING.md).

Leave the server running. In a second terminal, activate the pip environment if
using pip. The commands below use that installation and `./lake`.
**Compose users:** run CLI commands inside the container, replace `./lake` with
`/lake`, and use `/lake/exports/` for the OSCAL output paths in step 4. For example:

```bash
docker compose exec grc-lake grc-lake assessment status --lake /lake --format summary
```

## 2. Follow a failure to its evidence

In **Overview**, inspect findings and evidence freshness. Open **Controls**, pick
a failing result, then inspect its evidence records, source, observation time,
and failure reason. Use the investigation graph to follow recorded relationships.
A missing or stale record cannot establish a pass.

Read the same assessment in the terminal:

```bash
grc-lake --version
grc-lake assessment status --lake ./lake --format summary
grc-lake assessment violations --lake ./lake
```

The summary reports total and unevaluated controls, failing and warning tests,
open violations, and stale/expired/missing evidence. A posture score alone does
not establish framework compliance.

## 3. Inspect the framework mapping

Open **Frameworks** and compare catalogued, mapped, and reviewed requirements.
Use **Evaluate → Mapping review** to inspect proposed safeguard links. The same
SOC 2 queue is available from the CLI:

```bash
grc-lake frameworks review-queue --lake ./lake --framework soc2
grc-lake frameworks safeguards --lake ./lake --format table
```

A mapping links a safeguard to a framework requirement. Proposed mappings are
not attestable; a reviewed mapping still needs scoped evidence and testing.
This tour does not require an approval. For real evidence, an eligible human
must evaluate the requirement and record their own rationale through the
[mapping-review workflow](MAPPING_REVIEW.md).

## 4. Freeze and export the result

```bash
grc-lake assessment snapshot --lake ./lake --reason "Synthetic demo review"
grc-lake assessment verify-snapshots --lake ./lake
grc-lake oscal export --component-definition --lake ./lake --out component-definition.json
grc-lake oscal export --assessment-results ./lake --out assessment-results.json
```

Inspect the JSON documents: the component definition describes safeguard mappings;
the assessment results describe evaluated controls. Compare the failing control
with its console result. Exporting preserves the result; it does not approve
mappings or turn failures into passes. [OSCAL export](OSCAL_EXPORT.md) explains
the document boundaries and verification.

For Compose, copy the two outputs from the container after exporting them to
`/lake/exports/`:

```bash
docker compose cp grc-lake:/lake/exports/component-definition.json ./component-definition.json
docker compose cp grc-lake:/lake/exports/assessment-results.json ./assessment-results.json
```

You have completed the tour when you can explain one failure, identify its
supporting evidence, distinguish its mapping status, and locate the result in
an export.

## Continue with a scoped workpaper

The [auditor walkthrough](AUDITOR_WALKTHROUGH.md) uses a separate synthetic
fixture with an explicit test plan, assessment period, and population baseline.
Run its three commands from a source checkout to build a draft HTML/JSON
workpaper and verify the exported file hashes. Inspect the missing asset,
failed change observation, and incomplete sampling windows. Those extra inputs
are needed for the workpaper; the console's golden demo alone is not a complete
audit test plan. Hash verification establishes integrity relative to the
manifest, not source authenticity or auditor acceptance.

## Connect your own evidence

Use a new lake so real evidence never mixes with the sample company. Start with
one read-only source through [connector setup](CONNECTOR_CREDENTIALS.md) and
[the live-cloud guide](LIVE_CLOUD_POC.md), or qualify an
[existing-lake reader](BRING_YOUR_OWN_LAKE.md). Reader and mapping qualification
vary. In the console: **Connections → choose a source → Test → Enable → Sync**.

Configure [SSO and scoped credentials](SERVER_AUTH.md), storage, and
[backup/restore](runbooks/BACKUP_RESTORE.md) for a shared deployment. For automated
checks after setup, see the [CI posture gate](CI_GATE.md).

If a step fails, report the installed version, install method, failed command,
and sanitized error in a [bug report](https://github.com/koda-ai-studio/grc-lake/issues/new/choose).
Do not include credentials or real evidence.
