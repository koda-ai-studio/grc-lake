# Evidence investigation

Open **Graph → Evidence investigation** to inspect a bounded neighborhood of recorded relationships. Controls & CCF, Environment, and Findings, sources & vendors use the same model. Choose a starting point, search the server-side list, and select a depth of one, two, or three hops. Select a node to see its evidence, owner, severity, observation time, and next action; focus it to drill into another neighborhood. **Roll up** restores the previous starting point with its hop depth, visible layers, framework and evidence pages, and pinned model version. Without navigation history it follows a visible recorded containing framework, family, environment, or account. Navigation waits for the current neighborhood request to finish, so retained loading content cannot become the wrong parent. **Expand graph workspace** gives the graph the full browser screen, with depth and zoom controls still available; exit with its button or Escape.

Neighborhoods prioritize nearby nodes before deeper records, with upstream context first at the same depth. Controls walk upstream and downstream separately; a shared framework does not pull in sibling controls. Producer sources remain context without expanding their other records.

The console requests at most 150 nodes per neighborhood. The API allows 1–300 and reports truncation and the matching node count. Starting points are paginated in groups of 50; search narrows that list. Optional layers remove nodes before traversal. A missing starting point produces an explicit empty result. The full framework and repository maps remain available separately.

The canvas lays out at most 500 visible nodes and 1,000 visible relationships. Above either limit it shows the counts and asks for a narrower view; it does not silently discard relationships to fit. Framework, control, workflow and stale-evidence map filters advance one hop at a time, independent of edge order. These browser bounds are not a production capacity qualification.

**Fit View** restores readable zoom. When the full map cannot fit at that zoom, pan or use the minimap to follow it; zoom out for an overview. The visible line-style key distinguishes recorded links, reviewed mappings, pending review and invalid bindings. A mapping without a review state reads **Review not recorded** and uses an unreviewed line style. Only explicit maintainer or organization review receives reviewed styling; rejected and needs-changes states remain distinct.

## Relationship meaning

- Requirements connect to exact evidence records and their recorded assets. Sharing an evidence type does not create a relationship. Source-account IDs distinguish identically named assets.
- CCF categories contain families and safeguards. Requirement-to-safeguard edges carry their effective mapping review state. Proposed or rejected mappings are not assessed coverage. Recorded `safeguard_ids` are required to connect safeguard evidence.
- Environment and account nodes use recorded identifiers. Repository structure and governance context come from bronze repository observations. Public-mode gaps remain visible.
- Findings retain observed severity and the current recorded triage state. Resolving a workflow does not change the original evidence.
- Sources and tools produce evidence. Vendor assessments are separate entities. In **Vendor risk → Linked services and assets**, record the exact source-account and asset IDs. Unknown references stay unlinked; provider names never imply vendor assessment coverage.

- Walking from a requirement or safeguard also returns the source that produced each reached evidence record, with its `produces` edge. The source is context only: the walk does not continue into that source's other records.
- A safeguard-to-evidence `has_evidence` edge whose asset has more than one recorded type, or a type the safeguard's `asset_types` does not accept, carries `binding: "invalid_asset_type"` and a `binding_reason`. The CCF assessment applies the same rule and treats such a binding as `not_evaluated`; the edge is not supporting evidence.

The graph represents evidence relationships, not network reachability, attack paths, complete inventory, or live provider qualification. No compliance pass is inferred from a graph path.

### Requirement node fields

A requirement (`control`) node keeps two separate results:

| Field                      | Meaning                                                                                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`                   | Control posture from `gold/control_posture.jsonl`: the evaluation rule applied to evidence tagged with the requirement. `not_evaluated` when no posture row exists. |
| `rule_reasons`             | Posture rule reasons (list of strings), for example why the requirement fails. Empty when no posture row exists.                                                    |
| `evaluation_rule`          | Posture evaluation rule name, or `null`.                                                                                                                            |
| `open_event_count`         | Open violations counted by posture, or `null` when no posture row exists.                                                                                           |
| `ccf_status`               | The requirement's result in `gold/ccf_assessment.json` (for example `not_evaluated`, `unmapped`, `fail`, `pass`). `not_evaluated` when absent.                      |
| `reviewed_safeguard_count` | Safeguards with an attestable (reviewed) implementation mapping to the requirement.                                                                                 |
| `proposed_safeguard_count` | Implementation mappings still pending review; they never count as coverage.                                                                                         |

A posture `pass` is not a framework result. Only `ccf_status` reflects the reviewed CCF crosswalk, and it stays `not_evaluated` while mappings are proposed or the review log is unverified.

Graph versions are content hashes built in a deterministic order, so every worker process and restart serving the same generation and overlays returns the same `version`.

## API

`GET /api/v1/graph/investigation` requires `read` scope and uses the authenticated tenant's lake and vendor assessments.

| Parameter     | Meaning                                                     |
| ------------- | ----------------------------------------------------------- |
| `view`        | `controls`, `environment`, or `investigation`               |
| `root`        | Exact graph node ID; omitted selects a starting point       |
| `depth`       | `1`, `2`, or `3` (default `2`)                              |
| `limit`       | Returned node bound, `1`–`300` (default `150`)              |
| `root_offset` | Starting-point offset, in groups of 50                      |
| `search`      | Starting-point search, up to 200 characters                 |
| `layers`      | Comma-separated node kinds                                  |
| `version`     | Previous response version; a changed graph requires refresh |

Generated evidence and frozen requirement/safeguard catalogs are read within one pinned generation. When frozen catalogs are unavailable in a legacy lake, catalog definitions use the current catalog. Taxonomy labels are catalog navigation metadata. Current vendor and triage records are operational overlays; the response version covers those overlays as well as graph contents.

The API reuses completed models within a server process when the pinned generation
has frozen requirement and safeguard catalogs. The cache key includes the resolved
lake root, generation manifest, every graph input file version, current triage,
vendor records and navigation catalogs. File versions use content hashes for
recent writes and filesystem identity/change timestamps for settled files, as in
the lake's JSONL indexes. Changing a generation or overlay cannot reuse the previous
key. Mutable legacy lakes and generations missing frozen catalogs rebuild normally.

The process retains at most eight models, one per lake, within a 128 MiB budget of
accounted Python object sizes. Models expire after 60 seconds without a read, with
expired entries removed on the next cache access; least recently used models are
evicted when necessary. Oversized models are returned without retention. When the
models in active use do not fit the budget together, requests that alternate between
them rebuild each time and can be slower than running without the cache; see
[retention sizing](benchmarks/INVESTIGATION_CACHE.md#retention-sizing). This is
not a total RSS bound: active builds, active readers, temporary allocations and
Python allocator overhead are additional. No graph cache is written to disk. See the
[reuse measurements](benchmarks/INVESTIGATION_CACHE.md) for observed cold/warm
latency and memory tradeoffs.

Concurrent requests for the same key share a completed build. Waiting readers
check cancellation every 50 ms; canceling one waiter does not cancel other
readers. Failed builds are never retained. Input-version changes detected across construction
prevent retention. Returned nodes and edges are independent copies, so a caller
cannot mutate another response. Authentication and graph admission still run for
every HTTP request, including cache hits.

A cold read still builds the full server-side model. Depth, layers and search
operate on that model and its derived indexes.
Completed models also retain directed adjacency, original edge positions, node-kind counts, ordered starting points and default roots. These derived indexes count against the same 128 MiB retention budget and expire or invalidate with their model. Unfiltered warm reads, including requests that explicitly select every available layer, avoid full node/edge scans to rebuild those indexes; response edges retain their original order. Layer filters recompute eligible membership and degree ordering, search scans the indexed starting points, and broad neighborhoods still traverse their matching nodes. Cold builds do extra index construction, and larger retained models can cause earlier eviction. See the [paired measurements](benchmarks/INVESTIGATION_CACHE.md#navigation-index-follow-up) for warm latency, cold cost and process memory.

Neither this bounded reuse nor the response bound establishes constant-memory
indexing, tenant fairness or production-scale qualification.

### Build admission and cancellation

Each server process runs at most `GRC_LAKE_GRAPH_BUILD_CONCURRENCY` graph builds at once (default `4`, integer `1`–`64`; other values stop startup). A request beyond that bound is not queued: it returns `503` with `Retry-After: 1` and error code `graph_build_capacity`. Invalid parameters return `400` without taking a slot.

Each authenticated tenant may use at most `GRC_LAKE_GRAPH_TENANT_CONCURRENCY` of those slots. The default is half the process limit rounded down, with a minimum of one (2 of the default 4). Explicit values must be integers from 1 through the process limit; invalid values stop startup. All users and API keys belonging to a tenant share the limit. Tenant saturation returns `503`, `Retry-After: 1` and `graph_tenant_capacity`; a full process returns `graph_build_capacity`. Limits also apply to warm cached reads and requests waiting for a shared build. Counts are released on success, failure, timeout or disconnect, after the thread stops.

This prevents one tenant from occupying every process slot when the tenant limit is below the process limit. It does not guarantee fairness, reserve a slot for every tenant, or bound waiting time across replicas. Setting equal limits, including a process limit of one, removes that protection. Clients should back off and retry rather than increase parallelism on a rejection. The HTTP benchmark records both rejection codes separately per tenant.

A running build stops at its next checkpoint when the client disconnects or when it exceeds `GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS` (default `60`; `0` disables the deadline). Checkpoints sit between build phases, inside per-record loops, and between batches of at most 128 nodes or edges during version hashing. A single file read or one hash batch is not interrupted. Version tokens retain the same canonical encoding; hashing no longer allocates a complete serialized graph copy. A deadline abort returns `503` with `Retry-After: 5` and code `graph_build_timeout`. An aborted build returns no partial graph, and its slot is released only after the build thread has stopped.

The bound is per process, shared by all tenants of that process, and is not a reviewed capacity budget; see the [investigation benchmarks](benchmarks/INVESTIGATION.md) for measured memory and latency. Multiply by worker processes and replicas when sizing memory.

Vendor asset references are stored in the vendor assessment by migration `0031_vendor_asset_refs`. `PATCH /api/v1/vendor-assessments/{assessment_id}` accepts up to 100 `asset_refs`, each containing `source_account_id` and `asset_id`, and requires `control_manage` scope.

The existing `/api/v1/graph` retains the `evidence_type` node kind for compatibility, but each such node now represents one exact record. Evidence node IDs are content-derived; old type-only deep links must be replaced with a current node ID.

Repository nodes show the recorded GitHub or GitLab provider with a repository badge; unknown hosts retain the generic icon. Click to inspect, double-click or press Shift+Enter to explore recorded connections, and use Roll up to return. Expanded workspace falls back to an in-page view when browser fullscreen is unavailable.

The repository inspector lists evidence and findings present in the bounded view. Evidence outcomes distinguish passing, failing, observed but not evaluated, and settings that are not observable with the collection access. Selected records expose their exact linked controls and review guidance. Missing records do not prove a missing configuration; mappings and source outcomes do not establish whole-framework compliance.
