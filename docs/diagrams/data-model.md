# Data Model — analytics lake (local mode)

This models the file-backed Bronze/Silver/Gold analytics lake and its SQLite
mart (see [`architecture.md`](architecture.md)). Server mode adds an
application-state database: tenants, users, API keys, sessions, remediation
tasks, evidence requests, exceptions, tags, saved views, and posture metric
points — documented in [`../DATA_MODEL.md`](../DATA_MODEL.md) and
[`../SERVER_AUTH.md`](../SERVER_AUTH.md).

```mermaid
erDiagram
  NORMALIZED_EVENTS {
    string event_id PK
    string tenant_id
    datetime event_time
    string source
    string event_type
    string asset_id
    string asset_type
    string asset_owner
    string environment
    string severity
    int severity_score
    string status
    string control_ids_json
    string evidence_id
    string evidence_ref
    string raw_sha256
  }

  CONTROL_POSTURE {
    string control_id PK
    string framework
    string title
    string risk_domain
    string owner
    string status
    int risk_score
    int event_count
    int open_event_count
    int evidence_count
    float evidence_coverage
    datetime latest_event_time
  }

  ASSET_RISK {
    string source_account_id PK
    string asset_id PK
    string asset_type
    string asset_owner
    string environment
    int risk_score
    int critical_open
    int high_open
    int event_count
    datetime latest_event_time
  }

  METRICS {
    string metric PK
    string value
  }

  NORMALIZED_EVENTS }o--o{ CONTROL_POSTURE : maps_to_controls
  NORMALIZED_EVENTS }o--|| ASSET_RISK : rolls_up_to_asset
```

## Canonical Event Fields

| Field          | Purpose                                                 |
| -------------- | ------------------------------------------------------- |
| `event_id`     | Source-stable event identifier                          |
| `tenant_id`    | Legacy source-account identity; not platform ownership  |
| `source`       | Tool or system that produced the evidence               |
| `event_type`   | Normalized event family such as `vulnerability.finding` |
| `asset_id`     | Source identifier; joins also require source_account_id |
| `control_ids`  | Framework controls affected by this event               |
| `evidence_ref` | Pointer to the retained artifact                        |
| `raw_sha256`   | Replay and tamper-evidence link to bronze data          |
