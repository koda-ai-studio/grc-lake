# Reconcile an existing live connector run

The [qualification matrix](../CONNECTOR_QUALIFICATION.md) reports links to bounded
run receipts. A missing link means the public index does not establish that run.
It does not establish that the adapter was never tried, that a demo account is
unavailable, or that its catalog stage should change.

Before running another trial, inspect retained private run records for the exact
GRC Lake adapter. Verify the source revision or installed artifact, execution
command, read-only access scope, collected counts, collection gaps, replay result
and comparison against the provider. A provider account, screenshot, successful
login, fixture run, or run of another product is not connector qualification.
If part of the record is missing, state that limit; do not reconstruct success.

Keep credentials, raw evidence, account and tenant identifiers, project names,
principal names, resource URLs and command arguments containing those identifiers
private. Publish only aggregate results and the bounded conditions they establish.
Do not publish hashes of low-entropy provider identifiers as a substitute for
redaction. No provider resources need to be created or changed to reconcile an
existing run.

Use the template below only after verifying the record. Save the completed,
sanitation-reviewed receipt under `docs/qualification/live/`, give it an explicit
anchor, and link that anchor and source revision from `connector-evidence.json`.
Run `make connector-qualification-doc` and
`python -m pytest -q tests/test_connector_qualification_doc.py`. The generator
checks that the anchor and revision exist; a person must still check the facts.
Keep stage changes separate from a receipt link and explain their evidence.
Historical receipts retain their original dates and limits.

## Receipt template — not evidence of an execution

```markdown
# Bounded connector receipt: YYYY-MM-DD

<a id="connector-id-run-purpose"></a>

- Adapter: exact catalog connector ID.
- Execution date: actual UTC date and time window.
- Source basis: exact commit, or installed artifact version and digest.
- Runtime and dependencies: versions actually used.
- Operator: actual accountable role; retain private identity where required.
- Scope: one test account/project/repository; provider identifiers omitted.
- Authentication and access: mechanism and read-only permissions, no credentials.
- Sequence: sanitized commands actually executed; no substituted success claims.
- Data: distinguish provider records from synthetic records in a live account.

| Check                   | Observed result                                           | Limit or gap                      |
| ----------------------- | --------------------------------------------------------- | --------------------------------- |
| Probe and collection    | Actual outcomes and record counts                         | Unreadable scopes                 |
| Provider reconciliation | Independent provider counts and comparison method         | Unchecked event types             |
| Replay                  | Observed stable identities/counts or duplicates           | Not run if absent                 |
| Pipeline and assessment | Safeguard outcomes and reviewed/proposed framework states | No implied mapping approval       |
| Failure handling        | Only live failure modes actually exercised                | Offline-only cases remain offline |

This receipt establishes only the stated run. It does not establish other tenants,
production capacity, provider-wide completeness, or certification. State the
remaining qualification work and whether the existing catalog stage is retained.
```
