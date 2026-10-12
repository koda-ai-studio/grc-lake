# Assessment application contract

Evaluation and snapshot commands share `services/assessments.py` across HTTP,
queued execution, CLI and local MCP (through its HTTP adapter). Services do not
import transport handlers. An executable dependency test prevents that reversal.
Other operation kinds retain their existing dispatch; this is a bounded migration.

`AssessmentContext` carries the platform tenant, actor, authority reference,
operation ID and optional expected generation. It is a record of authorization,
not a grant. Server adapters authenticate and authorize; workers re-resolve
credentials and current scopes immediately before execution. Source-account IDs
remain evidence provenance. The expected-generation check runs under the same
local publication lock as evaluation or snapshot creation. Distributed writers
also retain their PostgreSQL fence.

## Outcomes and durable results

`meta.outcome.schema_version = grc.assessment_outcome.v1` separates execution,
publication, assessment verdict and export. Failed controls can belong to a
successful execution. A committed local assessment and failed warehouse export
remain distinct. `assessment_verdict: see_generation` directs consumers to the
frozen results, not an invented aggregate pass.

Queued execution writes `operations/results/<operation UUID>.json` with a version,
owner, operation ID, HTTP status, response and canonical content hash. In distributed
mode that file is uploaded and referenced in the same fenced catalog publication
as the assessment. Uncommitted uploads are never discovered by listing the bucket.
A rejected distributed transaction must not report its staged generation committed.
Local receipt persistence follows local publication: a crash between them remains
uncertain and requires domain-history inspection. No exactly-once external effects
are claimed; snapshot webhooks retain their existing delivery contract.

`GET /api/v1/operations/{id}/result` retrieves the retained result after checking
tenant, operation ownership or administrator authority, and current write scope.
It can recover a committed response even when the worker never updated the job's
completion status. Job state is not rewritten by this read. A missing receipt is
`outcome_unknown` (409), never proof of no effects; corruption or an unknown receipt
version is `integrity_failure` (409). Neither condition replays work.

Inline job responses are capped at 1 MiB. Larger responses preserve completion
status and a result reference. Retained responses are capped at 16 MiB; above that,
the receipt explicitly records `result_limit` and directs the operator to domain
history. Receipts are retained with the lake; existing operational SQL retention
does not delete them. Include their storage in backup and capacity planning.
No new schema is backfilled into old immutable generations.

## Pagination, admission and retry

Operation lists accept 1–500 rows and offset 0–100000. Responses add pagination
metadata. Follow `next_cursor` for traversal resilient to new inserts; cursors are
scoped to the tenant and ordered by creation time plus ID. Cursor and nonzero offset
cannot be combined. This is a live traversal, not a database snapshot: newly added
jobs preceding the cursor require a fresh traversal.

A full tenant queue returns `queue_full` (429) and `Retry-After: 5`; a conflicting
idempotency key remains 409. Credential rate limiting returns 429 and Retry-After.
An unavailable shared limiter rejects admission with a sanitized
`rate_limit_unavailable` (503). Redis uses its own clock, expires idle buckets and
bounds connection/read waits to one second. Local limiting remains per process;
shared limits require configured Redis. Health probes keep their exemptions.

Collector pagination stops on repeated cursors as incomplete, including loops with
empty pages. Cursors never appear in error messages. Collector HTTP retries keep
bounded attempts, exponential jitter and a 120-second default scheduling deadline.
A provider Retry-After above the local per-wait or total budget returns the original
error rather than retrying early. The deadline does not interrupt an in-flight
provider call: adapters must still configure socket timeouts. These read-oriented
helpers do not authorize retrying mutations or uncertain publications.

## Decision

Keep domain results separate from transport response delivery. Moving all routes
or introducing a general command bus would enlarge migration risk without improving
these two operations. Existing envelopes and CLI output remain compatible; new
metadata and the result endpoint are additive. New operation kinds should migrate
only with equivalent authorization, publication and failure tests.
