# Evidence lineage

`GET /api/v1/evidence/{event_id}/lineage` traces an exact normalized event to
its retained source record and frozen result references. The read-only MCP tool
`get_evidence_lineage` returns the same response envelope.

Use the normalized `event_id` returned by `/api/v1/evidence`, URL-encoded as one
path value. A connector event's ID is namespaced by connector; its original
provider ID is returned separately as `source.source_event_id`. The source
account is not the platform tenant. In server mode, authentication selects the
tenant's lake; this endpoint has no tenant or filesystem selector.

The response contains the event ID, source connector/account/time, asset ID,
normalized status and raw SHA-256. It omits the raw payload, evidence URI and local
paths. `integrity.verified` means the sealed generation's hashes and the exact
bronze-to-silver link matched. It does **not** establish external authenticity,
source correctness, evidence sufficiency or an audit opinion.

Result links distinguish two relationships:

- `declared_control`: the event declares a control association. The stored
  control-test result is included for context; this link does not assert that
  the individual event satisfied operating-evidence rules.
- `safeguard_result`: the same event ID and raw digest occur in the stored CCF
  result for that source account and asset. The result remains the aggregate
  outcome, including other evidence and blockers.

`limit` defaults to 25 and accepts 1–100; `offset` defaults to zero. `meta.count`
counts result links, and `meta.returned` counts this page. Every response includes
its generation ID and manifest digest. Send `generation_id` from the first page
on later requests to receive HTTP 409 if the current generation changed. The
parameter is a consistency precondition, not a historical-generation selector.

Unknown exact event IDs return 404. Missing/unsealed generations, ambiguous source
links and failed integrity checks return 409 without returning raw driver errors.
Re-evaluate an older lake to publish a sealed generation before using this API.

This is an audit drill-down, not a constant-time lookup: each request hashes the
assessment artifacts and streams normalized and raw evidence. Response memory is
bounded by one stored record and one result page; large lakes still incur read
I/O. It uses the same generation read lease as other assessment queries, so a
concurrent publication cannot mix old evidence with new results.
