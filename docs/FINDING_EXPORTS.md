# Finding exports

GRC Lake's findings are its open violations: one row per evaluated control
result that is `open`, `fail` or otherwise blocking, each with a stable
`violation_id` (`<control_id>:<event_id>`). The findings export turns the
current set into flat, portable CSV or JSONL for a SIEM, a ticketing system or
a spreadsheet, so a finding can be opened downstream from the export and closed
again from the matching `finding.resolved` webhook event
([webhooks](WEBHOOKS.md)).

The same projection serves every surface, so the columns never drift:

| Surface | How                                                                                  |
| ------- | ------------------------------------------------------------------------------------ |
| API     | `GET /api/v1/findings/export?format=csv\|jsonl&limit=N` (`read` scope)               |
| Console | **Export CSV** / **Export JSONL** on the Findings page (hidden in the recorded demo) |
| CLI     | `grc-lake assessment violations --lake DIR --format csv\|jsonl [--out PATH]`         |
| MCP     | `export_findings(format, limit)` (read-only; proxies the API in remote mode)         |
| SDK     | `GrcLakeClient.export_findings(format=..., limit=...)` and the async twin            |

Evidence, OSCAL and Parquet exports remain separate: this export carries
finding **references**, not evidence payloads ([OSCAL export](OSCAL_EXPORT.md),
[Parquet export](PARQUET_EXPORT.md)).

## Contract: `grc-lake.findings.v1`

Every row (CSV record or JSONL object) carries these columns, in this order.
The contract version is the first column so a consumer can reject a file it
does not understand before reading the rest.

| Column                  | Meaning                                                                                                           |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `export_schema_version` | Always `grc-lake.findings.v1`.                                                                                    |
| `finding_id`            | The stable `violation_id` (`<control_id>:<event_id>`); the same value `finding.created`/`finding.resolved` carry. |
| `tenant_id`             | The tenant the export was produced for (the authenticated tenant in server mode; `local` for a local lake).       |
| `source_account_id`     | The source account the evidence was collected from, when the connector recorded one; otherwise empty.             |
| `control_id`            | The evaluated control.                                                                                            |
| `framework_ids`         | Frameworks the control belongs to, from `gold/control_posture.jsonl` (a JSON array in JSONL, `;`-joined in CSV).  |
| `asset_id`              | The asset the finding is bound to.                                                                                |
| `severity`              | `critical`, `high`, `medium` or `low`.                                                                            |
| `state`                 | The finding state at export time (`open`).                                                                        |
| `detected_at`           | When the evidence that produced the finding was observed (`event_time`).                                          |
| `evaluated_at`          | When the posture the export was taken from was evaluated.                                                         |
| `snapshot_id`           | Empty for the current posture; reserved for exports pinned to a recorded snapshot.                                |
| `assessment_hash`       | The content hash of the posture the rows were taken from.                                                         |
| `source`                | The connector or source system that produced the evidence.                                                        |
| `event_type`            | The normalized evidence event type.                                                                               |
| `evidence_ref`          | A reference to the evidence record. Never the evidence body or its hash.                                          |

Rows are ordered highest severity first, then by `control_id` and `event_id`,
so a bounded export keeps the most important findings.

## Formats

**JSONL** (`application/x-ndjson`): one JSON object per line, keys in column
order, `null` for an absent value, trailing newline on every line. Parse line
by line; the file is never one JSON document.

**CSV** (`text/csv; charset=utf-8`): RFC 4180 — a header row, `CRLF` record
separators, fields quoted only when they contain a comma, quote or line break.
Absent values are empty cells.

### CSV safety

Spreadsheet applications evaluate a cell that starts with `=`, `+`, `-`, `@`, a
tab or a carriage return as a formula. Evidence is untrusted data (an asset id
or evidence reference can be chosen by whoever controls the source), so any
cell starting with one of those characters is prefixed with a single
apostrophe (`'`) in the CSV output. Readers that compare values should strip
that leading apostrophe; the JSONL output is unmodified.

## Limits

Exports are bounded. `limit` defaults to **1,000** rows and accepts at most
**10,000**; a request outside `1..10000` or an unknown `format` is rejected
with `400 bad_request`. Rows are rendered lazily and the posture read holds
only the `limit` highest-severity findings, so the bound also bounds memory.

The bound is never silent. The API answers with:

| Header                    | Meaning                                                            |
| ------------------------- | ------------------------------------------------------------------ |
| `Content-Disposition`     | `attachment; filename="grc-lake-findings-<evaluated_at>.<format>"` |
| `X-Export-Schema-Version` | `grc-lake.findings.v1`                                             |
| `X-Export-Limit`          | The row bound applied                                              |
| `X-Export-Total-Count`    | Open findings in the lake at export time                           |
| `X-Export-Truncated`      | `true` when `total_count > limit`                                  |

The console shows a notice when an export was capped; the CLI prints one to
stderr. Both read from the same facts the headers carry.

## Try it

```bash
# API (server mode, bearer token with the read scope)
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8787/api/v1/findings/export?format=csv&limit=500" -o findings.csv

# CLI (any lake directory); json stays the default, unbounded listing
grc-lake assessment violations --lake build/lake --format jsonl --out findings.jsonl
grc-lake assessment violations --lake build/lake --format csv --limit 2000 --out findings.csv
```

## SDK operator guide

The Python SDK (`security_lakehouse.sdk`) wraps the same endpoint.

**Authentication.** Mint a bearer token with the `read` scope at
`POST /api/v1/auth/keys` ([server auth](SERVER_AUTH.md)) and pass it as
`api_key=`. The client sends it as `Authorization: Bearer ...`; a server
started with `--allow-insecure-no-auth` accepts no key. Use the client as a
context manager so the connection pool closes.

**Pagination.** The export is bounded by `limit`, not paged: ask for the bound
you need (up to 10,000) and check the server's truncation facts. The paged
alternative is `list_violations(limit=..., offset=...)`, which reads the same
findings as JSON pages through `/api/v1/violations`.

**Errors.** A non-2xx response raises `GrcLakeError` with `status_code` and
the structured `errors` list (`[{"code": "bad_request", "detail": ...}]`);
`401` means a missing or revoked token, `400` an invalid `format` or `limit`.

**End-to-end example** (synthetic lake, local server). The export opens a
ticket per finding; the `finding.resolved` webhook closes it:

```python
import json

from security_lakehouse.sdk import GrcLakeClient

tickets: dict[str, str] = {}  # finding_id -> ticket id in your tracker

with GrcLakeClient("http://127.0.0.1:8787", api_key="tops_example_token") as client:
    for line in client.export_findings(format="jsonl", limit=5000).splitlines():
        row = json.loads(line)
        assert row["export_schema_version"] == "grc-lake.findings.v1"
        tickets[row["finding_id"]] = open_ticket(  # your tracker's API
            title=f"{row['control_id']} on {row['asset_id']}",
            severity=row["severity"],
            evidence=row["evidence_ref"],
        )
    # Take a snapshot now and again after remediation; the diff between the two
    # snapshots is what produces finding.resolved (docs/WEBHOOKS.md).
    client.create_snapshot(reason="ticket_sync")


def on_webhook(envelope: dict) -> None:
    """Your receiver, after verifying the X-GRC-Lake-* signatures."""
    if envelope["event"] == "finding.resolved":
        ticket = tickets.pop(envelope["data"]["finding_id"], None)
        if ticket:
            close_ticket(ticket, resolved_at=envelope["data"]["resolved_at"])
```

A finding whose source reported a collection gap in the later snapshot never
produces `finding.resolved`, so its ticket stays open until a complete read
confirms the absence.

## Not provided: OCSF

This export does not emit OCSF (Open Cybersecurity Schema Framework) records,
and the `grc-lake.findings.v1` contract should not be read as OCSF-compatible.
OCSF presets exist only on the ingest side ([bring your own lake](BRING_YOUR_OWN_LAKE.md)).
An OCSF _output_ mapping (class selection, required attributes, severity and
status normalization) is a separate decision to be tracked in its own issue
(the acceptance criteria of #1183 call for exactly that), not an implicit
property of this export.
