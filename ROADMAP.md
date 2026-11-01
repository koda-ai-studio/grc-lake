# GRC Lake roadmap

Status as of v0.3.23, checked **2026-11-01**; **v0.3.23 is published**.
This patch tightens qualification receipts, supports second-review packet
preparation and records bounded synthetic graph measurements. Deeper provider,
safeguard-contract and capacity qualification remain below.
Start with [current state and coverage](docs/CURRENT_STATE.md) for shipped paths
and qualification boundaries. This roadmap describes remaining work, not promises
of release dates.

## Stability period after 0.3.22

Release gates and the publication receipt are recorded in
[release readiness](docs/RELEASE_READINESS.md#verified-0322-publication). After
publication, follow the [14-day stability and pilot process](docs/PILOT.md): prioritize reported
correctness, security, supported-workload performance and setup problems. New
connectors and unrelated feature expansion wait. No pilot adoption or mapping
approval is implied by preparing this process.

## Next milestone: deepen qualification

Releases 0.3.13 through 0.3.22 separated control-test posture from framework
results, bounded graph layouts and reads, scoped evidence by provider and source
account, and hardened transport and review-state validation. Published-artifact
verification now covers v0.3.23 in [release readiness](docs/RELEASE_READINESS.md).
Provider depth, independent mapping review and measured capacity remain separate
work below. Correctness, security, migration and supported-workflow regressions
remain release blockers.

Use operator and contributor reports to set priorities: installation,
first connection and sync, finding investigation, access review, and audit export.
Useful reports include the installed version, deployment mode, sanitized reproduction,
expected versus actual behavior, and relevant counts. Do not include credentials or
customer evidence. Qualification depth and measured capacity come before unsupported
parity or scale claims.

## Choose a contribution

Check [open issues](https://github.com/koda-ai-studio/grc-lake/issues) and
[open pull requests](https://github.com/koda-ai-studio/grc-lake/pulls) before starting.
For a linked issue, comment with the slice you plan to tackle. For an untracked
slice, open an issue with scope and acceptance criteria before substantial work.
Maintainers confirm scope and review; an untracked row is not an assigned task.
See [Contributing](CONTRIBUTING.md) for setup and checks. Never post credentials
or real provider evidence in issues or pull requests.

| Priority / slice                        | Start here                                                                                                                                        | Complete when                                                                                                                                                         | Access / size                                 |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Next: Databricks reader qualification   | [#734](https://github.com/koda-ai-studio/grc-lake/issues/734), `connectors_databricks.py`                                                         | Approved read-only workspace run verifies probe, paging, SQL/schema mapping, normalized identity and failure reporting; reviewer accepts sanitized results.           | Authorized workspace + reviewer; medium       |
| Next: SOC 2 and ISO mapping review      | [SOC 2 and ISO batches](docs/reviews/SOC2_ISO_REVIEW.md), [Coverage ledger](docs/FRAMEWORK_COVERAGE.md), [mapping review](docs/MAPPING_REVIEW.md) | A named framework subset has source/version references and independent human review; stale reviews cannot count; generated coverage agrees.                           | Qualified domain reviewer; small per subset   |
| Next: reproducible capacity baseline    | [#910](https://github.com/koda-ai-studio/grc-lake/issues/910), `tools/benchmark_assessment_pipeline.py`, `tools/benchmark_distributed.py`         | Publish sanitized workload/configuration and measured latency, memory, disk and queue fairness; report saturation and failures without inferring production capacity. | Sufficient disk; medium                       |
| Later: provider recovery qualification  | [Backup/restore](docs/runbooks/BACKUP_RESTORE.md), [distributed mode](docs/DISTRIBUTED.md)                                                        | Real PostgreSQL/object-store restore and worker interruption drills preserve tenant isolation and generation identity, with measured recovery bounds.                 | Isolated deployment; large                    |
| Next: deepen live adapter qualification | [Qualification matrix](docs/CONNECTOR_QUALIFICATION.md), [Connectors](docs/CONNECTORS.md), [live-cloud runbook](docs/LIVE_CLOUD_POC.md)           | Each adapter records tested scope, permission-denied behavior, pagination, replay and normalization; preview changes only with reviewed evidence.                     | Authorized vendor tenants; one adapter per PR |

The branded not-found work in [#768](https://github.com/koda-ai-studio/grc-lake/issues/768)
and the earlier mapping slice in [#909](https://github.com/koda-ai-studio/grc-lake/issues/909)
are closed. The pending SOC 2 and ISO batches are a separate review scope.

Code paths without a directory prefix above are in `src/security_lakehouse/`.
Priorities are sequencing guidance; security and correctness regressions take
precedence. No contributor should need production credentials to run fixture tests.

Public repository URL onboarding shipped in 0.3.4 ([#911](https://github.com/koda-ai-studio/grc-lake/issues/911)), reusing the public audit pipeline before authenticated governance enrichment. Historical source identities remain preserved; new collection does not migrate retained legacy observations.

## Coverage still incomplete

The current catalog has 96.2% mapped requirements and
38.8% with reviewed mappings. The [NIST assessment expansion](docs/NIST53_ASSESSMENTS.md),
[maintainer approval of 33 source-review batches](controls/reviews/2026-10-14-source-batches.json)
and the [SOC 2 and ISO 27001 batch decision](controls/reviews/2026-10-25-soc2-iso27001-batch.json)
provide the mapping and review increases. The 38.8% is a blended aggregate: 381 of
those reviewed requirements are source-native NIST 800-53 self-maps, not
crosswalk judgements. Read reviewed coverage per framework, split into self-maps
and crosswalk reviews, in the [coverage matrix](docs/FRAMEWORK_COVERAGE.md).
Release qualification passed; it does
not approve additional mappings. A merged proposal or passing CI does not
approve a mapping.

SOC 2 has 49 of 61 reviewed requirements after demotion of unattributed legacy
mappings. Prioritize bounded review of the reopened legacy mappings and the
remaining ISO 42001 and ISO 27001 candidates. Title-theme suggestions need
requirement-specific contracts before a maintainer decision. Prepare clause-specific source evidence,
safeguard rationale, evidence requirements and limitations before requesting new
human decisions. Report progress per framework; the aggregate milestone does not
establish balanced review depth. Earlier approvals do not extend to remaining
proposals.

ISO 27701:2025 is a limited pack (10 of 78 Annex A controls). SOC 1 is planned
without an official catalog. NIST 800-171 Rev 3, NIS2, DORA and NIST RMF now have
reviewed mappings; gaps remain as shown in the [coverage matrix](docs/FRAMEWORK_COVERAGE.md).
ISO 27701 still needs mapping review. CIS Azure/GCP benchmarks remain gaps.
ISO 27001 management-clause mappings still need review. The [ISMS companion pack](docs/ISO27001_ISMS_ASSESSMENTS.md)
now catalogues 30 clause identifiers with proposed assessor contracts; it grants no new review credit.

1,790 of 2,760 safeguard-to-requirement mapping rows are proposed, so 1,312 of the 2,198 mapped requirements have no reviewed mapping.

Mapping counts are effective review states: a mapping marked reviewed against an
older control version counts as proposed until it is re-reviewed.

Existing-lake mappings remain experimental; provider and schema compatibility
need separate qualification. Distributed mode does not include cross-database
sharding or automatic shard placement. Live commercial billing/SCIM integration,
provider HA and production capacity remain unqualified by this audit.

## Release work

v0.3.23 is published. The earlier 0.3.3 changes include dependency remediation,
authentication hardening, evidence eligibility, versioned CCF governance, exact
lineage and frozen requirement-gap explanations. The console now exposes those
gaps and record-level investigation, with bounded graph navigation and shared
connector setup. These are implemented source paths, not live-provider parity. See the [changelog](CHANGELOG.md)
for merged changes and [open PRs](https://github.com/koda-ai-studio/grc-lake/pulls)
for work still in review.

For each subsequent release, finish final-main CI and the audit, then verify the package,
provenance, both container architectures, scans and authenticated behavior.
[Dependency findings](docs/DEPENDENCY_SECURITY.md) and
[Scorecard evidence](docs/SCORECARD_REMEDIATION.md) have their own resolution
criteria. Green CI does not by itself close them. Follow the
[release gates](docs/RELEASE_READINESS.md).

The 0.3.3 refresh includes the README, guides, 39 generated screenshots and measured
test coverage. Repeat this verification for future releases. Reconcile feature
coverage by implemented breadth, tested depth, live qualification, independent
mapping review and remaining limitations; link the existing qualification backlog
instead of treating catalog presence as parity.
