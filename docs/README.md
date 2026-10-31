# GRC Lake documentation

Every guide in `docs/`, grouped by task. New here? Start with the
[5-minute tutorial](TUTORIAL_5_MIN.md) and [architecture](ARCHITECTURE.md).

For a real evaluation and contribution feedback, use the [bounded pilot guide](PILOT.md).

## Start

| Guide                                                                   | Covers                                                                                                 |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| [5-minute tutorial](TUTORIAL_5_MIN.md)                                  | Sample data to evaluated controls, a mapping review, and an export                                     |
| [AI discovery walkthrough](AI_DISCOVERY_WALKTHROUGH.md)                 | A temporary AI lab: discover models and agents, inspect evidence, then start a bounded real evaluation |
| [Product walkthrough](PRODUCT_WALKTHROUGH.md)                           | Running the demo and what each console page does                                                       |
| [Scenarios](SCENARIOS.md)                                               | End-to-end scenarios over the bundled data                                                             |
| [Auditor walkthrough](AUDITOR_WALKTHROUGH.md)                           | The auditor's path through shares, snapshots, and workpapers                                           |
| [Control workflow qualification](CONTROL_WORKFLOW_QUALIFICATION.md)     | Synthetic access/change failure cases and retained workpapers                                          |
| [Connector workflow qualification](CONNECTOR_WORKFLOW_QUALIFICATION.md) | Offline GitHub, Okta and Jira collection-to-export evidence                                            |
| [Vendor diligence use case](USE_CASE_VENDOR_DILIGENCE.md)               | Just-in-time vendor diligence snapshots                                                                |
| [AWS + Snowflake demo](AWS_SNOWFLAKE_DEMO.md)                           | Demo package for AWS evidence in Snowflake                                                             |
| [Live cloud POC](LIVE_CLOUD_POC.md)                                     | Connecting a real AWS, Azure, or GCP account read-only                                                 |
| [Shareable demo](SHAREABLE_DEMO.md)                                     | Publishing a demo link for evaluators                                                                  |
| [Shareable POC hosting](SHAREABLE_POC_HOSTING.md)                       | Hosting a proof of concept                                                                             |

[Current state and coverage](CURRENT_STATE.md) · [Contributor roadmap](../ROADMAP.md) · [Contributing](../CONTRIBUTING.md)

[Published GitHub connector receipt, 2026-10-31](qualification/live/2026-10-31-github-published.md) · [Connector qualification matrix](CONNECTOR_QUALIFICATION.md) · [GitHub collection contracts](GITHUB_QUALIFICATION.md) · [Live receipts, 2026-10-24](qualification/live/2026-10-24.md) · [Databricks trial receipt](qualification/live/2026-10-25-databricks.md) · [AWS and GitHub binding receipt](qualification/live/2026-10-26-aws-github-binding.md) · [GCP effective-policy receipt](qualification/live/2026-10-26-gcp-effective-policy.md) · [Azure Defender receipt](qualification/live/2026-10-26-azure-defender.md)

## Operate

[Reconcile live receipts](qualification/RECONCILING_LIVE_RECEIPTS.md) explains how to
check retained run evidence and link bounded connector qualification.

[Upgrade from TrustOps to GRC Lake](REBRANDING.md) covers preserved data and integration identities.

| Guide                                                                    | Covers                                                  |
| ------------------------------------------------------------------------ | ------------------------------------------------------- |
| [Deployment](DEPLOYMENT.md)                                              | Self-hosted, hosted, and existing-lake deployment paths |
| [Server auth](SERVER_AUTH.md)                                            | SSO (OIDC, SAML), roles, API keys, hosted credentials   |
| [Connector credentials](CONNECTOR_CREDENTIALS.md)                        | Per-source credential setup                             |
| [Continuous ingestion](CONTINUOUS_INGESTION.md)                          | Scheduled sync and evaluation                           |
| [Operations contracts](OPERATIONS_CONTRACTS.md)                          | Generation archival, retention, integrity checkpoints   |
| [Evidence recovery](EVIDENCE_RECOVERY.md)                                | Recovery and external checkpoints                       |
| [DuckDB exports](DUCKDB_EXPORTS.md)                                      | DuckDB projection recovery                              |
| [Audit scale](AUDIT_SCALE.md)                                            | Large-volume ingestion, evaluation, and synthetic data  |
| [Commercial hosted](COMMERCIAL_HOSTED.md)                                | Gated hosted features: invites, limits, SCIM, billing   |
| [Release readiness](RELEASE_READINESS.md)                                | Release gates and what they prove                       |
| [Backup and restore](runbooks/BACKUP_RESTORE.md)                         | Backing up the lake and app database                    |
| [Distributed PostgreSQL and S3](DISTRIBUTED.md)                          | Shards, partitions, replicas and operational boundaries |
| [HA and read replicas](runbooks/HA_READ_REPLICAS.md)                     | Local and distributed deployment topology               |
| [Connector sync observability](runbooks/OBSERVABILITY_CONNECTOR_SYNC.md) | Connector sync dashboards                               |
| [Headless connector setup](playbooks/HEADLESS_CONNECTOR_SETUP.md)        | Configuring connectors without the console              |
| [HRIS personnel audit](playbooks/HRIS_PERSONNEL_AUDIT.md)                | HR systems and offboarding checks                       |

## Evaluate

| Guide                                                                      | Covers                                                            |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| [Evaluation contract](EVALUATION_CONTRACT.md)                              | What an evaluation guarantees                                     |
| [Evidence evaluation semantics](EVIDENCE_EVALUATION_SEMANTICS.md)          | How evidence states become results                                |
| [Evidence lineage](EVIDENCE_LINEAGE.md)                                    | Source identity, hashes and result links                          |
| [Assessment generations](ASSESSMENT_GENERATIONS.md)                        | Publication and failure contracts                                 |
| [Assessment application contract](ASSESSMENT_APPLICATION_CONTRACT.md)      | Shared services, durable outcomes, API limits and retries         |
| [Collection completeness](COLLECTION_COMPLETENESS.md)                      | Partial and blocked collection                                    |
| [Population reconciliation](POPULATION_RECONCILIATION.md)                  | Reconciling the evidence population                               |
| [Control test workpapers](CONTROL_TEST_WORKPAPERS.md)                      | Control design and period testing                                 |
| [Governed remediation](GOVERNED_REMEDIATION.md)                            | Exceptions and remediation                                        |
| [Audit readiness](AUDIT_READINESS.md)                                      | Audit-readiness API and audit room                                |
| [GRC automation](GRC_AUTOMATION.md)                                        | The automated compliance loop and known gaps                      |
| [Common control framework](COMMON_CONTROL_FRAMEWORK.md)                    | Safeguards, families, and categories                              |
| [CCF assessment reads](CCF_READS.md)                                       | Reading CCF results                                               |
| [CCF requirement gaps](CCF_REQUIREMENT_GAPS.md)                            | Mapping, safeguard and evidence gaps                              |
| [CCF risk monitoring](CCF_RISK_MONITORING.md)                              | Risk prioritization and ongoing monitoring                        |
| [CCF AI context](CCF_AI_CONTEXT.md)                                        | AI inventory and deployment context                               |
| [Framework packs](FRAMEWORK_PACKS.md)                                      | Pack contents, manifests, and gaps                                |
| [Portable framework coverage report](FRAMEWORK_COVERAGE_REPORT.md)         | Frozen catalog counts, mapping review and assessment gaps         |
| [Framework coverage](FRAMEWORK_COVERAGE.md)                                | Generated per-framework coverage matrix                           |
| [ISO 27001 ISMS assessments](ISO27001_ISMS_ASSESSMENTS.md)                 | Management-clause contracts, evidence, and review boundaries      |
| [Mapping review](MAPPING_REVIEW.md)                                        | Reviewing proposed safeguard mappings                             |
| [SOC 2 and ISO review batches](reviews/SOC2_ISO_REVIEW.md)                 | Source-guided proposals, operating contracts and review questions |
| [Recovery and confidentiality review](reviews/RECOVERY_CONFIDENTIALITY.md) | Focused SOC 2 candidates and required substantiation              |
| [NIST assessment expansion](NIST53_ASSESSMENTS.md)                         | Source-native assessment contracts and review boundaries          |
| [Catalog versioning](CATALOG_VERSIONING.md)                                | Catalog versions and audit pinning                                |
| [AI bill of materials](AIBOM.md)                                           | AI inventory evidence                                             |

## Integrate

[Data contracts](DATA_CONTRACTS.md) covers schemas, formats, and read/write boundaries.
[Connector test accounts](CONNECTOR_TEST_ACCOUNTS.md) lists sandbox/trial options and qualification checks.

| Guide                                                                | Covers                                                        |
| -------------------------------------------------------------------- | ------------------------------------------------------------- |
| [Connectors](CONNECTORS.md)                                          | Connector catalog, release stages, and access model           |
| [Agent-Bom report import](AGENT_BOM_IMPORT.md)                       | Offline scan findings, explicit bindings, and provenance      |
| [Adding connectors](ADDING_CONNECTORS.md)                            | Writing a connector adapter                                   |
| [AWS connector architecture](aws-connector-architecture.md)          | How the AWS connector collects                                |
| [Repository governance connector](REPO_GOVERNANCE_CONNECTOR.md)      | GitHub and GitLab governance and public repository audit      |
| [Ingestion and idempotency](INGESTION_CONNECTORS_IDEMPOTENCY.md)     | Ingestion, connectors, and idempotency                        |
| [Organization scopes](ORGANIZATION_SCOPES.md)                        | Select named accounts for scoped ingestion and CCF evaluation |
| [Bring your own lake](BRING_YOUR_OWN_LAKE.md)                        | Existing-lake readers, lake mappings, OCSF presets            |
| [Security data lakes](HERO_DATA_LAKES.md)                            | Supported lakes and warehouses                                |
| [Iceberg REST](ICEBERG_REST.md)                                      | Iceberg REST evidence publication                             |
| [Parquet export](PARQUET_EXPORT.md)                                  | Portable evidence with Parquet                                |
| [OSCAL export](OSCAL_EXPORT.md)                                      | Portable CCF bundles and assessment results                   |
| [Webhooks](WEBHOOKS.md)                                              | Outbound event delivery                                       |
| [CI gate](CI_GATE.md)                                                | Failing a pipeline on posture                                 |
| [CI posture gate playbook](playbooks/CI_POSTURE_GATE.md)             | Setting up the gate in CI                                     |
| [Headless GRC](HEADLESS_GRC.md)                                      | API, MCP, and agent architecture                              |
| [Agent harness](AGENT_HARNESS.md)                                    | Persisted agent runs and approvals                            |
| [Agent API](api/AGENT_API.md)                                        | The v1 contract for humans and agents                         |
| [Agent skills](api/AGENT_SKILLS.md)                                  | Agent skill catalog                                           |
| [MCP evidence and approvals](cookbook/MCP_EVIDENCE_AND_APPROVALS.md) | MCP cookbook for evidence requests and approvals              |
| [API v1 migration](API_V1_MIGRATION.md)                              | Console migration to `/api/v1`                                |

## Security

| Guide                                                              | Covers                                                                |
| ------------------------------------------------------------------ | --------------------------------------------------------------------- |
| [Trust boundaries](THREAT_MODEL.md)                                | Threat model and trust boundaries                                     |
| [Dependency security](DEPENDENCY_SECURITY.md)                      | Dependency security scope                                             |
| [Scorecard remediation](SCORECARD_REMEDIATION.md)                  | Review, fuzzing, and badge evidence gates                             |
| [Third-party assets](THIRD_PARTY_ASSETS.md)                        | Policy for third-party logos and assets                               |
| [CI duration balancing](benchmarks/CI_RUNTIME.md)                  | Test allocation, retained timings and measured CI baseline            |
| [Benchmarks](BENCHMARKS.md)                                        | Validation and benchmark plan                                         |
| [Artifact hashing benchmark](benchmarks/ARTIFACT_HASHING.md)       | Artifact hashing memory benchmark                                     |
| [CCF pipeline benchmark](benchmarks/CCF_PIPELINE.md)               | Bounded CCF pipeline measurements                                     |
| [Investigation graph benchmark](benchmarks/INVESTIGATION.md)       | Bounded graph reads and failure receipts                              |
| [Investigation cache benchmark](benchmarks/INVESTIGATION_CACHE.md) | Generation-model reuse, latency and memory tradeoffs                  |
| [Local graph release profile](benchmarks/RELEASE_PROFILE.md)       | Accepted bounded workload, latency, memory and tenant-progress checks |

## Reference

Several pages describe the architecture at different depths; start with
[Architecture](ARCHITECTURE.md).

| Guide                                                    | Covers                                                                     |
| -------------------------------------------------------- | -------------------------------------------------------------------------- |
| [Architecture](ARCHITECTURE.md)                          | Component map, module boundaries, design rules                             |
| [Components](architecture/COMPONENTS.md)                 | Component reference                                                        |
| [Data flow](DATA_FLOW.md)                                | Where evidence is stored and how it moves                                  |
| [Data model](DATA_MODEL.md)                              | Evidence, controls, tests, and snapshots                                   |
| [Entity registry](ENTITY_REGISTRY.md)                    | Explicit source identities, canonical aliases and binding revision history |
| [Product artifacts](PRODUCT_ARTIFACTS.md)                | Files and outputs GRC Lake produces                                        |
| [Evidence investigation graph](INVESTIGATION_GRAPH.md)   | Exact bindings, graph navigation, relationship meanings                    |
| [Console UX](CONSOLE_UX.md)                              | Console operator and contributor guide                                     |
| [Visual system](VISUAL_SYSTEM.md)                        | Console layout and components                                              |
| [Brand](BRAND.md)                                        | Name, voice, and brand constants                                           |
| [Diagram index](diagrams/README.md)                      | All diagrams                                                               |
| [Architecture: local mode](diagrams/architecture.md)     | File-backed architecture                                                   |
| [ASCII system map](diagrams/ascii-system-map.md)         | Text system map                                                            |
| [Agent workflow](diagrams/agent-workflow.md)             | Persisted agent harness flow                                               |
| [Identity and auth](diagrams/auth-identity.md)           | Identity and auth boundary                                                 |
| [Connector ingestion](diagrams/connector-ingestion.md)   | Read-only connection model                                                 |
| [Core GRC loop](diagrams/core-grc-loop.md)               | Sync to auditor-ready proof                                                |
| [Data model diagram](diagrams/data-model.md)             | Analytics lake in local mode                                               |
| [Deployment models](diagrams/deployment-models.md)       | Deployment options                                                         |
| [Dual lakehouse](diagrams/dual-lakehouse.md)             | Snowflake and ClickHouse roles                                             |
| [Evaluation lifecycle](diagrams/evaluation-lifecycle.md) | Evaluation stages                                                          |
| [Hosting](diagrams/hosting.md)                           | Hosting model                                                              |
| [Unified data model](diagrams/unified-data-model.md)     | Single-page data model                                                     |

[FedRAMP KSI assessment subset](FEDRAMP_KSI_ASSESSMENTS.md) documents the two source-pinned proposed indicators, evidence limits and draft workpaper path.
