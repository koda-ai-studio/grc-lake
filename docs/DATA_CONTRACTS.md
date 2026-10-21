# Evidence schemas, paths, and formats

GRC Lake reads supported source systems into an owned assessment lake. A source
lake, the platform tenant, and the assessment storage directory are separate
identities. Cloud hosting does not make every storage backend interchangeable.
See [deployment](DEPLOYMENT.md) and [lake compatibility](BRING_YOUR_OWN_LAKE.md).

## Read and write boundaries

| Boundary          | Input / read path                                                  | Output / write path                                         | Contract                                                                                                                                |
| ----------------- | ------------------------------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Collection        | Connector-specific read-only provider calls or mapped lake queries | Mutable raw intake                                          | Adapter output must satisfy the raw event contract; source scope and completeness are separate checks.                                  |
| Normalization     | UTF-8 JSONL, one raw object per nonblank line                      | `bronze/raw_events.jsonl`, `silver/normalized_events.jsonl` | Bronze retains the raw object and its hash. Silver normalizes identity, timestamps, evidence types, and bindings.                       |
| Evaluation        | Normalized evidence plus the effective catalog                     | `gold/` assessment artifacts and `mart/` SQL projections    | Deterministic results; observation, availability, freshness, and verdict eligibility have different meanings.                           |
| Publication       | Staged `generations/<id>/`                                         | Atomic `.active-generation` pointer                         | Artifacts are verified before publication; shared JSON writes reject sealed generation files.                                           |
| API / MCP         | Authorized tenant lake and pinned generation                       | JSON response envelopes                                     | Preserve pagination and generation metadata; compare identities across requests. Operational mutations use separate authorized actions. |
| Portable export   | Verified generation and explicit platform tenant                   | New Parquet bundle directory                                | Versioned typed evidence, manifest, hashes, and row counts; refuses an existing output.                                                 |
| Destination sinks | Selected silver/gold fields                                        | Explicit DuckDB, ClickHouse, or Snowflake destination       | Each sink has its own table specification. These projections are not complete copies of the assessment lake.                            |

Server paths must be confined to the authorized root. Shared IO supports this
through `base_dir`; local CLI paths rely on the caller's filesystem permissions.
Source connectors being read-only does not mean GRC Lake performs no writes:
it writes its own state, assessment artifacts, and explicitly configured exports.
POSIX publication requirements and retained-history behavior are documented in
[assessment generations](ASSESSMENT_GENERATIONS.md).

## JSON and identity rules

Canonical JSON schemas live in `data/schemas/`. Run
`python tools/sync_package_resources.py` after edits to regenerate packaged copies.
The runtime validator also enforces semantic rules such as duplicate scoped event
identities and supported timestamp bounds. JSON Schema alone is not the complete
runtime validator. Strict JSON parsing rejects duplicate keys, nonfinite numbers,
invalid Unicode, and excessive nesting.

Raw required fields are `event_id`, `tenant_id`, `event_time`, `source`,
`event_type`, and an object `entity` with a nonempty string `asset_id`, `id`,
or legacy `name`. Timestamps require an explicit timezone.
Provider-specific attributes are allowed; arbitrary extra properties are not
silently treated as evaluated evidence.

In normalized rows, legacy `tenant_id` and its alias `source_account_id` identify
the **source account**. The generation manifest's `tenant_id` identifies the
**platform owner**. Never use a row's source account as an authorization decision.
Connector-qualified records retain both `connector_id` and `source_event_id`;
unqualified records omit both. `raw_sha256` is a lowercase SHA-256 hex digest.

`evidence_available` is Boolean. `evidence_types`, `control_ids`, and
`safeguard_ids` are lists. An observed event can have available, fresh evidence
without supporting a pass/fail verdict. Use the frozen results and eligibility
fields, not the mere presence of a reference or a declared control binding.

## Generation marts and evolution

`trustops.mart.v2` adds source account, connector identity, availability, evidence
types, and safeguard bindings to generation-local SQLite and DuckDB
`normalized_events`; `evidence_freshness` also retains `verdict_eligible`.
List columns use the `_json` suffix and contain JSON arrays. SQLite stores
Booleans as 0/1; DuckDB uses Boolean columns. Legacy materializer inputs with
unknown availability or eligibility remain SQL NULL, not an inferred success.
DuckDB timestamps store UTC wall time; JSONL preserves the normalized text form.

`trustops.mart.v3` adds `source_account_id` to asset risk and uses it with
`asset_id` as the generation-local asset key. Destination asset-risk keys also
include platform `tenant_id`; see [upgrade guidance](DATA_MODEL.md#upgrade-and-rollback).

The mart version is recorded in the manifest and included in dependency
invalidation. The next incremental evaluation rebuilds an old projection into a
new generation even when raw evidence is unchanged. Historical generations keep
their original schema. Named-column queries are preferable to positional
`SELECT *` consumers when adding columns.

Normalized schema v1 remains compatible with older rows; transformation versions
identify added fields: v2 safeguard bindings, v3 optional connector identity,
v4 availability, v5 source account identity, and v6 strict entity admission
with scoped asset projections. The JSON schema validates new
fields when present; version-aware portable export validates the fields required
by the recorded transformation. This compatibility does not authorize editing
retained evidence to fabricate missing fields.

The separate destination sinks still publish narrower table projections and do
not carry all of these generation-mart fields. For complete normalized evidence
use JSONL or [Parquet](PARQUET_EXPORT.md); use the frozen generation for assessment
results. [Iceberg REST](ICEBERG_REST.md) has its own schema and publication rules.
Local contract tests do not establish live provider compatibility, distributed
filesystem guarantees, or production throughput.
