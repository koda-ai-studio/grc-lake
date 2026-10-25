# Evaluate GRC Lake with one useful workflow

Start with one question you can check independently, such as whether repository
changes have the required reviews or whether a scoped identity population has
current MFA evidence. Choose an existing connector and inspect its
[qualification limits](CONNECTOR_QUALIFICATION.md) before connecting it.

## First session

1. Follow the [sample-data tutorial](TUTORIAL_5_MIN.md). Find a failure, follow its
   evidence, inspect the mapping state and export a frozen assessment. Record
   installation time separately from the time spent doing the task.
2. For a real pilot, use an [authenticated deployment](DEPLOYMENT.md), a separate
   lake and an authorized read-only credential reference. Do not mix the golden
   sample with real evidence. Start with one source and a small, named scope.
3. Reconcile source and imported counts, inspect collection gaps and compare at
   least one result against the source. Confirm that missing data and unreviewed
   mappings do not become a passing framework result. Stop and report any mismatch.
4. Inspect source identity, observation time, evaluation reason and mapping state
   for that result. Export and verify a snapshot for your own review. Keep raw
   evidence, private infrastructure details and exported assessments private.

The useful outcome is a result you can explain and independently check. A green
dashboard, successful install or completed synthetic tour alone is not that outcome.

## Return and decide

Return around day 7, collect again and compare changes. Check that repeated reads
do not duplicate source records and that a failed collection remains visible.
Around day 14, decide whether to keep using the workflow, change its scope, or stop.
Record what blocked that decision and which result saved work, if any. Do not
claim time saved unless you measured the comparable task with and without it.

Use a private record for each participating organization or evaluator. Do not
publish identities or assume that an installation represents an organization.
Record the release, source category, synthetic versus real scope, task outcome,
timings, repeat-use date and unresolved correctness or usability problems.

| Signal                  | What counts                                                           | What does not establish it              |
| ----------------------- | --------------------------------------------------------------------- | --------------------------------------- |
| Started evaluation      | A person actually attempted the workflow                              | A proposed invitation or prepared demo  |
| First useful assessment | Scoped real evidence reconciled and one result independently checked  | Synthetic results or installation alone |
| Repeat use              | The person returned and completed another useful collection/review    | A background job or download            |
| Contribution            | A submitted reproducible issue, review, documentation change or patch | Interest in contributing                |
| Accepted contribution   | Maintainer-accepted work, reported separately by type                 | A submitted patch still awaiting review |

Report the denominator and date window with each count. Stars, forks and package
downloads describe visibility or distribution; they do not establish active users
or operating effectiveness. This process adds no telemetry or outbound reporting.

## Give feedback or contribute

The [pilot feedback form](https://github.com/koda-ai-studio/grc-lake/issues/new?template=pilot_feedback.yml)
accepts a sanitized description of the task, version, outcome and obstacle.
Submitting it is optional. Never include credentials, customer evidence or private
hostnames. Report security vulnerabilities through [Security](../SECURITY.md).

Useful first contributions are a minimal synthetic reproduction, a regression
test for an incorrect result, a corrected setup instruction, or a bounded mapping
review with sources and limitations. Follow [Contributing](../CONTRIBUTING.md).
Human mapping decisions require the full requirement text and an explicit,
version-bound rationale; a code review does not approve a framework mapping.

## Stability period

For the next stable release, use an initial 14-day code freeze from publication
to gather this feedback. During that period, accept security, evidence-correctness,
supported-workload performance, installation and documentation fixes. Defer new
connectors, framework expansions and unrelated features. Keep contributions open;
the freeze limits release scope, not participation.

Each exception needs a reproduced problem, a bounded fix, relevant checks and
independent review. Publish a patch when needed and verify its artifacts. Review
actual evaluation outcomes at the end of the period before reopening feature work.
