# Evidence investigation

Open **Graph → Evidence investigation** to inspect a bounded neighborhood of recorded relationships. Controls & CCF, Environment, and Findings, sources & vendors use the same model. Choose a starting point, search the server-side list, and select a depth of one, two, or three hops. Select a node to see its evidence, owner, severity, observation time, and next action; focus it to expand another neighborhood.

The console requests at most 150 nodes per neighborhood. The API allows 1–300 and reports truncation and the matching node count. Starting points are paginated in groups of 50; search narrows that list. Optional layers remove nodes before traversal. A missing starting point produces an explicit empty result. The full framework and repository maps remain available separately.

## Relationship meaning

- Requirements connect to exact evidence records and their recorded assets. Sharing an evidence type does not create a relationship. Source-account IDs distinguish identically named assets.
- CCF categories contain families and safeguards. Requirement-to-safeguard edges carry their effective mapping review state. Proposed or rejected mappings are not assessed coverage. Recorded `safeguard_ids` are required to connect safeguard evidence.
- Environment and account nodes use recorded identifiers. Repository structure and governance context come from bronze repository observations. Public-mode gaps remain visible.
- Findings retain observed severity and the current recorded triage state. Resolving a workflow does not change the original evidence.
- Sources and tools produce evidence. Vendor assessments are separate entities. In **Vendor risk → Linked services and assets**, record the exact source-account and asset IDs. Unknown references stay unlinked; provider names never imply vendor assessment coverage.

The graph represents evidence relationships, not network reachability, attack paths, complete inventory, or live provider qualification. No compliance pass is inferred from a graph path.

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

The API builds the server-side model before selecting the bounded response. Its processing cost still grows with evidence volume; the response bound is not a claim of constant-memory indexing or production-scale qualification.

Vendor asset references are stored in the vendor assessment by migration `0031_vendor_asset_refs`. `PATCH /api/v1/vendor-assessments/{assessment_id}` accepts up to 100 `asset_refs`, each containing `source_account_id` and `asset_id`, and requires `control_manage` scope.

The existing `/api/v1/graph` retains the `evidence_type` node kind for compatibility, but each such node now represents one exact record. Evidence node IDs are content-derived; old type-only deep links must be replaced with a current node ID.
