# Components

## Connectors

Connectors adapt external systems into evidence records. Examples:

- cloud posture export
- vulnerability scanner export
- identity provider access review
- SIEM detection alert
- runtime policy violation
- ticketing/remediation state
- AI/model registry metadata

Connectors should be replaceable and independently testable.

## Evidence Model

The evidence model provides:

- stable `evidence_id`
- source and event type
- asset reference
- collection time
- evidence URI
- raw SHA-256 hash
- freshness metadata

## Control Catalog

The control catalog provides:

- framework
- control identifier
- title
- risk domain
- owner
- evidence requirement
- evaluation frequency

## Evaluation Engine

The evaluation engine consumes evidence and controls. It emits:

- framework score
- control status
- stale evidence
- missing evidence
- violation records
- current posture

## Snapshot Service

The snapshot service freezes current posture into an immutable export with an
assessment hash. Snapshots are for audits, vendor reviews, incidents, releases,
and board reporting.

## Lake Adapters

Application state and warehouse integration have separate ownership:

- Filesystem mode keeps sealed evidence generations on local storage. SQLite or
  PostgreSQL holds operational records; one writable replica owns each lake.
- Distributed mode uses PostgreSQL for coordination and committed manifests,
  with S3-compatible objects for evidence. Replica scratch directories are disposable.
- Snowflake and ClickHouse can supply read-only evidence or receive optional
  post-assessment exports. They do not replace the application state store.
- The sealed SQLite analytics mart is a derived read projection, distinct from
  the operational database. Evaluation rebuilds it from generation inputs.

See the [implementation and test map](../ARCHITECTURE.md#implementation-and-test-map)
and [storage compatibility](../DEPLOYMENT.md#deployment-and-lake-compatibility).
