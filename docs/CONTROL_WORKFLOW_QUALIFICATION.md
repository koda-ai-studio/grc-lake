# Access and change workflow qualification

Run a bounded synthetic matrix through normalization, assessment generation,
population reconciliation, control sampling, snapshots, and draft workpaper
export. This checks two existing safeguards: `SG-IDENTITY-001` and
`SG-CHANGEMANAGEMENT-001`. It does not collect from AWS, GitHub, an identity
provider, or any other live system.

From a source checkout with development dependencies installed:

```bash
make qualify-control-workflow
```

Open `build/control-workflow-qualification/report.json`, then a case's
`workpaper/index.html`. Choose a new output directory for another attempt:

```bash
make qualify-control-workflow QUALIFICATION_OUT=build/control-workflow-second-run
```

Existing output directories are never reused. Run locally with repository
catalogs; hosted execution and a `GRC_LAKE_DATA_DIR` override are rejected.
Legacy `TRUSTOPS_` configuration aliases follow the same restriction.

## Expected behavior

Each safeguard runs the following cases independently with a declared asset,
two daily sample windows, design evidence, and an explicit historical cutoff.
Inputs are derived from the [auditor walkthrough](AUDITOR_WALKTHROUGH.md)
fixtures and saved beside each result. The passing case supplies synthetic
passing observations; it is not an approval of the original demonstration.

| Case                                                  | Operating samples     | Population reconciliation |
| ----------------------------------------------------- | --------------------- | ------------------------- |
| Complete samples                                      | Sample pass           | Declared scope reconciled |
| Observed failure                                      | Sample fail           | Declared scope reconciled |
| Conflicting pass/fail observations                    | Sample fail           | Declared scope reconciled |
| Missing daily window                                  | Insufficient evidence | Declared scope reconciled |
| Sample outside the assessment period                  | Insufficient evidence | Declared scope reconciled |
| Observation without a verdict                         | Insufficient evidence | Declared scope reconciled |
| Unavailable supporting evidence                       | Insufficient evidence | Declared scope reconciled |
| Partial collection receipt                            | Sample pass           | Incomplete                |
| Declared asset without observations                   | Insufficient evidence | Incomplete                |
| Stale collection receipt                              | Sample pass           | Incomplete                |
| Design evidence older than 366 days before the period | Sample pass           | Declared scope reconciled |

Design evidence remains documented except in the stale-design case, where design
is `insufficient_evidence` even though the operating samples pass. Age is measured
against the plan's historical period, not the wall clock when the test is run.
Partial or stale collection
can coexist with passing observed samples: the population gap remains visible.
Neither result becomes a conclusion of operating effectiveness. Inventory and
collection receipts remain synthetic operator assertions, and every workpaper
retains pending human review and the current mapping review states.

## Inspect the evidence

The report records the source revision, dirty-worktree flag, runner hash,
expected and observed results, and per-case input/content hashes. Each case
retains its raw events, plan, population baseline, normalized lake, draft
HTML/JSON workpaper, and export manifest. The workpaper includes requirement
mappings, recorded review states, generation identity, evidence references, and
sampling gaps for a human to inspect. It does not reproduce licensed requirement
text or record a mapping-review decision.

Checks also require identical workpaper content when rebuilt from the same
sealed generation and byte-identical JSON, HTML and manifest files in
`replayed-workpaper`. The mapping list must match the sealed catalog, and the
selected safeguard must exercise proposed mappings whose CCF requirements are
not attested passes. This checks existing mapping states without changing them;
if future human decisions review all of these mappings, update the synthetic
scope rather than silently reporting an unexercised check as passed.

The runner also requires a valid snapshot chain, rejection of a foreign tenant, and
rejection of a deliberately altered export. The altered copy is kept separately
under `tampered-workpaper`; use `workpaper` for review. A failed expectation or
execution error makes the overall command exit nonzero. Results are retained;
exception messages are omitted to avoid copying operator data into reports.

Each case also verifies the original export against its retained content digest,
then creates `replacement-workpaper` with changed narrative and regenerated HTML
and manifest. That replacement must pass consistency-only verification and fail
verification against the original digest. `handoff-verification.json` records
both checks separately. These deliberately altered copies remain synthetic and
unreviewed; the runner does not authenticate an external custodian of the digest.

CI runs the matrix in the required pipeline-smoke path and retains the report,
case inputs, result receipts, original and replayed workpapers, and replacement probes for 14 days, including
on failures. Download the `control-workflow-qualification` artifact for the
exact PR or main revision under review. Local runs additionally retain lakes
and tampered copies.

## Regression proof by boundary

The runner and focused tests share the existing control-assurance fixtures.
Use the following commands for the complete workpaper regression slice:

```bash
uv run --frozen python -m pytest -q -o addopts='' \
  tests/test_control_workflow_qualification.py tests/test_control_assurance.py \
  tests/test_population_reconciliation.py tests/test_audit_workpapers.py \
  tests/test_workpaper_handoff.py tests/test_workpaper_export_validation.py \
  tests/test_ccf_operational_assessment.py
```

| Boundary                                      | Retained or executable proof                                                                                                                                                                                                                                                                                                                                                                   |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Passing, failing and missing samples          | The matrix's complete, observed-failure, missing-window and unavailable-evidence cases assert declared outcomes separately.                                                                                                                                                                                                                                                                    |
| Stale evidence                                | Stale collection leaves population incomplete; stale design cannot document design. An out-of-period operating sample cannot fill a period window.                                                                                                                                                                                                                                             |
| Partial collection and incomplete populations | Passing observed samples coexist with an incomplete collection receipt. A declared asset without observations leaves operating gaps.                                                                                                                                                                                                                                                           |
| Proposed mappings                             | Every matrix case compares workpaper mappings with the sealed catalog and checks proposed requirements are not attested. `test_self_consistent_export_regressions_fail_qualification` deliberately promotes a workpaper-only mapping and requires qualification to fail.                                                                                                                       |
| Export determinism and tampering              | Each case compares all three exported files across replay, rejects changed HTML and rejects a self-consistent replacement against the retained digest. The fault-injection test also requires byte-changing but hash-consistent manifests to fail determinism.                                                                                                                                 |
| Invalid lineage                               | `test_five_control_demo_cli_and_evidence_integrity` in [control-assurance tests](../tests/test_control_assurance.py) corrupts normalized evidence and requires plan assessment, workpaper construction and CLI export to reject it; no export directory is created.                                                                                                                            |
| Historical generation binding                 | `test_workpaper_remains_bound_when_current_generation_changes` in [workpaper tests](../tests/test_audit_workpapers.py) publishes corrected evidence, checks that the new draft has a new generation and digest, and verifies the original server record, historical reconstruction and export bytes remain unchanged.                                                                          |
| Reviewer identity                             | `test_review_requires_independent_authority_and_exact_digest` in [workpaper tests](../tests/test_audit_workpapers.py) rejects self-review, bearer-key review, foreign tenants and stale digests. [Handoff tests](../tests/test_workpaper_handoff.py) preserve the hash-consistency-only boundary. Simulated identities exercise authorization; they do not constitute real auditor acceptance. |

These tests do not require live-provider credentials or write real human decisions.
All matrix exports remain drafts pending human review, including passing cases.

## Qualification boundary

A report marked `passed` means these explicit synthetic expectations were met.
It does not establish live-provider permissions, pagination, source authenticity,
provider-wide accuracy, complete framework coverage, or reviewer acceptance.
The replay check rebuilds a workpaper from one generation; it does not replay
collection or establish byte-identical output across separate live runs.

Use [connector qualification](CONNECTOR_TEST_ACCOUNTS.md) for authorized source
checks and [mapping review](MAPPING_REVIEW.md) for human decisions. Report
provider qualification and human review separately from this matrix.
