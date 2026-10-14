# GRC Lake roadmap

Status as of v0.3.4, checked **2026-10-13**; **v0.3.4 is published**.
Start with [current state and coverage](docs/CURRENT_STATE.md) for shipped paths
and qualification boundaries. This roadmap describes remaining work, not promises
of release dates.

## Next milestone: deepen qualification

Version 0.3.4 adds public repository URL onboarding, directional evidence graphs,
and collection-completeness fixes. It retains the investigation, connector-workflow
and AI-worklist changes, shared assessment services and bounded recovery behavior. Exact-main CI,
release qualification and published-artifact checks passed; see
[release readiness](docs/RELEASE_READINESS.md). Provider depth, independent mapping
review and measured capacity remain separate work below. Correctness, security,
migration and supported-workflow regressions remain release blockers.

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

| Priority / slice                        | Start here                                                                                                                                             | Complete when                                                                                                                                                          | Access / size                                 |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Next: KnowBe4 live cursor qualification | [#737](https://github.com/koda-ai-studio/grc-lake/issues/737), `connectors_knowbe4.py`                                                                 | An authorized account with more than 500 records confirms the next-cursor response contract; retained sanitized receipts show complete collection or explicit failure. | Authorized KnowBe4 tenant; medium             |
| Next: Databricks reader qualification   | [#734](https://github.com/koda-ai-studio/grc-lake/issues/734), `connectors_databricks.py`                                                              | Approved read-only workspace run verifies probe, paging, SQL/schema mapping, normalized identity and failure reporting; reviewer accepts sanitized results.            | Authorized workspace + reviewer; medium       |
| Starter: branded not-found recovery     | [#768](https://github.com/koda-ai-studio/grc-lake/issues/768), `app/web/src/app/`                                                                      | Unknown console routes show a concise recovery action in the built Python-served app, with keyboard and mobile tests.                                                  | Synthetic demo; small                         |
| Next: one reviewed mapping slice        | [#909](https://github.com/koda-ai-studio/grc-lake/issues/909), [Coverage ledger](docs/FRAMEWORK_COVERAGE.md), [mapping review](docs/MAPPING_REVIEW.md) | A named framework subset has source/version references and independent human review; stale reviews cannot count; generated coverage agrees.                            | Qualified domain reviewer; small per subset   |
| Next: reproducible capacity baseline    | [#910](https://github.com/koda-ai-studio/grc-lake/issues/910), `tools/benchmark_assessment_pipeline.py`, `tools/benchmark_distributed.py`              | Publish sanitized workload/configuration and measured latency, memory, disk and queue fairness; report saturation and failures without inferring production capacity.  | Sufficient disk; medium                       |
| Later: provider recovery qualification  | [Backup/restore](docs/runbooks/BACKUP_RESTORE.md), [distributed mode](docs/DISTRIBUTED.md)                                                             | Real PostgreSQL/object-store restore and worker interruption drills preserve tenant isolation and generation identity, with measured recovery bounds.                  | Isolated deployment; large                    |
| Next: deepen live adapter qualification | [Qualification matrix](docs/CONNECTOR_QUALIFICATION.md), [Connectors](docs/CONNECTORS.md), [live-cloud runbook](docs/LIVE_CLOUD_POC.md)                | Each adapter records tested scope, permission-denied behavior, pagination, replay and normalization; preview changes only with reviewed evidence.                      | Authorized vendor tenants; one adapter per PR |

KnowBe4 #737 is due **before November 2026**. Source now uses cursor-only
pagination and fails closed when continuation cannot be established. An authorized
run with more than 500 records must still verify the live next-cursor response
contract before the provider removes page-based pagination.

Code paths without a directory prefix above are in `src/security_lakehouse/`.
Priorities are sequencing guidance; security and correctness regressions take
precedence. No contributor should need production credentials to run fixture tests.

Public repository URL onboarding shipped in 0.3.4 ([#911](https://github.com/koda-ai-studio/grc-lake/issues/911)), reusing the public audit pipeline before authenticated governance enrichment. Historical source identities remain preserved; new collection does not migrate retained legacy observations.

## Coverage still incomplete

ISO 27701:2025 is a limited pack (10 of 78 Annex A controls). SOC 1 is planned
without an official catalog. NIST 800-171 Rev 3, NIS2 and DORA mappings are
proposed-only; NIST RMF and ISO 27701 also need mapping review. CIS Azure/GCP
benchmarks and ISO 27001 clauses 4–10 remain gaps.

1,362 of 1,702 safeguard-to-requirement mapping rows are proposed, so 1,083 of the 1,422 mapped requirements have no reviewed mapping.

Mapping counts are effective review states: a mapping marked reviewed against an
older control version counts as proposed until it is re-reviewed.

Existing-lake mappings remain experimental; provider and schema compatibility
need separate qualification. Distributed mode does not include cross-database
sharding or automatic shard placement. Live commercial billing/SCIM integration,
provider HA and production capacity remain unqualified by this audit.

## Release work

v0.3.4 is published. The earlier 0.3.3 changes include dependency remediation,
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
