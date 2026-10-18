# Current state and coverage

Release verification: **2026-10-17**. Source version: **0.3.9 candidate**. Latest published release checked: **v0.3.8**.
See the [publication receipt](RELEASE_READINESS.md#verified-038-publication) for artifact and runtime evidence.
Changes on `main` or in a pull request can be newer than the published package. Check the [releases](https://github.com/koda-ai-studio/grc-lake/releases)
and [changelog](../CHANGELOG.md) for the version you install.

## What you can use

| Journey                             | Implemented path                                                                      | Boundary                                                                                                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Platform engineer: connect evidence | Read-only connector → probe → enable → sync → evaluate                                | Permissions, provider scope and schema mappings must be qualified in your environment. A successful probe is not a complete collection.                         |
| Control owner: investigate and act  | Finding → control/evidence → owned task → human review                                | Missing evidence and unresolved findings remain visible; a task or exception does not rewrite the control verdict.                                              |
| GRC lead: understand coverage       | Frameworks, mapping review, risks and exceptions                                      | Proposed mappings are not attestable. Catalog breadth is not assessed coverage or certification.                                                                |
| Auditor: reproduce a result         | Frozen generations, exact evidence lineage, workpapers and exports                    | Hash verification establishes linkage/integrity, not source authenticity or sufficient audit evidence.                                                          |
| Agent developer: integrate          | REST, CLI and MCP over the same assessment contracts                                  | Permissions and human-reserved decisions still apply; surfaces have different workflow affordances.                                                             |
| Operator: self-host                 | Filesystem mode or opt-in PostgreSQL/S3 distributed mode; VM, container or Kubernetes | More workers admit different tenants concurrently. One tenant's evaluation still runs on one worker; production capacity/HA requires deployment-specific tests. |

The console evidence drawer provides an on-demand frozen-result trace with visible
verification failures and retry. Connections separates configuration, access testing,
first sync and result review, while keeping optional lake/JSONL setup behind a disclosure.
Frozen CCF requirement-gap explanations are available through the console, API and MCP.
The [investigation graph](INVESTIGATION_GRAPH.md) follows exact recorded bindings and
explicit vendor asset links, with depth controls, expanded workspace, drill-down and
roll-up. Shared presentation does not establish equal provider qualification.

Remaining depth work is described in the [connector qualification matrix](CONNECTOR_QUALIFICATION.md),
the [SOC 2 and ISO review batches](reviews/SOC2_ISO_REVIEW.md),
and [measured capacity #910](https://github.com/koda-ai-studio/grc-lake/issues/910).

The generated [connector qualification matrix](CONNECTOR_QUALIFICATION.md)
links offline test modules, historical bounded live records, declared permissions
and qualification owners for every built-in contract. Its
[GitHub slice](GITHUB_QUALIFICATION.md) documents tested collection failure modes.
Neither linked tests nor a prior source audit qualify the current release.

## Coverage sources

Use these maintained contracts rather than a second hand-maintained feature count.

| Coverage question                                | Source of truth                                                                                              | How to check                                                                                                                                             |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Which connectors execute, and which are preview? | [Connector catalog](CONNECTORS.md), `connectors/catalog.json`                                                | `grc-lake connectors validate`; runner and catalog tests under `tests/`                                                                                  |
| Which requirements have reviewed mappings?       | Generated [framework coverage](FRAMEWORK_COVERAGE.md)                                                        | `make coverage-doc`; review the generated diff and effective mapping versions                                                                            |
| Which lakes and deployment modes work?           | [Deployment compatibility](DEPLOYMENT.md#deployment-and-lake-compatibility), [BYOL](BRING_YOUR_OWN_LAKE.md)  | Qualify reader, schema mapping, application storage and export separately                                                                                |
| What goes in and comes out?                      | [Data model](DATA_MODEL.md), [data flow](DATA_FLOW.md), [API contract](api/AGENT_API.md)                     | Schema validation, replay/identity tests, export round trips and generation verification                                                                 |
| What scales, with which settings?                | [Distributed mode](DISTRIBUTED.md), [audit scale](AUDIT_SCALE.md), [benchmarks](BENCHMARKS.md)               | Record workload, storage, hardware, configuration, concurrency, latency and resource use                                                                 |
| Which user journeys exist?                       | [Console UX](CONSOLE_UX.md), `app/web/e2e/`                                                                  | Synthetic browser tests plus authorized deployment checks; an accessible page alone is not a completed journey                                           |
| How much Python code do tests exercise?          | [CI runs](https://github.com/koda-ai-studio/grc-lake/actions/workflows/ci.yml), `coverage-combined` artifact | The `coverage` job combines all four test shards into line-and-branch coverage for that exact revision; this is separate from framework mapping coverage |

The [0.3.3 main CI run](https://github.com/koda-ai-studio/grc-lake/actions/runs/38210181098)
at source `fee5a7b8` passed 5,355 Python tests, with 86 skipped. Its combined
four-shard report measured 88.29% line coverage, 77.91% branch coverage and
85.89% combined coverage. Separate PostgreSQL and built-image jobs add integration
checks; their execution is not included in that coverage percentage.

## Coverage depth

The refreshed tour uses source `9e741ffb`, including shared assessment services,
durable operation outcomes and bounded retry behavior alongside the existing
console workflows. Coverage documents and the README summary were regenerated
from this catalog; their counts are unchanged. This identifies the application
source used for the screenshots; published-package and container qualification
remain separate checks in [release readiness](RELEASE_READINESS.md).

| Area                | Implemented breadth                                                                                              | Evidence and remaining depth                                                                                                                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Collection          | 28 catalog contracts: 25 executable adapters, including 7 preview; 3 configuration/access boundaries             | Shared console setup retains each provider's fields and permissions. Fixture behavior and access tests do not establish complete live collection; see the [qualification matrix](CONNECTOR_QUALIFICATION.md). |
| Frameworks          | 20 populated packs; generated counts and effective review states in the [coverage matrix](FRAMEWORK_COVERAGE.md) | Source-cited, mapped, human-reviewed and freshly evaluated requirements are separate measures; review the pending [SOC 2 and ISO batches](reviews/SOC2_ISO_REVIEW.md).                                        |
| Investigation       | Exact records, source accounts, controls, CCF, repositories and explicit vendor asset links                      | Generation-bound reads and bounded navigation have contract tests. Server construction still scales with evidence volume; [#910](https://github.com/koda-ai-studio/grc-lake/issues/910) tracks measurement.   |
| AI governance       | Model/agent worklist with owner, environment, signals, next actions and asset-filtered evidence                  | Recorded lineage is not automatically complete; observed controls are not fresh evaluations. No model safety or certification conclusion follows.                                                             |
| Repository evidence | Public GitHub URL onboarding and audit CLI; authenticated GitHub/GitLab adapters                                 | Public collection is commit-pinned and bounded. Private governance remains unknown until authenticated collection; retained legacy source identities are not migrated.                                        |
| Human decisions     | Pending access reviews, mapping review and scoped sharing                                                        | Independent human authority remains enforced. A recorded access-revocation decision does not revoke provider access.                                                                                          |

Earlier console qualification at source `6a9464a0` passed the build,
catalog/schema validation and 175 focused graph, tenant/auth,
access-review, lineage and release-contract tests locally. Sixteen
PostgreSQL variants were skipped in that local run; PostgreSQL CI and the
release image probes are separate qualification. The synthetic browser tour
includes desktop light/dark and mobile views. After the identity fixes, 36 focused
browser tests passed, including shared artwork, mobile layout, provider setup,
graph interactions and review restrictions. None of this refresh repeats the
live-provider collections below.

## Assessment and recovery

Evaluation and snapshot transports now share application services. Authorized
callers can inspect tenant-scoped operation receipts after a lost completion
response; oversized responses preserve execution status. Queue admission,
cursor pagination, response retention, collector retries and recovery inspection
have explicit budgets and errors. Failed integrity checks still consume the
inspection download allowance. See the
[assessment application contract](ASSESSMENT_APPLICATION_CONTRACT.md).

The built-image CI drill restores coordinated PostgreSQL and S3 backups after
removing its original disposable storage. It checks retained revisions, evidence
hashes, snapshot chains, operation receipts, corrupt-backup rejection and tenant
isolation. The PostgreSQL CI job also exercises receipt retrieval across replicas
after deliberately omitting job completion. Local receipt persistence still
follows publication, so a crash in that gap remains uncertain. No automatic
replay, production RPO/RTO, provider failover or capacity guarantee follows from
these tests; inspect the exact candidate's CI reports before rollout.

## Earlier bounded provider qualification

The 2026-10-11 audit used source based on `ccd9d9c3` (after #900), plus the
console fixes described above. This is a dated check, not an evergreen support
promise or qualification of a future release artifact.

- **Offline contracts:** 792 tests passed across 52 connector, sink and export
  modules, covering adapter behavior, credential boundaries, replay and output
  contracts. Fixtures establish tested behavior, not vendor-wide compatibility.
- **Live read-only collection:** AWS IAM/posture (12 records), Azure subscription
  posture (26), and GCP project IAM/assets (181). Raw validation, normalization,
  evaluation, generation integrity and MCP lineage checks passed in those scopes.
  Control failures remained failures. No full-estate or compliance conclusion is implied.
- **Portable output:** all normalized fields from those three bounded collections
  round-tripped through Parquet and an independent DuckDB reader.
- **Distributed contracts:** local PostgreSQL exercised tenant admission, leases,
  jobs and HTTP contracts. Tests using object-store doubles do not qualify a live
  S3 provider or multi-node failover. The optional Moto end-to-end module was skipped.
- **Deployment templates:** Helm lint/render and Terraform formatting passed;
  cloud deployment and provider HA were not exercised in this audit.

GCP returned no organization-policy rows; inherited/effective organization-policy
coverage is not established. KnowBe4 and Databricks live checks still require
approved access and a designated reviewer. Other connector fixture tests do not
substitute for live vendor qualification. A new performance run stopped at the
5 GiB free-disk safety floor, so this audit adds no capacity claim.

Raw provider receipts, identities and resource data stay private. Public tests
and screenshots use synthetic examples. Release CI, scans, provenance, container
architectures and authenticated deployment checks remain separate gates in
[release readiness](RELEASE_READINESS.md).

## Take on work

Pick a scoped item in the [roadmap](../ROADMAP.md), check its linked issue and
open PRs, then follow [Contributing](../CONTRIBUTING.md). Update this page when
a capability or qualification boundary changes; regenerate coverage from its
owning command. Keep unresolved work visible until its acceptance criteria pass.
