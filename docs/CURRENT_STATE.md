# Current state and coverage

Release verification: **2026-10-31**. Latest published release checked: **v0.3.21**.
See the [publication receipt](RELEASE_READINESS.md#verified-0321-publication) for artifact and runtime evidence.
Changes on `main` or in a pull request can be newer than the published package. Check the [releases](https://github.com/koda-ai-studio/grc-lake/releases)
and [changelog](../CHANGELOG.md) for the version you install.

0.3.21 isolates connector state by source account, adds named account
connections and organization account selections, withholds passes from truncated
mapped lake reads, and separates the investigation graph's assurance lanes from
recorded lineage. See the [0.3.21 notes](RELEASE_READINESS.md#0321-release).

0.3.17 makes missing review status and unattributed legacy mappings proposed,
preserves explicit graph review provenance, and bounds graph layouts by both
nodes and relationships. See the [0.3.17 notes](RELEASE_READINESS.md#0317-release).

The provider-scoping fix from 0.3.16 is retained: benchmarks use only their own
provider's evidence (CIS AWS from AWS sources), so GCP or identity-provider evidence can no longer pass
or fail a CIS AWS requirement, and keeps a denied read from hiding a failing AWS
or GCP verdict. It builds on 0.3.15 (distrusted emSign roots removed, GCP
effective policy, Azure Defender verdicts) and 0.3.14, which reports a framework
result only for a CCF pass through reviewed mappings. See the
[0.3.16 notes](RELEASE_READINESS.md#0316-candidate) and
[publication receipt](RELEASE_READINESS.md#verified-0316-publication). The [pilot guide](PILOT.md) provides an
optional real-workflow evaluation and repeat-use check without telemetry.

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
links offline test modules, bounded live records, declared permissions
and qualification owners for every built-in contract. Its
[GitHub slice](GITHUB_QUALIFICATION.md) documents tested collection failure modes.

The [2026-10-24 live receipts](qualification/live/2026-10-24.md) cover
`aws-posture`, `azure-posture`, `gcp-posture` and `github-security` at source
`f4532d21`. Each ran read-only against one maintainer test account, subscription,
project or public repository: 12 AWS IAM records (29 with role policies and
inventory), 26 Azure, 183 GCP (187 with service accounts) and 6 GitHub
governance signals. Counts were reconciled with each provider's CLI, and
recollection and generation integrity checks passed. The GitHub run found and
fixed a Dependabot pagination failure. These receipts do not qualify a published
release artifact, other tenants or provider-wide coverage. The
[Databricks trial receipt](qualification/live/2026-10-25-databricks.md#databricks-multichunk)
adds populated audit-log collection and two 77,036-record syncs across three
result chunks, including 75,000 synthetic rows. Counts and open audit events
were reconciled with the provider, and recollection preserved unique event IDs.
Databricks remains Preview; live throttling and credential expiry remain untested.
The index currently links receipts for AWS, Azure, GCP, GitHub and Databricks;
an absent link does not establish that a connector has never been tried.

## Coverage sources

Use these maintained contracts rather than a second hand-maintained feature count.

| Coverage question                                | Source of truth                                                                                              | How to check                                                                                                                                            |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Which connectors execute, and which are preview? | [Connector catalog](CONNECTORS.md), `connectors/catalog.json`                                                | `grc-lake connectors validate`; runner and catalog tests under `tests/`                                                                                 |
| Which requirements have reviewed mappings?       | Generated [framework coverage](FRAMEWORK_COVERAGE.md)                                                        | `make coverage-doc`; review the generated diff and effective mapping versions                                                                           |
| Which lakes and deployment modes work?           | [Deployment compatibility](DEPLOYMENT.md#deployment-and-lake-compatibility), [BYOL](BRING_YOUR_OWN_LAKE.md)  | Qualify reader, schema mapping, application storage and export separately                                                                               |
| What goes in and comes out?                      | [Data model](DATA_MODEL.md), [data flow](DATA_FLOW.md), [API contract](api/AGENT_API.md)                     | Schema validation, replay/identity tests, export round trips and generation verification                                                                |
| What scales, with which settings?                | [Distributed mode](DISTRIBUTED.md), [audit scale](AUDIT_SCALE.md), [benchmarks](BENCHMARKS.md)               | Record workload, storage, hardware, configuration, concurrency, latency and resource use                                                                |
| Which user journeys exist?                       | [Console UX](CONSOLE_UX.md), `app/web/e2e/`                                                                  | Synthetic browser tests plus authorized deployment checks; an accessible page alone is not a completed journey                                          |
| How much Python code do tests exercise?          | [CI runs](https://github.com/koda-ai-studio/grc-lake/actions/workflows/ci.yml), `coverage-combined` artifact | The `coverage` job combines all six test shards into line-and-branch coverage for that exact revision; this is separate from framework mapping coverage |

Use the latest successful run for the exact revision being evaluated. Its
`pytest-*` artifacts record test results and timings; `coverage-combined` records
Python line and branch coverage. PostgreSQL, browser, and built-image checks are
separate qualification. Historical test totals are not a current coverage claim.

## Coverage depth

The product-tour screenshots were recaptured from the 0.3.17 release: frozen
runtime source `bdfa9135` with the release version alignment. The capture uses a
fresh synthetic golden lake and the same browser clock for light/dark pairs.
The graph light/dark pair was then refreshed for the bounded-layout and review-provenance improvements described in [Evidence investigation](INVESTIGATION_GRAPH.md).
Mapping-review, framework and mobile images retain the full-tour capture;
README and coverage counts come from the same catalog. Publication and live
provider qualification remain separate checks in [release readiness](RELEASE_READINESS.md).

| Area                | Implemented breadth                                                                                                                                          | Evidence and remaining depth                                                                                                                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Collection          | 31 catalog contracts: 28 executable adapters, including 10 preview; 3 configuration/access boundaries                                                        | Shared console setup retains each provider's fields and permissions. Fixture behavior and access tests do not establish complete live collection; see the [qualification matrix](CONNECTOR_QUALIFICATION.md). |
| Frameworks          | 21 populated packs, including a separate ISO ISMS clause scope; generated counts and effective review states in the [coverage matrix](FRAMEWORK_COVERAGE.md) | Source-cited, mapped, human-reviewed and freshly evaluated requirements are separate measures; review the pending [SOC 2 and ISO batches](reviews/SOC2_ISO_REVIEW.md).                                        |
| Investigation       | Exact records, source accounts, controls, CCF, repositories and explicit vendor asset links                                                                  | Generation-bound reads and bounded navigation have contract tests. Server construction still scales with evidence volume; [#910](https://github.com/koda-ai-studio/grc-lake/issues/910) tracks measurement.   |
| AI governance       | Model/agent worklist with owner, environment, signals, next actions and asset-filtered evidence                                                              | Recorded lineage is not automatically complete; observed controls are not fresh evaluations. No model safety or certification conclusion follows.                                                             |
| Repository evidence | Public GitHub URL onboarding and audit CLI; authenticated GitHub/GitLab adapters                                                                             | Public collection is commit-pinned and bounded. Private governance remains unknown until authenticated collection; retained legacy source identities are not migrated.                                        |
| Human decisions     | Pending access reviews, mapping review and scoped sharing                                                                                                    | Independent human authority remains enforced. A recorded access-revocation decision does not revoke provider access.                                                                                          |

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
promise or qualification of a future release artifact. The
[2026-10-24 receipts](qualification/live/2026-10-24.md) replace its live
collection entries in the qualification matrix.

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
coverage is not established. Databricks live checks still require
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
