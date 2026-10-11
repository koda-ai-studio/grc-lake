# Unified data model

Logical relationships across a platform-owned lake and its application database.
Catalog and evidence links are verified references, not SQL foreign keys.

```mermaid
erDiagram
  PLATFORM_TENANT ||--o{ GENERATION : owns
  GENERATION ||--o{ EVIDENCE_EVENT : seals
  GENERATION ||--o{ ASSET_SAFEGUARD_RESULT : freezes
  SOURCE_ACCOUNT ||--o{ ASSET : namespaces
  ASSET ||--o{ EVIDENCE_EVENT : observed_on
  SAFEGUARD_DEFINITION ||--o{ REQUIREMENT_MAPPING : maps
  REQUIREMENT ||--o{ REQUIREMENT_MAPPING : addressed_by
  REQUIREMENT_MAPPING ||--o{ MAPPING_REVIEW : reviewed_against_basis
  SAFEGUARD_DEFINITION ||--o{ ASSET_SAFEGUARD_RESULT : evaluates
  ASSET ||--o{ ASSET_SAFEGUARD_RESULT : assessed
  EVIDENCE_EVENT }o--o{ ASSET_SAFEGUARD_RESULT : supports
  PLATFORM_TENANT ||--o{ SCOPED_IMPLEMENTATION : operates
  SAFEGUARD_DEFINITION ||--o{ SCOPED_IMPLEMENTATION : versioned_basis
  PLATFORM_TENANT ||--o{ GOVERNANCE_DECISION : proposes
  GOVERNANCE_DECISION ||--o{ GOVERNANCE_REVIEW : records
  GENERATION ||--o{ GOVERNANCE_DECISION : evidence_basis
  GOVERNANCE_DECISION o|--o{ GOVERNANCE_DECISION : extends
  SCOPED_IMPLEMENTATION o|--o| SCOPED_IMPLEMENTATION : revises
  PLATFORM_TENANT ||--o{ REMEDIATION_TASK : tracks
  REMEDIATION_TASK ||--o{ VERIFICATION_RECEIPT : retests
  GENERATION ||--o{ VERIFICATION_RECEIPT : proves_at_time
```

`ASSET` has the composite logical key `(source_account_id, asset_id)` within a
platform tenant's lake. Evidence's legacy `tenant_id` means source account;
application records and the generation manifest's `tenant_id` mean platform owner.
One source account can supply evidence to separately authorized deployments; its
identifier alone is never an authorization boundary.

| Layer                           | Storage                                                  | Authority                                                            |
| ------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------- |
| Evidence and assessment         | Sealed generation: bronze, silver, gold, pinned catalogs | Deterministic evaluation over observed scope                         |
| Indexed reads                   | SQLite mart in the same generation                       | Derived projection, rebuilt from assessment                          |
| Mapping decisions               | Tenant lake's verified review ledger                     | Attributable mapping review, not effectiveness                       |
| Scoped operations and decisions | Tenant-scoped server SQLite/PostgreSQL                   | Human declarations and independent reviews, not verdict overrides    |
| Auth and workflows              | Server database                                          | Tenant membership, keys, sessions, remediation, risk and agent state |
| Snapshots                       | Snapshot artifacts and hash-chained ledger               | Point-in-time assessment history                                     |

A governance decision retains its content, scope, evidence references, catalog
basis and reviewer history. Extensions create new proposals; only approval
supersedes an earlier decision. Expiry, revocation or changed definitions make an
approved decision inactive. None of these records convert a failing or unknown
assessment to passing.

See [data model](../DATA_MODEL.md), [architecture](../ARCHITECTURE.md),
[CCF reads](../CCF_READS.md), and [governance](../GOVERNED_REMEDIATION.md).
