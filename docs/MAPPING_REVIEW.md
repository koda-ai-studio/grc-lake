# Mapping review

GRC Lake ships a Common Control Framework: reusable safeguards, each mapped to
the framework requirements it satisfies (see
[Common Control Framework](COMMON_CONTROL_FRAMEWORK.md)). Before an auditor
relies on a mapping, someone has to confirm that the safeguard's evidence
really answers that requirement. This page covers who can do that, what gets
recorded, and how the result shows up in coverage.

## Pending SOC 2 and ISO review

The [SOC 2 and ISO review batches](reviews/SOC2_ISO_REVIEW.md) contain the pending
requirements, candidate operating contracts, source locators, specific review
questions and empty decision fields. Cisco and Oracle guidance supports these
proposals; it does not establish normative equivalence or human approval.

## What "reviewed" means

A maintainer review inherited through `review_basis.inherited_from` remains valid
only while its source mapping exists in the same safeguard, has an unambiguous
current control, and retains a current maintainer review. Missing, demoted,
version-stale, duplicate, or cyclic source chains make the inherited mapping
proposed. This rule also follows multi-step inheritance. A tenant can still
review that mapping independently through the existing approval workflow.
Valid inherited mappings keep their existing decision fingerprints.

Each mapping in `controls/safeguards.json` ships with a `review_status`:

- **reviewed**: a GRC Lake maintainer confirmed the equivalence against the
  requirement text. The console and API call this **maintainer-reviewed**.
- **proposed**: a source-native assessment contract, a published crosswalk candidate, or a title-based suggestion, and
  not yet confirmed by anyone.

Your organization can add its own decision on top of either state:

| Org decision      | Effective state for your tenant                  | In evaluated coverage | Attestable (OSCAL, "reviewed" counts) |
| ----------------- | ------------------------------------------------ | --------------------- | ------------------------------------- |
| none              | maintainer-reviewed or proposed, as shipped      | yes                   | only if maintainer-reviewed           |
| **approve**       | **org-reviewed** (a proposed mapping)            | yes                   | yes                                   |
| **approve**       | stays maintainer-reviewed (already reviewed)     | yes                   | yes                                   |
| **needs changes** | needs changes                                    | yes                   | no                                    |
| **reject**        | rejected, also for a maintainer-reviewed mapping | **no**                | no                                    |

A rejected mapping leaves your tenant's evaluated coverage and is reported as
rejected, so the requirement it covered can fall back to unmapped. Neither kind
of review is a certification.

The state is computed in one place,
`security_lakehouse.safeguards.effective_review_state`, and every surface reads
it: CCF coverage, the framework coverage ledger, the review queue, OSCAL export,
and assessment snapshots.

## Coverage is never blended

Counts keep each kind of confirmation separate:

- **catalogued**: requirements in the catalog
- **mapped**: requirements with at least one mapping that is not rejected
- **maintainer-reviewed**: requirements with at least one maintainer-reviewed mapping
- **org-reviewed**: requirements attestable only through your approvals
- **rejected**: mappings (and requirements left without coverage) your org rejected

`reviewed` / `attestable` equals maintainer-reviewed plus org-reviewed. With no
org decisions every number equals the shipped one.

## Audit trail

Decisions are appended to `<lake>/gold/mapping_reviews.jsonl`. The shipped
`controls/safeguards.json` is never modified. In server mode each tenant has its
own lake, so each tenant has its own log.

Each record holds:

- the mapping (`safeguard_id`, `framework_id`, `control_id`)
- `decision`: `approve`, `reject`, or `needs_changes`
- `rationale` (required)
- `reviewer`, `reviewer_id`, `reviewer_role`, and `auth_method`, taken from
  the signed-in user in server mode
- `decided_at`
- an optional `evidence_ref`
- the mapping's published `source_anchor` at decision time
- `supersedes`: the decision it replaces

The latest decision for a mapping wins, and earlier ones stay in the log. The
log is hash-chained (`prev_hash`, `record_hash`) and serialized across
processes, like the other GRC Lake ledgers. `GET /api/v1/mapping-reviews/summary`
and `frameworks review export` report whether the chain verifies.

### Integrity

- Decisions are applied only from a log that verifies. If the chain is broken
  (an edited record, a torn line after a crash, a missing or wrong tip MAC),
  every mapping falls back to its shipped review state, no new decision can be
  recorded, and each coverage surface says so with `review_log_verified: false`:
  `GET /api/v1/ccf/coverage`, `GET /api/v1/frameworks/coverage` (each framework
  row and the summary), `GET /api/v1/mapping-reviews/summary`, and the snapshot
  `mapping_review.summary`. Restore `gold/mapping_reviews.jsonl` (and its
  `mapping_reviews.tip.json` sidecar) from backup to recover.
- Each decision batch is written with one append and `fsync`, so a batch lands
  whole or, after a crash mid-write, as a torn line that verification reports.
- When `GRC_LAKE_COOKIE_SIGNING_KEY` is set (always, when server auth is on),
  the chain tip is also MACed with a key derived from it and stored in
  `gold/mapping_reviews.tip.json`. Someone who can write the lake but does not
  hold the key cannot rewrite the log and recompute every hash undetected.
  `decision_log.tip_mac` reports `verified`, `missing`, `invalid`, or
  `not_configured` (no key; local mode). Rotating the key makes an existing
  tip MAC report `invalid` until you re-sign it (see
  [Rotating the signing key](#rotating-the-signing-key)).

### Rotating the signing key

After changing `GRC_LAKE_COOKIE_SIGNING_KEY`, re-sign each lake's decision-log
tip with the new key. Run it with the new key in `GRC_LAKE_COOKIE_SIGNING_KEY`
and the old one in any other variable you name:

```bash
export GRC_LAKE_COOKIE_SIGNING_KEY="<new key>"
export GRC_LAKE_PREVIOUS_SIGNING_KEY="<old key>"
grc-lake frameworks review resign --lake <root>/tenants/<tenant_id> \
  --previous-key-env GRC_LAKE_PREVIOUS_SIGNING_KEY --actor ops@example.com
unset GRC_LAKE_PREVIOUS_SIGNING_KEY
```

The command holds the log's lock, verifies the hash chain, and checks the
recorded tip MAC against the old key. Only then does it write a new tip MAC
with the current key. It refuses, and writes nothing, when the chain is broken,
the `mapping_reviews.tip.json` sidecar is missing, or the recorded MAC was not
made with the old key. A log rewritten by someone without the old key can
therefore never be re-signed. Restore that log from backup instead. A tip that
already verifies with the current key is left as is (`status: already_current`).

Each re-sign appends a `tip_resigned` entry (actor, time, log length, tip hash)
to the hash-chained `gold/mapping_review_audit.jsonl`. It appears in the
workbench audit log under **Mapping review**. Neither key is recorded. The
output ends with the `decision_log` verification, which reports
`tip_mac: verified` after a successful re-sign. In a multi-tenant deployment,
run the command once per `tenants/<tenant_id>` lake.

Each assessment snapshot also pins a `mapping_review` block: the counts above
plus the decision-log tip hash. An auditor can then tie a snapshot's coverage to
the exact decisions in force when it was frozen.

## Who can decide

| Principal                                                     | List queue and history | Record a decision |
| ------------------------------------------------------------- | ---------------------- | ----------------- |
| `admin`, signed-in console session                            | yes                    | yes               |
| `compliance_reviewer`, signed-in console session              | yes                    | yes               |
| any other role                                                | yes                    | no (403)          |
| any API key used as a bearer token (agents, CI, scripts, MCP) | yes                    | no (403)          |
| MCP tools                                                     | yes                    | no tool exists    |

The server enforces both checks. `mapping_review` is a separate scope: only
`admin` and the new `compliance_reviewer` role hold it. A decision also needs an
interactive session. A bearer API key is refused whatever its role, so an agent
holding an admin key still cannot approve. The request body has no reviewer
field, and one sent anyway is rejected: the reviewer is always the
authenticated user.

A console session opened with an API key (`/api/v1/auth/session-from-key`)
counts as interactive. The record then carries `auth_method: session:api_key`,
which separates it from SSO sessions (`session:oidc`, `session:saml`).

In local mode (no server login) the CLI records decisions and requires
`--reviewer`. Those records say `auth_method: cli-local`. The stdlib local
server takes `reviewer` in the body and records `local-unauthenticated`.

## Using it

Console: **Evaluate → Mapping review**. It shows per-framework progress
(org-reviewed x of mapped) and a queue filterable by framework, family, status,
and text. Select rows, write one rationale, then approve, request changes, or
reject. Each row opens a drawer with its basis, source anchor, and decision
history. Frameworks and Crosswalk link to it and show the same split.

API:

```bash
GRC_LAKE=https://grc-lake.example.com  # your server's base URL; KEY is an API key
# Pending queue (proposed + needs changes), paginated
curl -s "$GRC_LAKE/api/v1/mapping-reviews/queue?framework_id=fedramp-moderate&limit=50" -H "Authorization: Bearer $KEY"
# status=all | maintainer_reviewed | org_reviewed | needs_changes | rejected ; family=<ccf family> ; safeguard_id= ; q=
curl -s "$GRC_LAKE/api/v1/mapping-reviews/decisions?safeguard_id=SG-IDENTITY-001&control_id=SOC2-CC6.1" -H "Authorization: Bearer $KEY"
curl -s "$GRC_LAKE/api/v1/mapping-reviews/summary" -H "Authorization: Bearer $KEY"
```

`POST /api/v1/mapping-reviews/decisions` takes
`{"decision", "rationale", "items": [{"safeguard_id", "framework_id", "control_id", "review_basis_sha256", "expected_decision_id"}], "evidence_ref"}`
from a signed-in console session. A batch holds up to 500 mappings and is all or
nothing. Copy both concurrency fields from the queue item that was inspected:
`review_basis_sha256` binds the operating contract, source, mapping and requirement;
`expected_decision_id` is the most recent decision ID, or JSON `null` when there
has been no decision. Missing fields are rejected. If either the definition or
history has changed, the entire batch is rejected before any log write. Refresh
and inspect the changed item before submitting again. The console refreshes the
queue and clears the stale selection after this conflict. Selections retain the
inspected definition and decision tokens even when the queue refreshes in the
background. History labels stale
approvals as needing renewed review instead of presenting them as in force.

CLI (local lake):

```bash
grc-lake frameworks review approve --lake ./lake \
  --safeguard SG-IDENTITY-001 --framework cmmc-2-level2 --control CMMC-3.1.14 \
  --rationale "MFA evidence covers remote access routing" --reviewer grc@example.com
grc-lake frameworks review reject ...        # same flags
grc-lake frameworks review needs-changes ... # same flags
grc-lake frameworks review export --lake ./lake --format csv --out decisions.csv
grc-lake frameworks review resign --lake ./lake --previous-key-env OLD_KEY  # after a key rotation

# Coverage, queue, and OSCAL with your decisions applied
grc-lake frameworks safeguards --lake ./lake --format table
grc-lake frameworks coverage --lake ./lake
grc-lake frameworks review-queue --lake ./lake
grc-lake oscal export --component-definition --lake ./lake --out cd.json
```

## OSCAL

The component definition (see [OSCAL export](OSCAL_EXPORT.md)) emits
maintainer-reviewed mappings plus your org-reviewed ones. Each
implemented requirement carries `grc-lake-review-state`. Org-reviewed ones also
carry `grc-lake-reviewed-by`, `grc-lake-reviewed-at`, and
`grc-lake-review-decision-id`. Rejected and proposed mappings are left out.

## Coverage terminology

- **Readiness `mapped` / Source article identity reviewed** checks that a local
  control identifier has a reviewed mapping to its source article. It does not
  establish that a safeguard satisfies the requirement.
- **CCF mapped** means a requirement is claimed by a primary or equivalent
  safeguard mapping, whether proposed or reviewed. Supporting and inherited
  mappings are contextual and do not establish full coverage.
- **Reviewed CCF mapping** records human review of the safeguard-to-requirement
  relationship; it still needs scoped evidence and operating-effectiveness tests.
- **Top-level coverage** applies to the 12 PCI DSS requirement headings and the
  18 CIS v8.1 control headings in the catalog. A 100% source-citation percentage
  at this level does not mean coverage of their sub-requirements or safeguards.
- **Source reconciliation** attributes automated source matching through
  `source_reconciled_by` and `source_reconciled_date` (catalog) or
  `source_reconciled_at` (articles). Proposed rows stay proposed. Readers accept
  the old `reviewed_*` fields on proposed rows as source provenance only; human
  reviewed rows continue to use `reviewed_*`.

## Semantic review basis

A decision requires a unique safeguard-to-control target whose framework matches
the current control catalog. Duplicate targets, missing controls, and mismatched
frameworks reject the whole batch before the decision log changes. Historical
approvals for these invalid targets remain visible but cannot verify a review
basis or contribute org-reviewed coverage. Rejections and requests for changes
remain holds until explicitly superseded.

New organization decisions record `review_basis_version` and
`review_basis_sha256`. The digest includes the safeguard's operating semantics,
the mapping member and the requirement definition. Changing objective, rule,
evidence or asset requirements, frequency, owner or mapping source invalidates a
previous approval even when the requirement ID and version are unchanged. A
cosmetic safeguard title change does not.

An approval with a changed or absent basis becomes proposed; its historical
review stays visible with `basis_verified: false`. Legacy decisions are not
rewritten or automatically reapproved. Rejections and `needs_changes` remain holds
until a reviewer supersedes them. The console identifies approvals needing review.

Catalog publication validation also rejects duplicate mappings, mismatched
frameworks, missing explicit review/version fields, invalid rules and malformed
asset/evidence type lists. This stricter publication gate does not rewrite legacy
reader defaults or claim that a mapping establishes operating effectiveness.

## CSF 2.0 improvement and recovery review packet

This bounded slice covers ID.IM-01, ID.IM-03, RS.MA-05, RC.RP-04 and RC.RP-06.
Each outcome has a separate safeguard and a typed assessment-evidence
contract in `controls/safeguards.json`. The source is
[NIST CSF 2.0, Appendix A](https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf),
SHA-256 `3c31f46fee98cac0c4323453e5109291a213b4de7fef8c058af9bf67f717433c`.
These are direct outcome mappings, not cross-framework equivalence claims.

| Outcome  | Safeguard                     | Evidence to inspect before deciding equivalence                                                |
| -------- | ----------------------------- | ---------------------------------------------------------------------------------------------- |
| ID.IM-01 | SG-EVALUATIONIMPROVEMENT-001  | Evaluation scope and findings linked to improvement decisions; explain any no-change decision. |
| ID.IM-03 | SG-OPERATIONALIMPROVEMENT-001 | Actual operational experience linked to improvement decisions and follow-up.                   |
| RS.MA-05 | SG-RECOVERYINITIATION-001     | Incident-specific application of initiation criteria and the accountable transition decision.  |
| RC.RP-04 | SG-POSTINCIDENTNORMS-001      | Mission functions and residual risks informing the post-incident operating norms.              |
| RC.RP-06 | SG-RECOVERYCOMPLETION-001     | Completion criteria, the recovery declaration and completed incident documentation.            |

A qualified reviewer should compare each evidence contract and its limits with
the cited outcome, then record `approve`, `needs_changes` or `reject` through the
existing mapping-review workflow. The maintainer approved all five mappings in
the [33-batch decision receipt](../controls/reviews/2026-10-14-source-batches.json).
The typed evidence names identify assessment records; they do not
claim a connector automatically extracts or semantically verifies these records.
An assessor must establish the meaning of the record and bind the outcome to the
specific safeguard. Framework tags, generic tickets and service health alone do
not establish these outcomes.

This slice adds five distinct mapped requirements, bringing CSF catalog mapping
coverage to 106/106. All five now earn review credit; CSF has 72/106 reviewed
requirements overall. A reviewed mapping still needs fresh, correctly typed,
explicitly bound passing evidence to support a requirement pass. Absent, stale,
unrelated or non-conclusive evidence cannot establish operating effectiveness. Full catalog
mapping coverage is not certification or complete asset-population coverage.

## Prepare bounded human review batches

```bash
# Shipped-catalog review preparation; does not modify reviews or a lake.
grc-lake frameworks review packet --batch-size 25 --out review-packet.json
# Filtered work uses the same global denominator for milestone reporting.
grc-lake frameworks review packet --framework nist-csf-2.0 --out csf-review.json
# Include one organization's current decisions when reviewing for that tenant.
grc-lake frameworks review packet --lake ./lake --out org-review.json
```

Each batch groups distinct requirements and shows every candidate mapping,
its source reference, the complete catalog requirement, the safeguard operating
and evidence contract, the semantic basis hash and the latest decision ID.
The packet leaves decision, reviewer and rationale blank. A citation's presence
is reported separately from source validation; it does not establish equivalence.
Alternative mappings never multiply a requirement's potential coverage credit.

The summary reports the full catalog denominator and additional distinct
requirements needed for 80% mapped and 50% reviewed coverage. Review all
applicable clauses, parameter choices, dependencies, evidence specificity and
limitations. Reject or request changes when the contract does not establish the
mapping; targets do not justify approval. Packet hashes detect changed content,
not authenticity or review completion.

For a local decision based on a previously inspected packet, pass
`--review-basis <review_basis_sha256> --expected-decision-id <id-or-none>` with
the existing decision flags. The trusted local CLI remains compatible with
immediate decisions without these optional tokens; HTTP submissions require
them. Never reuse old tokens after a concurrent decision or definition change.

Organization decisions affect only that organization's coverage. A shipped
maintainer-reviewed milestone requires actual human decisions about the
catalog mappings, with reviewer identity, rationale and source evidence carried
into a catalog PR and validated against its current basis. This command does
not import decisions, impersonate a reviewer, or promote proposals.
