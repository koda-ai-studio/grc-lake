# Collection completeness

A connector sync must finish every required read before publishing evidence or advancing its watermark. An error leaves the prior raw evidence, assessment and watermark available; the run is recorded as an error so the operator can retry after correcting the source problem.

The shared cursor iterator raises `IncompleteCollectionError` if another page remains when its page budget is reached. Its `cursor` attribute supports explicit resumption by the caller. Provider cursors are excluded from the exception text and persisted run errors. A caller that consumes only part of the iterator has not established completion.

GCP posture collection distinguishes unavailable scope from malformed evidence. A missing organization-policy client, disabled API or denied permission records a named coverage gap and allows other readable collections to proceed. If all three collections are unavailable, the sync fails. These gap records do not establish passing or failing controls.

Malformed IAM bindings, policy identities, asset identities, collection envelopes or IAM member/condition fields fail the entire sync. SDK iterators are consumed to completion; an unclassified failure on a later page fails the sync, while a classified access denial records the unavailable collection as a gap. Records from a failed collection are discarded. A successful empty response remains valid.

Offline GCP fixtures must provide all three files: `iam_bindings.json`, `org_policies.json` and `assets.json`. Use an explicit `[]` for a successfully read empty collection. Missing files, invalid JSON, malformed records and envelopes with a remaining `nextPageToken` are errors, not empty inventories. IAM and asset fixtures also accept the existing `bindings` and `assets` envelopes.

Configure Application Default Credentials with read access to the requested project and install the required Google Cloud clients; retry after resolving access or API availability. No extra write permissions are required. [Regression tests](../tests/test_gcp_collection_integrity.py) verify rejection of malformed input and preservation of prior raw evidence and posture after a failed sync. These offline tests do not extend live-provider qualification.

These checks establish completion of the configured reads. They do not establish that the selected project scope includes every account, resource type or organization the operator intended to assess.
