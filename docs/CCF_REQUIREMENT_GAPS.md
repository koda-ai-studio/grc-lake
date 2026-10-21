# CCF requirement gaps

`GET /api/v1/ccf/requirement-gaps` explains blockers retained in the current
assessment's requirement and safeguard summaries. The read-only MCP tool
`list_ccf_requirement_gaps` returns the same page envelope. Neither surface
approves mappings, modifies evidence nor changes the stored requirement verdict.

Each row contains the requirement and framework IDs, stored status, sorted
`gap_codes`, reviewed/pending/contextual mapping counts, and compact details of
blocking safeguards. A `pass` with no gaps still does not establish population
completeness: the assessment is scoped to observed assets.

| Gap code                     | Meaning and next evidence needed                                                                                                  |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `mapping_review_pending`     | An implementation mapping still needs a human equivalence decision.                                                               |
| `no_reviewed_implementation` | No reviewed implementation mapping is available for this requirement.                                                             |
| `context_only`               | Supporting/context mappings exist, but do not establish implementation coverage.                                                  |
| `review_log_unverified`      | The review ledger was not verified when this assessment was produced.                                                             |
| `safeguard_failed`           | A required safeguard has a failing aggregate result. Inspect its asset results.                                                   |
| `safeguard_stale`            | A required safeguard's evidence is stale. Refresh and re-evaluate it.                                                             |
| `safeguard_not_evaluated`    | A required safeguard lacks a conclusive result. Inspect its asset results.                                                        |
| `unassessed_assets`          | Observed applicable assets lack assessed safeguard evidence. This is not a count of all assets in the source estate.              |
| `invalid_evidence_bindings`  | The assessment rejected evidence-to-safeguard bindings. Inspect the corresponding asset reasons.                                  |
| `requirement_stale`          | The stored requirement result is stale. This summary alone does not identify particular missing evidence types.                   |
| `assessment_detail_missing`  | Stored summary detail cannot fully explain this result. Do not infer a pass; inspect the assessment and re-evaluate if necessary. |

Filter by `framework_id`, `control_id`, `status` or `gap_codes` using the standard
collection query contract; `sort`, `limit`, `offset` and `cursor` are supported.
Counts are calculated after filtering. The response includes a generation ID and
manifest digest. Send that `generation_id` with later pages to reject a changed
current generation with HTTP 409. This is not a historical-generation selector.

Server authentication selects the tenant's lake and requires read scope. The
query reads the generation's SQLite summary, never its per-asset evidence arrays.
The result is computed at catalog scale; pagination bounds the returned rows,
not the catalog summary held in memory. Unsealed lakes, missing projections and
unreadable summaries return HTTP 409. Re-evaluate a legacy lake to publish a
current generation. A successful read uses the stored projection; it does not
perform a new full-generation cryptographic verification or a new evaluation.

Human review or evidence changes after publication appear only after a new
assessment. Use mapping-review and safeguard asset-result endpoints for their
respective details; a pending mapping and missing operating evidence require
different actions.

## Console journey

Open **Frameworks**, select a framework and expand a requirement. Choose
**Explain assessment gaps** to read its frozen result, mapping-review blockers,
stale or unassessed evidence, and relevant next actions. Blocking safeguard
counts and the generation/manifest identity are available on demand.

Opening the explanation makes one bounded request for that requirement. Closing
it discards the result; reopening reads the latest assessment. A late response
from a closed panel cannot replace the new result. Missing rows, unavailable
assessments and mismatched generation metadata produce an explicit unavailable
state, never inferred coverage. Retry reads the latest assessment.

The explanation does not change verdicts, approve mappings or verify integrity
again. Complete asset inventory remains unestablished; a recorded pass with no
blockers is not a certification or an estate-wide coverage claim.

For a private offline handoff across multiple frameworks, export the
[portable framework coverage report](FRAMEWORK_COVERAGE_REPORT.md). It verifies
and pins a generation, preserving all catalogued requirements in the denominator.
