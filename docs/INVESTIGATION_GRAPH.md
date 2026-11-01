# Evidence investigation

Open **Graph → Evidence investigation** to inspect a bounded neighborhood of recorded relationships. Controls & CCF, Environment, and Findings, sources & vendors use the same model. Choose a starting point, search the server-side list, and select a depth of one, two, or three hops. Select a node to see its evidence, owner, severity, observation time, and next action; focus it to drill into another neighborhood. **Roll up** restores the previous starting point with its hop depth, visible layers, framework and evidence pages, and pinned model version. Without navigation history it follows a visible recorded containing framework, family, environment, or account. Navigation waits for the current neighborhood request to finish, so retained loading content cannot become the wrong parent. **Expand graph workspace** gives the graph the full browser screen, with depth and zoom controls still available; exit with its button or Escape.

Neighborhoods prioritize nearby nodes before deeper records, with upstream context first at the same depth. Controls walk upstream and downstream separately; a shared framework does not pull in sibling controls. Producer sources remain context without expanding their other records.

The console requests at most 150 nodes per neighborhood. The API allows 1–300 and reports truncation and the matching node count. Starting points are paginated in groups of 50; search narrows that list. A missing starting point produces an explicit empty result. The full framework and repository maps remain available separately.

**Visible relationship layers** hide node kinds within the neighborhood already loaded; they do not request a different neighborhood. The console requests every layer, so hiding a layer keeps your place, showing it again restores the same nodes, and the status line compares shown with loaded nodes and relationships. Hidden nodes still count toward the 150-node bound; when a response is truncated the status line says so. Inspecting a relationship whose endpoint is hidden turns that layer back on and keeps **Focus direct relationships** when the endpoint is a direct link. The live console and the static demo behave the same way. The API's `layers` parameter is different: it removes nodes before traversal, so it can return a different neighborhood (see [API](#api)).

The investigation keeps its state in the page URL, so reload, back/forward and a shared link restore it:

| URL parameter | Meaning                                                                                        |
| ------------- | ---------------------------------------------------------------------------------------------- |
| `root`        | Starting point node ID; omitted uses the default starting point                                |
| `view`        | `controls`, `environment` or `investigation`, when it differs from the one implied by `root`   |
| `depth`       | `1` or `3`; omitted means two hops                                                             |
| `hide`        | Comma-separated hidden optional layers                                                         |
| `trail`       | Repeated, one per drill-down level (at most 20), oldest first; **Roll up** returns to the last |
| `direct`      | Node shown with **Focus direct relationships**                                                 |
| `node`        | Node open in the inspector                                                                     |

Choosing a starting point, drilling down, rolling up and direct focus add a history entry. Layer, depth and selection changes update the current entry. Starting-point pages, framework and evidence pages, and the pinned graph version are not in the URL. A `direct` or `node` ID that is not in the loaded neighborhood is ignored; an unknown `root` shows **Starting point not found**.

The canvas lays out at most 500 visible nodes and 1,000 visible relationships. Above either limit it shows the counts and asks for a narrower view; it does not silently discard relationships to fit. Framework, control, workflow and stale-evidence map filters advance one hop at a time, independent of edge order. These browser bounds are not a production capacity qualification.

Investigation opens with the entire loaded neighborhood in view, including when the inspector is open. The **Fit View** icon restores that overview. **+** reaches readable zoom, then zooms in further; **−** zooms out. Pan the canvas to follow relationships when enlarged. The chosen view refits when the canvas resizes or expands. Lane headings distinguish assurance hierarchy from evidence lineage without adding nodes or relationships. The visible line-style key distinguishes recorded links, reviewed mappings, pending review and invalid bindings. A mapping without a review state reads **Review not recorded** and uses an unreviewed line style. Only explicit maintainer or organization review receives reviewed styling; rejected and needs-changes states remain distinct.

## Relationship meaning

- Requirements connect to exact evidence records and their recorded assets. Sharing an evidence type does not create a relationship. Source-account IDs distinguish identically named assets.
- CCF categories contain families and safeguards. Requirement-to-safeguard edges carry their effective mapping review state. Proposed or rejected mappings are not assessed coverage. Recorded `safeguard_ids` are required to connect safeguard evidence.
- Environment and account nodes use recorded identifiers. Repository structure and governance context come from bronze repository observations. Public-mode gaps remain visible.
- Findings retain observed severity and the current recorded triage state. Resolving a workflow does not change the original evidence.
- Sources and tools produce evidence. Vendor assessments are separate entities. In **Vendor risk → Linked services and assets**, record the exact source-account and asset IDs. Unknown references stay unlinked; provider names never imply vendor assessment coverage.

- Walking from a requirement or safeguard also returns the source that produced each reached evidence record, with its `produces` edge. The source is context only: the walk does not continue into that source's other records.
- A safeguard-to-evidence `has_evidence` edge whose asset has more than one recorded type, or a type the safeguard's `asset_types` does not accept, carries `binding: "invalid_asset_type"` and a `binding_reason`. The CCF assessment applies the same rule and treats such a binding as `not_evaluated`; the edge is not supporting evidence.

The graph represents evidence relationships, not network reachability, attack paths, complete inventory, or live provider qualification. No compliance pass is inferred from a graph path.

### Reading hierarchy and directed links

The guide separates assurance mappings (framework → control → safeguard), CCF
taxonomy (category → family → safeguard), and evidence lineage (source →
observation → asset). It explains node roles; it does not add relationships to
the recorded graph. Turn on **Show relationship labels** to read edge meanings
on the canvas. Proposed and invalid bindings retain their separate labels.

The investigation layout keeps assurance above evidence lineage, with separate
source, observation and asset columns. Recorded neighbors influence row alignment;
shared sources and assets appear once, with every loaded link retained. Right-angle
connectors use the gaps between cards. Assurance bindings enter observation cards
from above; source links enter from the left. Selecting a node emphasizes its direct
links while keeping the surrounding nodes readable. Use **Focus direct relationships**
to show only the selected node and its incoming/outgoing links. Visible counts
compare that subset with the loaded neighborhood; **Show full neighborhood** restores
all loaded nodes. This local focus does not fetch additional evidence.

Readable titles keep the original record label in the inspector. Dates display in
UTC; **Exact recorded timestamps** retains the original precision and timezone offset.

**Selected relationships and mapping review state** separates incoming from
outgoing links, identifies source-account scope where recorded, and lets you
inspect either endpoint. Each direction pages five links at a time. Counts cover
the loaded neighborhood only; response truncation does not imply that omitted
relationships do not exist. Arrow direction is a relationship, not a lifecycle
completion signal or evidence of a compliance pass.

### Evidence lifecycle

The investigation inspector separates the source observation time from the
recorded collection time and the freshness evaluation time. A freshness deadline,
when recorded, comes from that evidence's saved freshness projection. These are
assessment-time facts, not a continuously updated clock or proof of a successful
connector run. Missing timestamps display **Not recorded**; an observation time
is never substituted for missing collection metadata in this view.

The freshness projection is matched to the exact account, event and asset, with
the existing event-wide fallback only when a projection has no asset identifier.
The graph preserves the evidence's outcome and provenance. Review, remediation,
re-verification and framework attestation require their own receipts; these
three timestamps do not claim that those later steps occurred.

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

| Parameter     | Meaning                                                         |
| ------------- | --------------------------------------------------------------- |
| `view`        | `controls`, `environment`, or `investigation`                   |
| `root`        | Exact graph node ID; omitted selects a starting point           |
| `depth`       | `1`, `2`, or `3` (default `2`)                                  |
| `limit`       | Returned node bound, `1`–`300` (default `150`)                  |
| `root_offset` | Starting-point offset, in groups of 50                          |
| `search`      | Starting-point search, up to 200 characters                     |
| `layers`      | Comma-separated node kinds; others are removed before traversal |
| `version`     | Previous response version; a changed graph requires refresh     |

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
Python allocator overhead are additional. This in-memory cache is separate from the optional prepared disk index described below. See the
[reuse measurements](benchmarks/INVESTIGATION_CACHE.md) for observed cold/warm
latency and memory tradeoffs.

Concurrent requests for the same key share a completed build. Waiting readers
check cancellation every 50 ms; canceling one waiter does not cancel other
readers. Failed builds are never retained. Input-version changes detected across construction
prevent retention. Returned nodes and edges are independent copies, so a caller
cannot mutate another response. Authentication and graph admission still run for
every HTTP request, including cache hits.

Without a matching prepared index, a cold read still builds the full server-side model. Depth, layers and search
operate on that model and its derived indexes.
Completed models also retain directed adjacency, original edge positions, node-kind counts, ordered starting points and default roots. These derived indexes count against the same 128 MiB retention budget and expire or invalidate with their model. Unfiltered warm reads, including requests that explicitly select every available layer, avoid full node/edge scans to rebuild those indexes; response edges retain their original order. Layer filters recompute eligible membership and degree ordering, search scans the indexed starting points, and broad neighborhoods still traverse their matching nodes. Cold builds do extra index construction, and larger retained models can cause earlier eviction. See the [paired measurements](benchmarks/INVESTIGATION_CACHE.md#navigation-index-follow-up) for warm latency, cold cost and process memory.

Neither this bounded reuse nor the response bound establishes constant-memory
indexing, tenant fairness or production-scale qualification.

### Prepared indexes for large inventories

Operators can run `grc-lake graph prepare-index --lake /path/to/lake` after publishing
an assessment generation. Large investigation reads reuse a matching disk-backed
index across processes. Preparation preserves the graph version, exact relationships,
counts, navigation order and evidence semantics. It does not increase the browser's
node limit or infer a compliance verdict.

See [prepared investigation indexes](benchmarks/PERSISTENT_GRAPH.md) for tenant scope,
invalidation, disk limits, recovery and a benchmark that varies records, findings
and assets independently. Large unprepared or invalidated inventories retain the
existing in-memory fallback; preparation is an explicit operator step.

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
