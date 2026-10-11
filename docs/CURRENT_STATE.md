# Current state and coverage

Source review: **2026-10-11**. Latest published release checked: **v0.3.2**.
The source is preparing v0.3.3; features on `main` or in a pull request are not
therefore available in the published package. Check the [releases](https://github.com/koda-ai-studio/grc-lake/releases)
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

The console evidence drawer in this change adds an on-demand frozen-result trace,
visible verification failures and retry. Connections keeps optional lake/JSONL
setup behind a disclosure so source selection remains the main action. Frozen CCF requirement-gap explanations
are available through the API/MCP; a dedicated console journey remains roadmap work.

## Coverage sources

Use these maintained contracts rather than a second hand-maintained feature count.

| Coverage question                                | Source of truth                                                                                             | How to check                                                                                                   |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Which connectors execute, and which are preview? | [Connector catalog](CONNECTORS.md), `connectors/catalog.json`                                               | `grc-lake connectors validate`; runner and catalog tests under `tests/`                                        |
| Which requirements have reviewed mappings?       | Generated [framework coverage](FRAMEWORK_COVERAGE.md)                                                       | `make coverage-doc`; review the generated diff and effective mapping versions                                  |
| Which lakes and deployment modes work?           | [Deployment compatibility](DEPLOYMENT.md#deployment-and-lake-compatibility), [BYOL](BRING_YOUR_OWN_LAKE.md) | Qualify reader, schema mapping, application storage and export separately                                      |
| What goes in and comes out?                      | [Data model](DATA_MODEL.md), [data flow](DATA_FLOW.md), [API contract](api/AGENT_API.md)                    | Schema validation, replay/identity tests, export round trips and generation verification                       |
| What scales, with which settings?                | [Distributed mode](DISTRIBUTED.md), [audit scale](AUDIT_SCALE.md), [benchmarks](BENCHMARKS.md)              | Record workload, storage, hardware, configuration, concurrency, latency and resource use                       |
| Which user journeys exist?                       | [Console UX](CONSOLE_UX.md), `app/web/e2e/`                                                                 | Synthetic browser tests plus authorized deployment checks; an accessible page alone is not a completed journey |

## Latest bounded qualification

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
