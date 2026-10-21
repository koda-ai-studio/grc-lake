# GitHub, Okta, and Jira workflow qualification

Run the existing read-only adapters against retained provider-shaped fixtures,
then materialize their combined evidence with the shared local pipeline:

```sh
make qualify-connector-workflow
# Or retain another attempt without overwriting the first:
make qualify-connector-workflow CONNECTOR_QUALIFICATION_OUT=build/connector-attempt-2
```

The command exits nonzero when a check fails. It requires a new output directory
and refuses hosted mode or a catalog data-directory override. Collection uses
explicit fixture paths and `materialize=False`, then calls the local pipeline;
it does not invoke connector write sinks or evidence-change automations.

## What a passing receipt establishes

| Stage            | Checked behavior                                                                                                                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Collect          | Six GitHub repository-governance, eight Okta identity, and eight Jira workflow records survive in one raw ledger with distinct event IDs and synthetic provenance.                                      |
| Evaluate         | Raw and normalized statuses agree; an active account without MFA and open workflow deviations remain visible even alongside a resolved Jira ticket. The selected SOC 2 controls retain failing results. |
| Freshness        | GitHub and Okta use their 60-minute connector SLOs; Jira uses its 240-minute SLO. A separate time-bound regression checks Jira becomes stale after four hours.                                          |
| Verify           | Every normalized event verifies against its raw hash; the materialized generation passes integrity verification.                                                                                        |
| Export           | A frozen HTML evidence report and OSCAL assessment-results JSON disclose synthetic evidence.                                                                                                            |
| Recollect        | All three adapters run again. Event IDs, record counts and observed outcomes stay stable, without duplicating rows. Observation timestamps may advance.                                                 |
| Preserve history | The original assessment snapshot remains unchanged after recollection, and its chain verifies.                                                                                                          |
| Fail collection  | Malformed Jira fixture JSON records an error and preserves the previous combined raw inventory and materialized posture.                                                                                |

## Review the output

The default directory is `build/connector-workflow-qualification/`:

- `report.json`: pass/fail checks, source commit and dirty-tree flag, runner hash, copied-input hashes,
  first collection run receipts, export hashes and retained snapshot path.
- `inputs/`: original provider-shaped JSON fixtures, copied before collection.
- `lake/`: connector configuration and run ledgers, raw records, bronze/silver/gold
  evidence, published generations and the immutable assessment snapshot.
- `verification.json`: generation integrity and per-event raw-hash verification.
- `evidence.html`: self-contained evidence report, viewable without a running API.
- `assessment-results.json`: synthetic OSCAL assessment-results export.
- `failed-inputs/`: the deliberately malformed Jira input used for the failure check.

Retain the receipt separately if using its hashes to check a later handoff. A hash
in a mutable local receipt alone does not authenticate an external publisher.

## Qualification boundary

This is an **offline synthetic connector workflow**. It does not establish live
credentials, vendor permission coverage, pagination correctness, production
capacity, availability, hosted tenant isolation or independent completeness of
an inventory. It does not infer identity joins between providers, link a Jira
ticket to a security finding, or approve any control or framework mapping.

Collection, evaluator results, evidence integrity and human review are distinct
claims. The tests in
[`test_connector_workflow_qualification.py`](../tests/test_connector_workflow_qualification.py)
also inject dropped provider rows and an exception to ensure they cannot produce
a successful receipt. For control operating-period and auditor-workpaper scenarios,
use [control workflow qualification](CONTROL_WORKFLOW_QUALIFICATION.md).
