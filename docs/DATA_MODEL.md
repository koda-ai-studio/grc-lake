# Data model

GRC Lake separates collected evidence, deterministic assessment, and human
operating decisions. A reviewed mapping is not a passing control. An accepted
risk, exception, or implementation record does not supply evidence or change a
verdict.

## Identity and ownership

| Identity        | Meaning and scope                                                                                                                                                                                |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Platform tenant | Authenticated organization; owns a lake, its sealed generation and server database records. The generation manifest carries this `tenant_id`.                                                    |
| Source account  | Account or workspace reported by a connector. Normalized evidence exposes `source_account_id`; the legacy evidence field `tenant_id` remains an equal alias. Neither authorizes platform access. |
| Asset           | Within a platform-owned lake, `(source_account_id, asset_id)` identifies an observed asset. An asset ID alone is ambiguous across source accounts.                                               |
| Evidence event  | Normalized `event_id`, with connector/source event identity and `raw_sha256` preserving provenance. References are resolved within the owned generation.                                         |
| Requirement     | A versioned catalog `control_id` in a named framework.                                                                                                                                           |
| Safeguard       | An operated CCF activity identified by `safeguard_id`; its definition digest binds objective, evidence requirements, rule, asset/evidence types, frequency, owner and mapping source.            |
| Mapping         | A safeguard-to-framework-requirement relationship, including relationship type, version, source and review state.                                                                                |

Normalization v5 adds the source-account alias. Historical v1–v4 exports remain
readable without rewriting saved evidence. Warehouse gold `tenant_id` is platform
ownership; silver `tenant_id` is the legacy source-account field. Do not join these
columns as if they represented the same identity.

## Assessment and governance

| Entity                      | Contract                                                                                                                                                                               |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Raw and normalized evidence | Source facts and references; observations may describe inventory without asserting pass or fail.                                                                                       |
| Asset safeguard result      | Evaluates explicitly bound evidence for one safeguard and source-account asset. Ambiguous assets remain visible.                                                                       |
| Framework/control result    | Evaluates required evidence and freshness. An `observed` row cannot refresh an old verdict or provide operating test credit. Unknown and unavailable evidence cannot establish a pass. |
| Control workpaper           | Separates available design evidence, eligible period samples, population gaps and human judgment; output schema `trustops.control_assurance.v2`.                                       |
| Assessment generation       | Catalog, evidence and derived outputs published atomically with artifact hashes. Readers pin one generation per operation.                                                             |
| Snapshot                    | Point-in-time assessment with a predecessor hash in the snapshot ledger. A snapshot is distinct from an evaluation generation.                                                         |
| Scoped implementation       | Immutable revision declaring owner, system, cadence, controls/safeguards and optional assets, with evidence and definition digests. Supersession retains earlier content.              |
| Governance decision         | Evidence-backed, scoped, expiring disposition: risk acceptance, by design, not applicable, inherited or compensating. Independent human approval binds the exact proposal hash.        |
| Governance review           | Append-only approval/rejection or revocation. An approved extension supersedes the prior decision; a pending extension leaves it unchanged.                                            |

Organization mapping approvals bind a versioned review basis containing the
safeguard semantics, mapping member and requirement. Semantic changes or legacy
approvals without that basis require fresh review. Rejections and requests for
changes remain holds until explicitly superseded. No migration invents approvals.

Governance decisions separately verify their saved safeguard and requirement
basis against the installed catalog. Changed definitions disable active status
and block approval until a new proposal is reviewed. Historical records remain
readable. Custom catalog definitions must match the server catalog before their
proposals can become active.

## Physical storage and read surfaces

| Store                                       | Contents and purpose                                                                                                                                                                                                          |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bronze/`, `silver/normalized_events.jsonl` | Replayable evidence and normalized facts inside a generation.                                                                                                                                                                 |
| `catalog/` in a generation                  | Pinned control and safeguard inputs for reproducible evaluation.                                                                                                                                                              |
| `gold/`                                     | Control posture, tests, asset risk, CCF results and assessment outputs.                                                                                                                                                       |
| Sealed SQLite mart                          | Derived indexed CCF rows, compact asset summaries and paged evidence/reason references. Rebuilt by evaluation; never the source of truth.                                                                                     |
| Mapping review JSONL ledger                 | Tenant-local attributable mapping decisions, separate from shipped catalog data.                                                                                                                                              |
| Server SQLite/PostgreSQL                    | Auth, workflow state, risks, scoped implementation revisions, governance proposals and reviews. API queries enforce tenant scope; composite governance foreign keys additionally guard databases with FK enforcement enabled. |
| Optional warehouse exports                  | Copies of committed generation data. Export success and assessment publication are separate results.                                                                                                                          |

Use `/api/v1/ccf/asset-results?include_evidence=false` for compact pages and
`/api/v1/ccf/evidence-links` for bounded detail. Full result reads retain their
compatibility contract. New governance records are available through authenticated
server APIs; they are not automatically injected into workpapers or evaluated
results, and do not yet have a dedicated console editor.

## Upgrade and rollback

Database migration `0030` adds governance tables without altering existing risk or
exception records. Back up the database before upgrading. Export new records and
reviews before downgrading: downgrade removes these new tables. Restoring a
backup is the recovery path for their history; a downgrade cannot reconstruct it.

Normal evaluation rebuilds derived artifacts with normalization v5, evaluation v9
and CCF projection v2. Existing sealed generations remain unchanged. Projection
v1 remains readable through the existing full-results API; compact/link reads
require reevaluation. Admission failures leave the current generation in place.

## Related contracts

- [Unified model diagram](diagrams/unified-data-model.md)
- [Raw event schema](../data/schemas/raw-security-event.schema.json)
- [Normalized event schema](../data/schemas/normalized-event.schema.json)
- [Mapping review](MAPPING_REVIEW.md)
- [Workpapers](CONTROL_TEST_WORKPAPERS.md)
- [Governed decisions and remediation](GOVERNED_REMEDIATION.md)
- [CCF reads](CCF_READS.md) and [scale limits](AUDIT_SCALE.md)
