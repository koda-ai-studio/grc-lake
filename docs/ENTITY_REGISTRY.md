# Canonical entity registry and binding history

`grc-lake entities export` produces a read-only, versioned JSON projection of
source identities and explicitly supplied canonical entity bindings. It is an
experimental local export. `entities record` optionally persists complete binding
revisions in a separate operational ledger. Neither command changes findings,
assessments, or workflow identities. Recorded bindings can be inspected in the
authenticated investigation graph.

```bash
grc-lake entities export --lake build/lake --tenant-id customer-a > entities.json
```

The caller must select a lake belonging to the named platform tenant. The CLI
argument namespaces the output; it does not authorize access or establish lake
ownership. Source account IDs remain separate from this platform namespace.
Distributed mode rejects these local commands through the existing CLI boundary.

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
canonical JSON payload excluding itself and the optional `generation` and
`binding_history` metadata.
A sealed lake supplies the pinned generation ID and manifest hash separately;
a legacy unsealed lake supplies `generation: null`.

`first_observed_at` and `last_observed_at` bound the observations in the selected
input, in UTC. They do not mean creation, deletion, resolution, or continuous
existence. Reused provider identifiers, renamed source types, and reassigned
accounts require an explicit identity migration; this exporter cannot infer
those transitions. Recorded revisions describe assertion history in append
order, not provider-valid-time intervals. Caller-supplied assertion timestamps
do not override revision order or schedule future activation.

Missing identity/provenance fields, source-account alias disagreement, unknown
manifest fields, invalid or timezone-free timestamps, mismatched tenant
namespaces, missing evidence, and conflicting bindings fail the whole export.
No partial JSON result is printed. The local command caps evidence deliveries
and binding assertions at 100,000 each; this is a work bound, not a capacity
qualification. Missing files fail rather than producing an empty inventory.

## Persisted revisions, supersession and revocation

Record a **complete replacement** binding manifest after reviewing it. Omitting
an existing alias revokes it in the new revision. An empty `entities` array
revokes all aliases. Records retain the operation actor/reason separately from
the actor/reason on each source assertion; both are caller supplied.

```bash
grc-lake entities record --lake build/lake --tenant-id customer-a \
  --bindings entity-bindings.json --actor operator-1 \
  --reason "Verified device enrollment references" \
  --expected-revision 0 --request-id enrollment-import-1

grc-lake entities history --lake build/lake --tenant-id customer-a

grc-lake entities export --lake build/lake --tenant-id customer-a \
  --stored-bindings > current-entities.json

grc-lake entities export --lake build/lake --tenant-id customer-a \
  --stored-bindings --revision 1 > recorded-bindings-v1.json
```

The first write requires `--expected-revision 0`; later writes must match the
latest recorded revision. The check and append share an OS file lock, so a
concurrent editor cannot silently overwrite a newer revision. Repeating the
same request ID with the same manifest, actor, reason, and expected revision
returns the original receipt, even after source evidence changes. Reusing that
ID with a different request fails. A reordered manifest is a different write
request even when its exported registry content would be equivalent.

The ledger lives at `entities/bindings.jsonl`, outside sealed assessment
generations. Rows follow
[`entity-binding-revision.schema.json`](../data/schemas/entity-binding-revision.schema.json).
Each row includes its full binding manifest, the exact normalized observations
referenced by those bindings, pinned generation metadata when available, and
added/removed/changed source-entity IDs. Unbound inventory observations are not
copied into the ledger. Evidence hashes in historical exports can therefore be
recomputed from retained rows even when the live generation has changed or
been removed. Raw evidence objects are not copied or independently verified.

`--stored-bindings` without a revision checks the latest bindings against current
evidence and includes the current inventory. If referenced observations are no
longer present, it fails until bindings are explicitly refreshed or revoked.
`--stored-bindings --revision N` exports only that revision's recorded binding
evidence, with `binding_history.mode: recorded_binding_evidence`; it is not a
complete inventory snapshot or a claim about current state. An empty replacement
can be recorded without the source file, allowing revocation after evidence loss.
Canonical keys cannot change entity type, including after revocation.

Readers and writers verify the entire hash chain and revision sequence before
using it. Altered content, reordered entries, and torn appends fail closed. The
chain is unkeyed: it does not authenticate operators or prevent a filesystem
owner from rewriting the entire history or deleting a valid suffix. Retain
receipts/tip hashes and backups outside the lake for independent comparison.
No automatic history pruning or repair is performed.

This local implementation caps a revision at 1,000 source aliases and the
ledger at 1,000 revisions or 32 MiB, whichever is reached first. Writes exceeding
those bounds fail without pruning prior records. Those limits bound local
resource use; they are not a capacity qualification. Authenticated approval,
and provider-valid-time lifecycles are outside this version.

## Investigation graph

The environment view includes recorded canonical entities and alias assertions.
Select a canonical entity to inspect its aliases and their exact normalized
observation hashes. Assertions show the caller-supplied actor, timestamp, reason,
and ledger revision. Dashed assertion links express a claimed identity, not an
approved mapping or a compliance result. Existing asset and finding identities
remain unchanged.

Only aliases whose exact observation exists in the selected generation and is
not classified stale receive identity links. Missing and stale anchors remain
visible as disconnected assertions requiring review. Revoked aliases disappear
from the current graph; ledger changes invalidate cached graph versions. No
name, email, hostname, or shared native ID is used to infer equivalence.

The HTTP route takes the platform namespace from the authenticated tenant.
Unscoped library calls omit the canonical layer. Invalid or mismatched history
fails the graph request; a busy writer produces a retryable response. History
verification observes graph cancellation checkpoints and retains the ledger
bounds above. This does not qualify production capacity or authenticated
approval of CLI assertions.
