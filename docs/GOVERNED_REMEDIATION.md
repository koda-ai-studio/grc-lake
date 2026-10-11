# Governed exceptions and remediation

A risk exception records a time-limited acceptance decision. It never changes a
control result to `pass` or supplies missing evidence.

## Exception lifecycle

A control manager requests an exception with a reason and a future, timezone-aware
expiry. The server binds the requester to the authenticated user. The request is
`pending` until a different control manager approves it. Approval binds the
reviewer identity and time on the server; caller-supplied approver names are
rejected. Expired or revoked requests cannot be approved. The active list applies
these checks before pagination. Expired requests display an expired status even
when no background job has updated their stored lifecycle state.

After upgrading, legacy active exceptions become pending. Their historical
claimed approver remains visible, but is not an authenticated approval. Revoke and
re-request those exceptions to establish the independent review trail.

## Verified remediation

A task linked to a control or finding cannot be resolved by changing its status.
Use `POST /api/v1/remediation/tasks/{id}/verify` as a control manager, with an
optional `resolution_note`. The task needs a control ID. Verification requires:

- an intact sealed generation owned by the authenticated tenant;
- passing control tests with fresh required evidence;
- observations and collection times after task creation and no later than the
  verification time.

Successful verification appends a receipt containing the authenticated reviewer,
control, generation digest, assessment hash, and raw evidence hashes. Reopening a
task retains its verification history. A conditional database update rejects a
concurrent stale retest instead of overwriting another reviewer's receipt. A failed verification leaves it open and
rolls back the submitted note. Unlinked administrative tasks still support manual
closure; this is not an assurance conclusion.

The receipt is a point-in-time retest over observed assets. It does not establish
complete inventory coverage, sustained operating effectiveness, or remediation of
assets absent from the generation. A resolution note or external link is context,
not proof of a passing retest. The console displays this distinction and keeps the
note available when verification fails.

## Recovering interrupted scheduler history

The daemon logs a sanitized tick failure and tries again on its normal cadence.
Corrupt history stays blocked until reconciled; it is never silently ignored.
CronJobs use `restartPolicy: Never` and `backoffLimit: 0`, leaving the next scheduled
job as the retry boundary.

For an unterminated final line in one tenant's `scheduler_state.jsonl` or
`connector_runs.jsonl`, run:

```bash
grc-lake scheduler repair-history --lake /path/to/tenant-lake
```

This explicit recovery takes scheduler and connector-history locks, preserves
original bytes in the owner-only `gold/recovery` directory, and repairs only the
final unterminated record. Interior or newline-terminated corrupt records require
operator reconciliation. Evidence generations and assessment ledgers are outside
this command's scope. A recovery marker blocks ticks if the command is interrupted;
rerunning the command completes recovery. Every configured target waits a full
schedule interval after recovery because the interrupted attempt's execution
cannot be inferred from a torn record. Review the archived tail before retrying
any external action manually.

Reopening retains previous receipts but requires a new generation with evidence
observed after the task's latest update. Partial source collection blocks a
retest. Publishing a failing control assessment reopens resolved tasks owned by
that generation's platform tenant when the application database is available.
Fixture generations can be assigned with `fixtures load --tenant-id <platform-tenant-id>`;
source account IDs remain distinct from platform ownership.

## Scoped implementations and governance decisions

The following authenticated server APIs add versioned records alongside existing
risks and exceptions. They do not automatically convert those older records,
change control verdicts, populate workpapers or provide a dedicated console editor.

| Endpoint                                         | Purpose and authority                                                                                                                              |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET/POST /api/v1/ccf/implementations`           | Read scope history; a human with `control_manage` creates an implementation revision.                                                              |
| `GET/POST /api/v1/governance/decisions`          | Read decision history; `control_manage` proposes a disposition. Machine identities can propose but cannot approve.                                 |
| `POST /api/v1/governance/decisions/{id}/reviews` | A human with `control_manage` approves, rejects or revokes the exact content hash. Approval/rejection requires a different user from the proposer. |

GET collections use `limit` (default 25, maximum 100), `offset` and `has_more`.
Reads and references are platform-tenant scoped. A cross-tenant record is not found.

An implementation specifies `safeguard_id`, `owner`, `system`, `cadence_days`,
`scope`, and `evidence_event_ids`. Scope contains `safeguard_ids`, `control_ids`
and optional assets identified by `source_account_id` plus `asset_id`.
Revisions set `supersedes_id` and retain the original safeguard. Saved content and
its SHA-256 bind the declaration, tenant, creator, generation, evidence references
and definition digests. Earlier revisions remain readable.

A decision specifies `kind` (`risk_acceptance`, `by_design`, `not_applicable`,
`inherited`, or `compensating`), rationale, residual risk, the same scope/evidence
fields, and a future timezone-aware `expires_at`. An optional `risk_id` must belong
to the same platform tenant. Evidence must be available, bound to the declared
controls or safeguards and within any declared asset scope in an intact,
tenant-owned generation. This establishes provenance, not scope completeness or
correctness of the human conclusion.

Review bodies contain `decision` (`approve`, `reject`, or `revoke`), `rationale`
and the returned `content_sha256`. The server binds reviewer identity and time.
Approval is active only while unexpired, unrevoked, unsuperseded and matched to the
current safeguard and requirement definitions. `approved` records the historical
action; `active` is the current applicability of that decision. Changed definitions
set `basis_verified: false`; submit a new proposal for review. Content hashes detect
accidental record modification; they are not signatures against a privileged
database administrator.

An extension is a new proposal with `supersedes_id`, the same kind, risk and scope,
and a later expiry. It requires fresh evidence binding and independent approval.
A pending extension leaves its predecessor unchanged; approving it supersedes the
old decision without deleting its reviews. Competing approvals or repeated reviews
return a conflict. Revocation is recorded separately and never deletes history.

Migration `0030` adds these tables without modifying existing records. Back up the
application database before migration and export the new histories before any
downgrade, which removes the added tables. See the [data model](DATA_MODEL.md) for
identity, generation and compatibility details.
