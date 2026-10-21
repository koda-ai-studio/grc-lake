# Canonical entity registry export

`grc-lake entities export` produces a read-only, versioned JSON projection of
source identities and explicitly supplied canonical entity bindings. It is an
experimental local export. It does not change findings, assessments, workflow
identities, or the investigation graph.

```bash
grc-lake entities export --lake build/lake --tenant-id customer-a > entities.json
```

The caller must select a lake belonging to the named platform tenant. The CLI
argument namespaces the output; it does not authorize access or establish lake
ownership. Source account IDs remain separate from this platform namespace.
Distributed mode rejects this local command through the existing CLI boundary.

## Identity and cardinality

| Record           | Identity and meaning                                                                                                                                                                         |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source entity    | SHA-256 of the platform tenant and exact `(source, source_account_id, asset_type, asset_id)` tuple, with a versioned prefix. Case, punctuation, provider and native type remain significant. |
| Canonical entity | SHA-256 of the platform tenant and caller-maintained stable key, with a distinct versioned prefix. The key must represent one logical entity and must not be recycled.                       |
| Alias assertion  | Content-addressed link from exactly one source entity to one canonical entity, retaining the source tuple, observation hash, asserting actor, timestamp and reason.                          |
| Observation      | Content hash of the complete normalized row plus its event ID, raw hash and observation time. Multiple observations attach to one source entity.                                             |

A canonical entity may have multiple source aliases. A source entity may have
at most one binding in an export. Exact duplicates are idempotent; conflicting
bindings are rejected. Source entities are retained even when bound. Unbound
source entities remain unresolved; the exporter does not manufacture canonical
entities or merge on names, email addresses, hostnames, or similar strings.

The source identity tuple is deliberately more specific than the existing
account/asset risk grouping. This additive export does not migrate those marts.
A person and their account are different entities. Two provider accounts owned
by the same person are not aliases of each other. Ownership and other typed
relationships are outside this export; use aliases only for multiple source
representations of the same entity, such as one device observed by two vendors.

## Explicit binding input

First export without bindings to obtain exact source tuples and observation
hashes. Then supply a manifest conforming to
[`entity-bindings.schema.json`](../data/schemas/entity-bindings.schema.json).
For example, the structure for one device alias is:

```json
{
  "schema_version": "1.0",
  "platform_tenant_id": "customer-a",
  "entities": [
    {
      "key": "managed-device-17",
      "entity_type": "device",
      "bindings": [
        {
          "source": "intune",
          "source_account_id": "org-a",
          "asset_type": "device",
          "asset_id": "device-1",
          "evidence_sha256": "REPLACE_WITH_HASH_FROM_EXPORT",
          "asserted_by": "reviewer-1",
          "asserted_at": "2026-10-21T13:00:00Z",
          "reason": "Verified native device enrollment reference"
        }
      ]
    }
  ]
}
```

The placeholder hash must be replaced with an actual 64-character digest from
that source entity's observations. Add a second binding to the same canonical
entity only when there is an explicit basis for equivalent source identity.

```bash
grc-lake entities export --lake build/lake --tenant-id customer-a \
  --bindings entity-bindings.json > entities-with-aliases.json
```

All entity types and aliases are labeled `caller_asserted`. A valid evidence
reference proves that the referenced normalized observation is present for that
exact source tuple. It does **not** prove the alias is true, authenticate the
asserting actor, verify the upstream raw record, or constitute approval. The
manifest is not ingested into an authorization or compliance decision path.
Allowed canonical types are `person`, `account`, `device`, `resource`,
`repository`, `service`, `organization`, and `unknown`; native source types are
preserved separately.

## Replay, integrity and time

Output conforms to [`entity-registry.schema.json`](../data/schemas/entity-registry.schema.json).
Rows and claims are ordered deterministically. Duplicate evidence deliveries
and reordered inputs produce the same content hash. `content_sha256` hashes the
canonical JSON payload excluding itself and the optional `generation` metadata.
A sealed lake supplies the pinned generation ID and manifest hash separately;
a legacy unsealed lake supplies `generation: null`.

`first_observed_at` and `last_observed_at` bound the observations in the selected
input, in UTC. They do not mean creation, deletion, resolution, or continuous
existence. Reused provider identifiers, renamed source types, and reassigned
accounts require an explicit identity migration; this exporter cannot infer
those transitions. Changing or removing a binding changes the next export;
there is no persisted alias approval/revocation history in this version. Retain
manifests and exports when an audit trail is needed.

Missing identity/provenance fields, source-account alias disagreement, unknown
manifest fields, invalid or timezone-free timestamps, mismatched tenant
namespaces, missing evidence, and conflicting bindings fail the whole export.
No partial JSON result is printed. The local command caps evidence deliveries
and binding assertions at 100,000 each; this is a work bound, not a capacity
qualification. Missing files fail rather than producing an empty inventory.
