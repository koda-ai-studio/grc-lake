-- ClickHouse schema for high-volume security telemetry analytics.
-- The tables mirror the local gold/silver artifacts and are optimized for
-- time-window investigations, dashboard aggregates, and runtime event analytics.
--
-- Point-in-time posture history: the assessment snapshots written to
-- gold/snapshots/assessment-<ts>.json (each immutable, with an evaluated_at and
-- assessment_hash) are the authoritative "posture as of date X" record and are
-- queryable via assessment.posture_as_of / GET /api/v1/posture/as-of?as_of=.
-- The MergeTree tables below carry loaded_at/event_time, but a dedicated
-- valid_from/valid_to temporal model for these analytics tables is a follow-up;
-- the snapshot history is the current source of truth for as-of queries.

create database if not exists security;

create table if not exists security.normalized_events
(
  event_id String,
  tenant_id LowCardinality(String),
  event_time DateTime64(3, 'UTC'),
  source LowCardinality(String),
  event_type LowCardinality(String),
  asset_id String,
  asset_type LowCardinality(String),
  asset_owner LowCardinality(String),
  environment LowCardinality(String),
  severity LowCardinality(String),
  severity_score UInt8,
  status LowCardinality(String),
  control_ids Array(String),
  evidence_id String,
  evidence_ref String,
  evidence_collected_at DateTime64(3, 'UTC'),
  raw_sha256 FixedString(64)
)
engine = MergeTree
partition by toYYYYMM(event_time)
order by (tenant_id, event_time, source, event_type, asset_id)
-- TTL expressions require Date/DateTime; event_time is DateTime64, so cast it.
ttl toDateTime(event_time) + interval 730 day;

create table if not exists security.control_posture
(
  tenant_id LowCardinality(String),
  control_id String,
  framework LowCardinality(String),
  title String,
  risk_domain LowCardinality(String),
  owner LowCardinality(String),
  status LowCardinality(String),
  risk_score UInt8,
  event_count UInt64,
  open_event_count UInt64,
  evidence_count UInt64,
  evidence_coverage Float32,
  latest_event_time DateTime64(3, 'UTC'),
  loaded_at DateTime64(3, 'UTC') default now64(3)
)
engine = ReplacingMergeTree(loaded_at)
partition by tenant_id
order by (tenant_id, framework, control_id);

create table if not exists security.control_tests
(
  tenant_id LowCardinality(String),
  test_id String,
  program_id LowCardinality(String),
  control_id String,
  framework LowCardinality(String),
  name String,
  owner LowCardinality(String),
  cadence LowCardinality(String),
  automation_level LowCardinality(String),
  agent_skill LowCardinality(String),
  status LowCardinality(String),
  result LowCardinality(String),
  confidence_score UInt8,
  confidence_inputs_json String,
  required_evidence_types Array(String),
  observed_evidence_types Array(String),
  missing_evidence_types Array(String),
  evidence_count UInt64,
  failing_evidence_count UInt64,
  open_violation_count UInt64,
  latest_evidence_at Nullable(DateTime64(3, 'UTC')),
  freshness_status LowCardinality(String),
  remediation_sla_hours UInt16,
  next_action String,
  api_refs_json String,
  evaluated_at DateTime64(3, 'UTC'),
  loaded_at DateTime64(3, 'UTC') default now64(3)
)
engine = ReplacingMergeTree(loaded_at)
partition by tenant_id
order by (tenant_id, program_id, framework, result, control_id);

create table if not exists security.asset_risk
(
  tenant_id LowCardinality(String),
  source_account_id String,
  asset_id String,
  asset_type LowCardinality(String),
  asset_owner LowCardinality(String),
  environment LowCardinality(String),
  risk_score UInt8,
  critical_open UInt64,
  high_open UInt64,
  event_count UInt64,
  latest_event_time DateTime64(3, 'UTC'),
  loaded_at DateTime64(3, 'UTC') default now64(3)
)
engine = ReplacingMergeTree(loaded_at)
partition by tenant_id
order by (tenant_id, source_account_id, asset_id);

create view if not exists security.control_test_readiness as
select
  framework,
  count() as tests,
  countIf(result = 'pass') as passing_tests,
  countIf(result = 'fail') as failing_tests,
  round(avg(confidence_score), 2) as avg_confidence_score
from security.control_tests
group by framework
order by failing_tests desc, avg_confidence_score asc;

create view if not exists security.runtime_policy_metrics as
select
  tenant_id,
  toStartOfHour(event_time) as hour,
  count() as runtime_events,
  countIf(status in ('blocked', 'failed')) as blocked_events,
  round(blocked_events / runtime_events, 4) as block_rate
from security.normalized_events
where startsWith(event_type, 'runtime.')
group by tenant_id, hour
order by hour desc;
