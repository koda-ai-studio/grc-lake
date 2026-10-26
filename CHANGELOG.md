# Changelog

All notable GRC Lake changes are summarized here. Versions follow semver for the
Python package, Helm chart, and bundled web console.

## Unreleased

- Demote 354 historical mappings without a recorded reviewer or decision receipt to proposed. Mapped coverage stays 2,196/2,282; reviewed requirements fall from 1,225 (53.7%) to 886 (38.8%). Passing safeguard evidence cannot attest those proposed mappings or export them as reviewed OSCAL implementations. The historical inventory and origin commits remain available.

- `grc-lake mcp` runs the MCP server (same as `grc-lake-mcp`), and the release workflow lists GRC Lake in the official MCP Registry as `io.github.koda-ai-studio/grc-lake` from `server.json`, verified by GitHub OIDC and a hidden `mcp-name` marker in the PyPI README. The registry entry launches `uvx --from "grc-lake[mcp]==<version>" grc-lake mcp`. A registry failure never blocks the PyPI package or the GitHub release.

## 0.3.16 - 2026-10-26

- AWS and GCP collection-gap rows, and AWS inventory-absence rows, now sit on their own assets (`aws:account:<id>:collection:<collection>`, `aws:account:<id>:inventory`, `gcp:project:<id>:collection:<collection>`) instead of the account or project asset that carries the password-policy or org-policy verdict. A denied read or a missing CloudTrail trail no longer hides a failing verdict as `not_evaluated`. A collection gap from a source still keeps every safeguard that source binds from passing.
- Provider benchmarks are assessed only from their own provider's evidence. The framework registry declares `provider_sources` (CIS AWS: `aws`, `aws_config`), and a CIS AWS requirement now counts only asset results from those sources. Previously a shared safeguard let GCP or identity-provider evidence decide CIS AWS results: enforced GCP org policies could mark `CIS-AWS-1.10` and other identity recommendations passing with no AWS evidence, and a failing GCP policy failed them. Without AWS evidence they are now `not_evaluated`.

## 0.3.15 - 2026-10-26

- Databricks: document the `databricks-sql-access` entitlement in the reader's minimum permissions (a new service principal without it gets HTTP 403), and record a live multi-chunk run (77,036 records over 3 result chunks, reconciled with the provider). The connector stays Preview.
- Security: upgrade certifi to 2026.10.23, which removes the distrusted "emSign ECC Root CA - C3" and "emSign Root CA - C1" roots from the Python CA bundle used for outbound HTTPS, plus pip 26.2.2 and uv 0.13.5 (CI and the image build). The container's system CA bundle already excluded both roots; the 0.3.14 image's Python bundle did not.
- GCP `iam.disableServiceAccountKeyCreation` and `compute.requireOsLogin` constraints that are not set on the project are now evaluated from their effective (inherited) policy, so an organization or folder enforcement can pass `SG-IDENTITY-001` and an unenforced one fails it. A conditional or list rule, or an effective policy that cannot be read (new permission `orgpolicy.policy.get`, in `roles/orgpolicy.policyViewer`), stays `not_evaluated` and is reported as a coverage gap.
- `azure-posture` now collects Microsoft Defender for Cloud assessments (read-only ARM `Microsoft.Security/assessments`, `api-version=2021-06-01`, same-host `nextLink`, bounded pages, `Retry-After`). Healthy is `pass`, Unhealthy `open`, NotApplicable `observed` and any other code `not_evaluated`. A reviewed allowlist of 12 built-in assessment keys binds to `SG-IDENTITY-001` (disabled and guest accounts with privileged access), `SG-DATAPROTECTION-001` (storage secure transfer, SQL TDE), `SG-LOGGING-001` (Key Vault diagnostic logs) and `SG-VULNERABILITYMANAGEMENT-001` (machine vulnerability findings), so Azure verdicts reach framework (CCF) results; other assessments keep their verdict unbound. A denied or malformed assessment read is a coverage gap and the run is marked partial. Reader already grants the read.

## 0.3.14 - 2026-10-26

- The Overview's assessed-coverage tile now states how many requirements are attested ("3 attested" on the demo), using the same count as the Controls page, and an overflowing graph node inspector fades at its bottom edge so it reads as scrollable. All 42 demo screenshots were retaken; the Evidence capture had still shown 56 records instead of 59.

- `grc-lake assessment status --format summary` adds a framework line with attested, failing and not-assessed CCF requirements, matching the console and trust page. The graph workspace tabs now align with the page content instead of touching the top bar.

- Record a live AWS and GitHub pilot before and after flagship safeguard binding: the same read-only collection moved from no framework results to 103 failing requirements from verified IAM findings and one attested pass from a verified branch-protection verdict.

- Okta and Google Workspace MFA enrollment and GCP expected org-policy constraints now reach framework (CCF) results through `SG-IDENTITY-001`. An active user without MFA, or an unenforced `iam.disableServiceAccountKeyCreation` or `compute.requireOsLogin`, fails the safeguard. It passes only when every accepted asset is assessed and passing. Unreadable factors, unknown enrollment, conditional rules and constraints not set on the project (newly recorded as `not_evaluated`) block a pass, and observations stay unbound. Azure, Entra, Jira, Intune, Jamf and CrowdStrike stay unbound: their signals are heuristic or observations, or no safeguard accepts their asset types and control tags.

- Record a second Databricks live run against a populated system audit log: 928 rows recollected without duplicates, with open audit events reconciled to the provider's count of failed requests. The connector stays Preview until multi-chunk, throttling and credential-expiry behavior are exercised.

- Discover installed connector plugins once per process instead of on every catalog load. Safeguard evaluation reloads the connector catalog for each evaluation, and each reload scanned every installed distribution's entry points (about 40 ms); the NIST SP 800-53 assessment tests drop from 114 s to 12 s locally, and evaluation-heavy API and pipeline paths stop paying the scan.

- Record msaad00's batch approval of the SOC 2 and ISO 27001 mapping queue as one decision, without per-mapping rationales. The receipt binds 73 mappings (37 SOC 2, 36 ISO 27001) to the fingerprints in the archived 123-candidate queue. The 50 title-theme ISO 27001 candidates are listed as excluded and stay proposed. Reviewed requirements rise from 1,163 to 1,227 (53.8%): SOC 2 from 33/61 to 61/61 and ISO 27001 from 17/93 to 53/93. Mapping coverage is unchanged and ISO 42001 stays pending. This is a mapping approval only; operating effectiveness and certification need separate evidence.

- Record msaad00's batch approval of the SOC 2 and ISO 27001 mapping queue as one decision, without per-mapping rationales. The receipt binds 71 mappings (35 SOC 2, 36 ISO 27001) to the fingerprints in the archived 123-candidate queue. The 50 title-theme ISO 27001 candidates, and SOC2-A1.3 and SOC2-C1.1 (whose recovery-testing and data-protection recommendations in `docs/reviews/RECOVERY_CONFIDENTIALITY.md` remain open), are listed as excluded and stay proposed. Reviewed requirements rise from 1,163 to 1,225 (53.7%): SOC 2 from 33/61 to 59/61 and ISO 27001 from 17/93 to 53/93. Mapping coverage is unchanged and ISO 42001 stays pending. This is a mapping approval only; operating effectiveness and certification need separate evidence.

- Refresh the README structure and console screenshots, expose the bounded graph performance profile, and reconcile connector summaries with the catalog. Preview qualification now distinguishes limited live receipts from provider-wide coverage. Add a regression check for overview counts and remove an unmeasured hosted-demo setup-time claim.

- Add a repeatable local graph performance acceptance check for two tenants at 1k/10k records each. It checks cold and warm latency, idle-expiry reads, memory and tenant progress while reporting admission rejections separately. These bounded synthetic measurements do not qualify production capacity.

- Renew Databricks OAuth tokens before expiry and retry an unauthorized SQL request once with fresh credentials. Invalid token lifetimes are rejected, repeated authorization failures stop, and rate-limit retries continue to honor `Retry-After`. These recovery paths are tested with synthetic responses; live expiry and throttling remain separate qualification.

- Let mapping-review packets select exact pending requirements with repeatable `--control` flags. Preserve candidate fingerprints and coverage denominators; reject missing or already-reviewed selections before writing output. Add focused recovery/confidentiality review guidance without approving either mapping, align the pip and Compose tutorial versions, and document an optional pilot-feedback and stability period.

- Report an OSCAL assessment-results finding as `satisfied` only when the control test passes and the requirement's framework (CCF) result is `pass` through reviewed mappings. A passing control test with only proposed mappings, or no CCF result, is now `not-satisfied` (reason `other`); each finding adds a `trustops-ccf-status` prop. Previously the golden demo exported 8 SOC 2 objectives as satisfied while every CCF requirement was not evaluated.

- The public trust summary (`/api/public/trust/{token}`) adds `attested_pass_count` per framework and overall, and reads `ready` only when every catalogued requirement has a framework (CCF) pass. A framework whose control tests all pass without that attestation now reads `not_attested`, shown as "Control tests passing · Not attested".

- Label a mapping whose maintainer review no longer applies (the requirement version changed or an inherited review is invalid) as "Earlier maintainer review · needs re-review" in Mapping review instead of "Maintainer review", since it counts as proposed. Framework badges whose short mark is longer than four characters, such as NIST SP 800-53, show the framework icon at small sizes instead of wrapping the mark onto two lines.

- The golden demo now reaches three attested framework (CCF) passes: synthetic ISO 27001 assessor records for A.5.13, A.5.28 and A.8.17 bind to each requirement's only safeguard, whose mapping is maintainer reviewed, on the one `service` asset those safeguards accept. The Controls page reads "11 of 41 control tests · 3 attested" instead of "0 attested"; evaluation rules, safeguard definitions and review states are unchanged, and the demo keeps its failing, stale and unattested controls.

- Reject incomplete Databricks SQL results before replacing evidence or advancing watermarks. Validate result schemas, row counts and chunk offsets, follow index-only chunk cursors, and record failed reads as partial runs with a collection gap. Malformed chunk links are rejected before requesting them. The adapter remains Preview; the added qualification uses synthetic responses.

- `grc-lake frameworks safeguards --format table` now states how many maintainer-reviewed requirements rest only on legacy reviews with no recorded reviewer, matching the console and README. A release test keeps the README and 5-minute tutorial install pins on a single published version; the tutorial had mixed 0.3.12 and 0.3.13.

- AWS posture and GitHub governance verdicts now reach framework (CCF) results. AWS MFA enrollment (console users), access-key hygiene, and account password policy events bind to `SG-IDENTITY-001`; privileged-name flags and observations stay unbound. GitHub sync adds a `repository.governance.change_approval` verdict for the default branch, bound to `SG-CHANGEAPPROVAL-001`: `pass` only when protection is readable with at least one required approval, admins included, and force pushes and deletions disabled; `open` with the unmet settings listed; `not_evaluated` when protection is unreadable or incomplete. Previously a live sync with failing IAM posture left every safeguard not evaluated. Change-approval requirements such as SOC 2 CC8.1 stay not evaluated until their mappings are reviewed.

## 0.3.13 - 2026-10-25

- Scope experimental OCSF event and asset identity to the source account, so colliding user/event IDs in different accounts stay separate through CCF assessment. Missing assessed subjects no longer fall back to a cloud account. Mixed mapping errors create a collection gap, mark the run partial, and hold positive outcomes at `not_evaluated` until repair and replay. OCSF preset IDs change; re-ingest into a fresh lake to avoid mixing scoped and unscoped history.

- Accept both Databricks audit response field spellings in the POC bootstrap. Empty audit windows and incomplete response codes no longer imply a passing denied-access review. Record bounded live OAuth and recollection checks; the adapter remains Preview.

- Carry framework (CCF) results and reviewed/proposed mapping counts into both framework and repository maps. A passing control test with a missing or non-passing CCF result stays unattested, including older payloads. Rebuild cached maps when their assessment inputs change.

- Keep investigation graph models warm while they are in use: a read now renews the 60-second cache entry, so a model expires only after 60 seconds without reads. Document that models in active use which do not fit the cache budget together can rebuild on every request. The control drawer now says "1 record with outcomes" instead of "1 records". Refresh the Controls, Frameworks and control drawer screenshots for the control test and framework result labels.
- Refuse a release tag while `## Unreleased` still has entries, so every shipped change appears in the release notes. Rescan the published image daily on both architectures with the release vulnerability policy.
- Fix investigation graph accuracy. Graph versions no longer depend on the process hash seed, so expanding a node after a restart or on another worker no longer fails with "graph version changed". Requirement nodes add `ccf_status`, `reviewed_safeguard_count` and `proposed_safeguard_count` from the CCF assessment beside the posture `status`, plus posture `rule_reasons`, `evaluation_rule` and `open_event_count`. Requirement and safeguard neighborhoods now include the source that produced each evidence record. Safeguard evidence bound to an asset type the safeguard does not accept is marked `binding: "invalid_asset_type"` instead of drawn as supporting evidence.
- Delete the `grc-lake demo` temporary lake when the process receives SIGTERM, not only on Ctrl+C.
- Show the framework (CCF) result next to the control test result. `/api/v1/controls`, `/api/v1/control-tests` and `/api/v1/frameworks/{framework_id}/detail` controls now carry `ccf_status` (the requirement result from `gold/ccf_assessment.json`, `not_evaluated` when absent), `reviewed_safeguard_count` and `proposed_safeguard_count`. Framework detail keeps `passing_control_count` (control tests passing) and adds `attested_pass_count`. The Controls page, control drawer and Frameworks drawer label a passing control test without a CCF pass as "Control test passing · Not attested" with its mapping counts and a Mapping review link, and the framework headline leads with attested passes ("8 control tests passing · 0 attested"). Failing control tests stay failing.
- Keep the console graph responsive on large maps. A map above 500 nodes, such as All frameworks or NIST SP 800-53 on the golden demo, is no longer laid out; it says how to narrow the view instead. Drawable maps above 200 nodes render only the nodes in view, and hover or selection no longer re-runs the layout. On the golden demo, choosing All frameworks went from a 26-second freeze with about 39,000 DOM elements to under a second with about 600.
- Label graph outcomes accurately. Passing evidence that is stale or expired reads "Stale evidence". When a control node carries a framework result (`ccf_status`) that is not a pass, a passing control test reads "Control test passing · Not attested", and the node inspector shows the framework result, reviewed and proposed safeguard counts, the evaluation rule, open events and rule reasons. Edges with `binding: "invalid_asset_type"` draw as red dashed lines labeled as invalid, never as support. Older payloads without these fields keep their previous labels.
- Make the graph usable by keyboard and screen reader. Nodes show a visible focus ring, come before edges in tab order (edges are no longer tab stops), and are announced as "kind: label, status".
- Improve graph readability. Maps open at a readable zoom from the focused control or the start of the layout, with a note when part of the map is outside the view. Each status has its own icon shape, safeguards are named as safeguards, catalog mappings draw dashed (dotted while proposed), and the investigation view has a column legend. The minimap is hidden on phones, the maps legend stays visible in its rail, and the map uses framework names, readable evidence names and correct plurals. An unknown starting point says "Starting point not found" with a reset, starting points no longer repeat their kind, and empty layer chips are dimmed.

## 0.3.12 - 2026-10-25

- Pin README links and screenshots to the release tag in the published package description, so the PyPI project page renders them. The release workflow rewrites the build checkout only, and the wheel gate refuses a published description with repository-relative links.

## 0.3.11 - 2026-10-24

- Make the `github-security` Test connection a real read. The probe resolves the token as sync does (`credential_ref`, then `options.token_env`, then the provider default; a literal `token` is never used), reads the repository metadata, and sends one request to each of the code scanning, secret scanning and Dependabot alert endpoints in the sync's request shape. Each signal reports `readable`, `forbidden` or `not_enabled`. An unreadable repository or any other HTTP failure now fails the probe instead of passing ahead of a failing sync. Probes that relied on a literal `token` with no resolvable reference now fail.
- Report AWS Security Hub not enabled (`InvalidAccessException`) and an account outside an organization (`AWSOrganizationsNotInUseException`) as the coverage-gap reason `service_not_enabled`, separate from `permission_denied` and `read_failed`. The sync stays partial.
- Fail `CIS-AWS-3.1` and `CIS-AWS-3.3` when a successful read finds no CloudTrail trail or no AWS Config configuration recorder in a region. The connector emits an account-scoped open `aws.inventory.absent.cloudtrail` or `aws.inventory.absent.config` row; a failed read stays a coverage gap. CloudTrail is now described with shadow trails included, so a multi-region or organization trail homed elsewhere counts as coverage without adding inventory rows. Accounts with no trail or recorder in a selected region gain failing results on these controls.
- Refuse a hosted-mode tenant kubeconfig whose selected user runs an `exec` plugin or `auth-provider` command. The kubeconfig is parsed with a safe loader and never executed; an unreadable kubeconfig fails closed. Local and CLI runs still accept exec plugins, such as the Nebius CLI login.
- Record bounded live read-only receipts for `aws-posture`, `azure-posture`, `gcp-posture` and `github-security` (2026-10-24, source `f4532d21`), with counts reconciled against each provider's CLI and provider identifiers omitted. The qualification matrix links them and names the maintainer as owner. Each covers one test account, subscription, project or public repository, not provider-wide coverage.
- Fix `github-security` sync failing with HTTP 400 on repositories with Dependabot alerts. GitHub rejects page-number pagination on that endpoint, so the adapter now follows `Link` cursors, restricted to the same host and endpoint.
- Assess GPU clouds. `kubernetes-cluster` now records GPU and InfiniBand workloads (`nvidia.com/gpu`, `amd.com/gpu`, `rdma/ib`) as inventory and judges LoadBalancer, NodePort, and KServe InferenceService exposure against `SG-NETWORK-001`. A public load balancer without source ranges is open (high when it fronts a GPU workload), a cluster-local inference endpoint passes, and an external endpoint, NodePort, or unassigned address stays `not_evaluated`. It works with CoreWeave and Nebius managed Kubernetes. The ClusterRole adds `list services` and, on KServe clusters, `list inferenceservices`; a denied read is a coverage gap, not a failed sync. Existing clusters with LoadBalancer or NodePort Services gain network-safeguard results.
- Add the `lambda-cloud` connector (preview) for Lambda GPU instances. It judges inbound exposure from the global and attached firewall rulesets (`SG-NETWORK-001`), flags DSA and short RSA SSH keys and API keys without an expiry or unused for 90 days (`SG-IDENTITY-001`), and never passes logical access on key strength alone. Requests are GET-only, paced to the documented one per second, and sent to the fixed API host. Jupyter tokens, IP addresses, and key material are dropped. Encryption settings, InfiniBand isolation, endpoint authentication, and `us-south-1` firewall coverage are not visible through these APIs and are not assessed.
- Add the `training-completion` preview connector. It reads security awareness training assignments and completions from LMS or training-platform CSV and JSON exports, using a documented column contract and `options.column_map` for vendor headers. Exports are read from a path under `GRC_LAKE_LAKE_LOCAL_ROOT`, per tenant in hosted mode. Malformed, oversized or empty exports fail the sync with row-level errors that never echo values. After a training or HRIS sync, a derived `hris-training-coverage` snapshot joins completions to the HR population. Each person row binds `SG-TRAINING-001`: completed within the window passes, while overdue, expired or missing training is open. People absent from HR, conflicting identifiers, and completions without any HR evidence are not evaluated. A summary row states how many active personnel completed required training. Terminated staff and new hires inside the onboarding grace are excluded. Framework tags stay within the safeguard's reviewed crosswalk, and proposed mappings such as ISO 27001 A.6.3 are not attested. The Parquet reader and this connector share one local-path guard.
- Add the `snyk-vulnerabilities` connector (preview). It reads Snyk organizations, projects, and issues through the REST API with a read-only token held by reference. Regions are limited to the four Snyk API hosts. Open-source, container, and code vulnerability issues and per-project test coverage bind `SG-VULNERABILITYMANAGEMENT-001`, so SOC 2 CC7.1 and the other mapped requirements follow its reviewed crosswalk. Open issues are open findings. Ignored issues, projects never tested or not tested within the window (7 days by default), and incomplete listings are `not_evaluated`, never a pass. Unreadable organizations and exhausted page budgets are recorded as coverage gaps and mark the sync partial. Fixture-tested only; not yet run against a live Snyk organization.
- Add `grc-lake demo`: load the synthetic golden company into a temporary lake, serve the console on loopback without authentication, and open the browser. Falls back to local mode without the `server` extra; refuses a busy port and deletes the lake on exit.
- Publish a read-only live demo of the console to GitHub Pages from recorded synthetic API responses. Writes are blocked in the browser, unrecorded views say so, and the packaged console build is unchanged; the copy step refuses demo or non-`/console` builds.
- Bind OCSF events to Common Control Framework safeguards. Lake mapping specs accept `fields.safeguard_ids` and ordered `rules` that set a row's outcome, control hints, and safeguard binding together from the row's own values. Safeguard ids are checked against the catalog. A new `not_evaluated` outcome blocks a pass without asserting a failure.
- Evaluate OCSF 1.1.0 sign-ins and privilege grants. In `ocsf/authentication`, a successful Logon passes `SG-IDENTITY-001` when `is_mfa` is true and is open when it is false. In `ocsf/account_change`, a successful Attach Policy is pending review on `SG-IDENTITY-002`. Failed sign-ins, logons without an `is_mfa` value, other account changes, and API activity remain observations. Framework requirements follow each safeguard's reviewed crosswalk, and proposed mappings are not attested. Both presets now use the `identity_user` asset type. Existing preset users see new pass, open, and pending results on SOC 2 CC6.1 and related requirements. Add `"rules": []` to a preset reference to keep presence-only mapping.
- Bind more OCSF 1.1.0 events to Common Control Framework safeguards. The new `ocsf/group_management` preset (Group Management, 3006) holds a successful Add User or Assign Privileges for review on `SG-IDENTITY-002`, the same way as a privilege grant. Amazon Security Lake's native CloudTrail source does not emit this class. Vulnerability findings on EC2 instances and ECR container images bind `SG-VULNERABILITYMANAGEMENT-001`, and compliance checks on EC2 instances bind `SG-CONFIGBASELINE-001`. Both keep their existing status. Detection and legacy security findings bind nothing. The finding presets and `ocsf/api_activity` now translate Security Hub and CloudTrail resource types to catalog asset types where there is a clear equivalent (for example `AwsEc2Instance` and `AWS::EC2::Instance` to `host`), so one resource keeps one type across sources. The vendor value moves to `attributes.resource_type`. Other types are unchanged. Translated resources count toward safeguard scope, so an instance with no vulnerability evidence now shows as unassessed.
- Narrow `ocsf/account_change` privilege-grant control hints to `SOC2-CC6.2` and `ISO27001-A.5.18`, matching `SG-IDENTITY-002`'s crosswalk like the group rule. Other account changes keep the preset's hints.
- Report failed snapshot requests as errors instead of success notices.
- Serve local mode from the bare package. The scheduler no longer imports SQLAlchemy-backed operational retention at import time; the base-only wheel gate now starts local mode and requests the console and core API.
- Bring selected graph node details into view on phones and tablets where the inspector sits below the canvas. Preserve the adjacent desktop inspector.
- Restore local fixture loading, pipeline replay and snapshots without optional server dependencies. Detect configured application databases before importing SQLAlchemy; retain schema checks and remediation reconciliation for server-backed lakes. Add a base-only installed-wheel gate on each supported CI Python version.
- Update installation examples and publication records for 0.3.11. Keep historical screenshot and scan provenance scoped to their original versions.
- Lock dev-only virtualenv 21.14.13 (GHSA-cx6f-vjhg-g3cc).
- Lock dev-only zod 4.6.7 (GHSA-mrhx-c7xc-m3w5) for the console lint toolchain.
- Lock filelock 4.2.4 (CVE-2026-112907, CVE-2026-112913, CVE-2026-112940) via snowflake-connector-python 5.1.0, which drops its `filelock<4` cap; protobuf resolves to 6.33.6 under the connector's `<7` bound.
- Pin Wolfi brotli runtime libraries to 1.2.0-r7 (CVE-2026-111497). The rest of the runtime package resolution is unchanged on AMD64 and ARM64.

## 0.3.10 - 2026-10-22

- Redirect every console entry URL to the packaged dashboard in both server modes, including `/console/`, instead of serving the static export's unsupported root redirect.

- Preserve account-scoped asset identities and reject unknown identity types rather than treating them as human or machine evidence. Add an experimental canonical entity export with explicit, evidence-referenced aliases and an auditable binding-revision ledger; bindings do not rewrite assessment results or establish identity equivalence automatically.

- Import Agent-Bom reports as scoped observations. Reuse attributed Agent-Bom collection logic for Okta and Entra non-human identities, GCP service-account inventory, and optional AWS role identity policies without a runtime dependency. AWS role policies preserve denies, conditions, literal strings and partial coverage; this does not evaluate effective permissions or establish credentialed provider qualification.

- Reject malformed and incomplete Azure/GCP collections instead of reporting empty success. Guide connector setup through configuration, access testing, sync and evidence review, retaining provider-specific delegation and permission requirements.

- Require complete evidence per asset and sampling window, retain operating deviations even when selected as design evidence, and make readiness holds explicit. Add scoped ISO assessment proposals, a separate ISO 27001 ISMS clause pack, and NIST 800-53 assessment contracts. Proposed mappings remain unapproved and grant no compliance verdict.

- Export portable CCF and framework OSCAL bundles plus frozen coverage, evidence gaps and auditor workpapers. Verify handoff content against retained digests; these checks establish reproducibility and integrity, not source authenticity or sufficient audit evidence. Add synthetic GitHub/Okta/Jira workflow qualification.

- Replace exception-derived API error details with fixed retry/configuration guidance for mapping reviews, public-repository validation, assessment conflicts and cloud linking. Preserve response codes and stale-review rejection; sanitize public cloud-account examples and remove duplicate test imports.

- Refresh locked runtime, console and build dependencies. Container vulnerability scans, authenticated runtime probes and release provenance are required separately for the exact release candidate.

- Bound concurrent investigation reads per authenticated tenant as well as per process. Share limits across credentials, return distinct tenant/process saturation codes, and retain per-tenant rejection counts in the HTTP benchmark. Release both quotas after completion or cancellation.

- Reuse completed investigation models for pinned generations with frozen catalogs in a bounded process-local cache. Invalidate reuse on evidence, triage, vendor and navigation changes; preserve expansion versions and independent response data. Coalesce same-key builds with cancellable waiting and retain no failed or oversized model.

- Reduce investigation graph temporary memory by batching canonical version hashing, releasing build scratch before traversal, and deriving undirected neighbors from directed indexes. Preserve expansion tokens and check cancellation between hash batches. Refresh reproducible graph, pipeline and local distributed measurements with explicit latency and fairness limits.

- Reuse graph adjacency, ordered starting points, default roots, counts and edge positions within the existing bounded model cache. Avoid repeated full-table scans on unfiltered warm reads while preserving layer-sensitive ranking, original edge order, pagination and expansion tokens.

- Retire the unqualified KnowBe4 preview connector, its setup surfaces and qualification tooling. Existing configurations are no longer scheduled and explicit syncs are rejected. Historical evidence, snapshots and exports remain readable; managed local evidence remains available for applicable training records. Remove external sync jobs and revoke unused provider tokens separately.

## 0.3.9 - 2026-10-18

- Reject weak SAML certificate and OIDC signing keys, including refreshed JWKS during key rotation. Bind OIDC token issuer and audience to the configured provider and client. Existing IdPs using RSA keys below 2048 bits or shared-secret ID-token signing must rotate before upgrading.
- Add a bounded deployment TLS checker and local negotiation tests for forward-secret TLS 1.2/1.3, static-RSA rejection, and certificate verification. Document the proxy configuration and qualification scope.

- Retain signed Python build provenance during release dry runs, before publication. Consolidate duplicated route query and pagination helpers without changing response contracts.

## 0.3.8 - 2026-10-17

- Build the container runtime from pinned Wolfi CPython 3.14 and matching system libraries in an empty root. Require the complete installed package set to match the runtime lock, retaining package inventory and licenses. Preserve the shell-free, non-root entrypoint, persistent paths and authentication contract.
- Check populated TLS trust stores alongside native imports, compression, SQLite and XML dependencies. Qualify both architectures with signed SAML, authenticated tenant-isolation, Compose persistence and upgrade probes. Image scans remain unfiltered; no vulnerability suppression or policy exception is added.

## 0.3.7 - 2026-10-16

- Replace the general-purpose runtime OS with a pinned distroless base and only the Python application's required Debian libraries. Remove shells, package managers, mount/login utilities, Perl, and optional terminal/libuuid Python extensions; retain package inventories and licenses for vulnerability scanning. Native dependency, compression, XML, database, authentication, tenant-isolation and persistence probes cover both architectures.
- Block all HIGH and CRITICAL image findings, including those without a listed fix, plus fixable MEDIUM findings. Retain unfiltered scan evidence and fail incomplete reports; no suppression or applicability exception supplies a policy pass.
- Make the framework coverage table header explicit to avoid an implicit string-concatenation warning without changing generated output.
- Give the graph lifecycle test's ordinary cold reads and recovery sufficient time under CI coverage while preserving the injected deadline assertion and production timeout.

## 0.3.6 - 2026-10-16

- Lead coverage reporting with per-framework review depth and distinguish 381 source-native self-maps from 782 crosswalk-reviewed requirements. Share the split across the mapping ledger, API, console, README and generated coverage matrix; neither classification is an operating-effectiveness verdict.

- Retain per-tenant graph admission rejections, make the HTTP benchmark client deadline configurable, and add separate loopback deadline, disconnect and recovery probes. Publish refreshed direct/HTTP graph, CCF pipeline and local PostgreSQL/S3-emulator measurements with reproducible receipts. These synthetic results do not establish production capacity; the proposed 1 GiB graph envelope remains unqualified.

- Limit repository-wide tests to tracked files and fail unexpected missing-extra skips in CI, while allowing documented local dev-only installations.

- Remove the `internal-trust-team` placeholder reviewer from the twelve seed safeguards. Record the 354 mappings reviewed before decision receipts in `controls/reviews/legacy-unattributed.json` with their originating commits and no reviewer. They still count as maintainer-reviewed. Coverage, the framework matrix, the mapping-review queue and the console now flag the 339 reviewed requirements that rest only on them; 824 have a decision receipt. A test lets that list only shrink. Reviewed totals and the 920 receipt-bound approvals are unchanged.

- Cap safeguard fan-out with a ratchet test: the 23 umbrella safeguards above 20 requirements may only shrink, and any other safeguard stays at 20 or fewer. The CCF guide adds a generated table of the broadest safeguards and explains why a pass on one does not demonstrate each mapped requirement.

- Require MCP SDK 1.30.0 or newer within the 1.x series to address CVE-2026-59951. Include the inspected mapping-review archive in Docker build inputs as well as wheel distributions.

- Record maintainer approval of 35 repaired mappings (23 SOC 2, seven ISO 27001, five ISO 42001), with source contracts and per-mapping fingerprints. Reviewed coverage becomes 1,163/2,252 (51.6%); mapped coverage remains 80.1%. Preserve source limitations and keep mapping approval separate from operational evidence. Regenerate the remaining 13 batches without approving alternatives; preserve recorded decisions only while their inspected contracts match.

- Replace 13 proposed SOC 2 governance links that relied on a CMMC system security plan with scoped, requirement-specific assessment contracts. Normalize spaced Cisco identifiers before deduplication so explicit CC1.3 and A1.3 references are retained without accepting cross-line or malformed IDs. Pin supporting Cisco references, require distinct evidence types, and regenerate the 17 SOC 2/ISO review batches. The mapping repairs themselves preserved earlier approvals and granted no additional review credit.

## 0.3.5 - 2026-10-15

- Replace 28 weak proposed SOC 2 and ISO mapping relationships with 22 requirement-specific assessment contracts. Prepare 17 review batches covering 150 requirements and 185 candidate relationships, with pinned Cisco/Oracle implementation references, operating contracts, review fingerprints and blank decisions. Preserve earlier approved contracts and coverage totals; these new proposals grant no review or operating-effectiveness credit.

- Record maintainer approval of 33 source-review batches with per-mapping inspected digests. Mapped coverage is 1,803/2,252 (80.1%); reviewed coverage is 1,128/2,252 (50.1%). Stale version pins remain uncredited, source-less alternatives remain proposed, and mapping review does not establish operating effectiveness.

- Bind console mapping decisions to the inspected definition and latest decision, rejecting stale batches atomically. Show the safeguard operating and evidence requirements alongside each review. Export deterministic, bounded human-review packets with distinct-requirement milestone counts, source gaps and blank decisions; preparation grants no review credit.

- Bound concurrent investigation graph builds per server process (`GRC_LAKE_GRAPH_BUILD_CONCURRENCY`, default 4). Excess requests return 503 with Retry-After instead of queueing. Builds stop at the next checkpoint after a client disconnect or a configurable deadline (`GRC_LAKE_GRAPH_BUILD_TIMEOUT_SECONDS`, default 60) and never return a partial graph; the slot is released once the build thread stops.

- Add five NIST CSF 2.0 mappings for evaluation and operational improvement, recovery initiation, post-incident operating norms, and recovery completion, plus 381 source-native NIST 800-53 assessment safeguards. Each has a distinct assessment contract; their mapping approvals are included in the maintainer decision above. All 106 CSF outcomes now have a catalog mapping. Catalog coverage does not establish assessment or compliance.

- Exclude ambiguous safeguard identities and repeated requirement mappings from coverage totals and OSCAL component exports. Preserve raw records for repair and keep valid sibling mappings eligible; conflicting rows cannot earn review credit by selecting the most favorable entry.

- Align OSCAL component exports with the coverage catalog: unknown requirements and conflicting framework identities cannot become implemented requirements. Legacy mappings without a framework inherit their catalog target's framework; valid sibling mappings remain exportable.

- Preserve evaluated control status and risk in graph projections and cache invalidation. Share evidence outcome labels across both graph views and the inspector; unevaluated safeguards remain neutral. Clarify linked-record counts versus records with outcomes and distinguish catalog mapping lists from visible paths.

- Align access-review, detection-alert and dependency-finding evidence names with control requirements. Add explicit synthetic golden-demo records for distinct missing requirements, while preserving deliberate stale timestamps and adverse outcomes. Verify required evidence types against each control's records and the evaluated pipeline.

- Group safeguard mappings by framework with complete counts and five-control pages. Keep curved links clear of labels, highlight connected paths on hover or selection, preserve dragged positions within the current view, and prevent overlapping cards. Collapse starting-point options, provide live search, disable wheel zoom, and clarify investigation versus catalog/repository map purposes.

- Reject duplicate safeguard and mapping identities, empty or non-string identifiers, and in-scope framework mismatches before CCF assessment. A rejected run keeps the previous active generation. Catalog mappings and review approvals are unchanged.

- Reject duplicate and malformed source mapping records, and validate each target against the catalog. The coverage ledger, crosswalk and framework detail share one target-and-citation check, so a wrong-framework citation earns no credit in any view. Catalog totals are unchanged.

## 0.3.4 - 2026-10-13

- Add authorized, durable public GitHub URL onboarding with bounded, commit-pinned collection and scoped investigation links. Simplify setup, show repository evidence in paged directional lanes with explicit relationship types, and preserve exact normalized record bindings without duplicating connector-scoped evidence. Public observations remain distinct from authenticated governance and compliance verdicts.

- Reject incomplete connector collections: paginate GitHub and GitLab access lists and S3 bucket inventory; bound Kubernetes continuation; reject repeated pages/cursors, malformed list rows, and premature empty pages in affected adapters. Repository sync fails after exhausted transient HTTP errors instead of recording a permission gap. Add a generated built-in connector qualification matrix with test pointers, historical scope, catalog permissions and explicit ownership gaps; fixture coverage does not assert current-release live parity.

- Add a reproducible synthetic access/change qualification matrix with explicit expected outcomes, retained draft workpapers, input hashes, tenant rejection, replay and tamper checks. CI retains reports and review bundles; passing this matrix does not establish live-provider qualification or mapping approval.

- Put installation before the README product tour, clarify the sample evidence-to-export workflow, separate human mapping review from demo inspection, and align package and tutorial repository links with the current organization.

- Remove KnowBe4 fallback to deprecated page parameters. Reject missing, repeated or malformed continuation and overlapping records instead of returning incomplete evidence. Add a cursor-only, data-minimized qualification command; live next-cursor verification with more than 500 records remains outstanding.

- Require unique, catalog-backed mapping review targets. Reject ambiguous family identities, bind coverage source citations to catalog identities, and exclude invalid targets from mapping coverage.

- Consolidate dependency updates and qualify installed packages on Python 3.14. Add bounded graph and authenticated HTTP capacity probes with retained failure receipts; synthetic measurements do not establish production capacity.

## 0.3.3 - 2026-10-12

- Route evaluation and snapshot execution through shared assessment services. Persist versioned, tenant-scoped operation receipts so authorized callers can inspect a committed result after a lost worker response. Large responses preserve their execution status; generation conflicts and uncertain outcomes remain explicit.

- Bound operation pagination, queue admission, retained results and collector retries. Detect repeated provider cursors, honor Retry-After without retrying early, use Redis server time for shared rate limits, and return sanitized errors when admission or storage is unavailable.

- Add bounded, read-only distributed recovery inspection and cooperative write-lease checks. Qualify coordinated PostgreSQL/object backup restoration into fresh stores, including corruption rejection, snapshot chains, retained operation receipts and tenant isolation. This synthetic single-host drill does not establish production RPO/RTO, failover or capacity.

- Replace evidence-type graph fanout with exact, source-account-scoped record bindings. Add bounded CCF, environment, repository, finding, source and explicit vendor relationships, plus paginated roots and version-checked navigation. Evidence node IDs now identify records; old type-only links must be refreshed.
- Add an expanded icon-led graph workspace with continuous directional connections, drill-down, parent roll-up, and readable adjacent details. Redesign shared connector setup around configuration, access testing, first sync and results; clarify findings and pending access-review decisions.
- Show repository evidence outcomes and linked control impact, keep unobservable public settings distinct from failures, and show AI models, evidence gaps, linked controls and next steps alongside current framework coverage. Preserve the approved logo corners without CSS clipping.
- Store explicit vendor asset references with migration 0031. Refresh the investigation guide, product screenshots, coverage boundaries and contribution roadmap.

- Preserve evidence eligibility across freshness, control tests and workpapers: observed inventory cannot refresh a stale verdict, and unavailable evidence cannot supply design or sample credit. Correct order-dependent CCF ambiguity totals.
- Bind organization mapping approvals to safeguard semantics, mapping and requirement definitions; preserve stale review history and adverse decisions. Tighten catalog publication validation.
- Add versioned, tenant-scoped safeguard implementations and independently reviewed governance decisions, including expiring risk acceptance and extensions. These records never override assessment verdicts. Database migration 0030 adds their history tables; export them before a downgrade.
- Add source-account identity to normalization v5, compact CCF pages and separately paged references in projection v2, plus input and relation admission budgets. Document deployment limits and model relationships.

- Reuse shared framework marks in AI governance and mapping review, and shared control-family icons in the graph. Point console documentation links at the current repository.

- Pin the Compose quick start to published release templates. Refresh the candidate tour, AI-governance and mobile screenshots, navigation map, and coverage-depth boundaries.

- Gate container publication on dependency scans and authenticated runtime qualification for both AMD64 and ARM64, and make PyPI wait for the image job so a failed container check cannot leave an immutable Python release published first. Require the latest main-push CI run to pass; an older green run or a PR-only run no longer authorizes a tag.

- Replace the G-and-waves logo with a shared layered-evidence mark across the console, favicon, MCP icon, README and social preview. Enlarge the README banner and regenerate the synthetic console screenshots.

- Security: refresh the container's liblzma package for DSA-6549-1, remove pip and ensurepip from both runtime Python environments, remove the unused vulnerable infocmp executable, and remove setuid/setgid bits from system utilities. CI and release builds now reject fixable MEDIUM findings as well as HIGH and CRITICAL findings. Unfixed distribution findings remain tracked; this does not certify a vulnerability-free image.

- Security: reject incoming SAML signatures and digests that use deprecated algorithms, including SHA-1. Previously, selecting SHA-256 for outgoing signatures did not reject SHA-1 assertions from the IdP. Configure the IdP to use RSA-SHA256 and SHA-256 or stronger before upgrading.

- Security: sign browser-session, OIDC-state and SAML-correlation cookies with SHA-256 and require at least 32 bytes for signing secrets in authenticated deployments. Existing browser sessions must sign in again after upgrading; replace short secrets before starting the new server.

- Split GRC workflow routes out of the server application factory while preserving route behavior. Update LangGraph, web dependencies and the pinned cache action. Keep the Node build image on a current digest of supported Node 22 LTS, aligned with console CI; Node major upgrades require an explicit coordinated change.

- Refresh README setup instructions and synthetic console screenshots. Correct package visibility and release-status guidance; the published 0.3.2 image remains available while 0.3.3 is qualified.

## 0.3.2 - 2026-10-10

- Prepare package, console, chart, Compose and deployment examples for 0.3.2. New images target `ghcr.io/koda-ai-studio/grc-lake`; historical 0.3.1 images remain under `ghcr.io/msaad00/grc-lake`. Candidate references become usable only after publication.

- Preserve synthetic fixture origin through collection and invalidate stale or cyclic inherited CCF mapping reviews. Tighten Helm startup and distributed availability behavior and refresh pinned dependencies and security gates.

- Add bounded ClusterFuzzLite coverage for strict JSON, raw evidence, AI-BOM imports and webhook signatures. Reject malformed signature text without exceptions and tolerate malformed optional AI-BOM fields; replay minimized regressions in the unit suite.

- Correct personnel-screening, breach-notification, and broad PCI CCF mappings; use official ISO Annex A titles, label top-level coverage, and attribute proposed catalog rows to source reconciliation with legacy-field reads.

- Stream atomic gold JSON writes and bound dashboard detail with explicit totals. Cold posture uses a source-hash-bound asset projection, with a streaming fallback for legacy lakes.

- Use native NIST OSCAL catalog/profile references, return a JSON-RPC error for unknown MCP tools, and return 404 for unknown legacy evidence IDs. Clarify console mapping labels and guard batched Sidebar toggles.

- The Helm chart refuses to render without authentication. Set `GRC_LAKE_COOKIE_SIGNING_KEY` (and `GRC_LAKE_SESSION_SECRET` for OIDC) through `env[]`, or acknowledge a local-only insecure install. The container is now named `grc-lake`, so update `kubectl logs -c` and similar selectors, and the writable home volume mounts at `/home/grc-lake`.

- The EKS reference keeps the cluster API endpoint private unless `cluster_endpoint_public_access_cidrs` names the networks allowed to reach it. Open-world CIDRs are rejected. Existing clusters become private on their next apply unless the variable is set.

- Connector plugins register under the `grc_lake.connectors` and `grc_lake.connector_catalog` entry-point groups. The `trustops.*` groups still load; when both define a name, the `grc_lake` entry wins.

- Webhook deliveries add `X-GRC-Lake-Timestamp` and `X-GRC-Lake-Timestamp-Signature` so receivers can reject replays. Existing signature headers are unchanged.

- SPDX 3.0.1 and CycloneDX AI-BOM exports validate against the official schemas. `grc-lake query` accepts `WITH` queries and opens both marts read-only.

- Add a disposable authenticated image probe for API-key authorization, tenant isolation, revocation, snapshot integrity, and persistence after container recreation. Document publisher and provenance verification across the repository ownership transfer while retaining working historical image references. Allow the exact repository-owner identifier in technical copy without allowing retired product names or visual wordmarks.

## 0.3.1 - 2026-10-09

- Bulk-load the DuckDB mart through typed Arrow tables when available, with a staged NDJSON fallback. Preserve table schemas, views, row contents, and order. Strict JSON decoding avoids unnecessary depth and Unicode scans while retaining duplicate-key, finite-number, Unicode, and nesting checks.

- Cache posture, violations, graph, coverage, and file-derived ingestion status per tenant lake and input version. Posture refreshes at evidence freshness boundaries. JSONL collection pages validate each file version and then seek directly to the requested rows. Callers receive independent results. Distributed request scratch directories remain isolated; reuse across those requests is limited.

- Refresh the README screenshots from the golden demo, correct the hero markup, and document local versus distributed deployment topology. Update the upgrade guide to reflect the published GRC Lake package and image.

## 0.3.0 - 2026-10-09

- Rebrand the product, CLI, SDK, console, logo, repository links and deployment examples to GRC Lake. Legacy CLI commands, Python imports and runtime environment variables remain supported. See [upgrade instructions](docs/REBRANDING.md) before changing package or deployment names. The release targets the new `grc-lake` distribution and image; existing TrustOps releases remain under their original registry names.

- Add opt-in distributed mode backed by PostgreSQL and S3-compatible object storage. API replicas use independent scratch storage, concurrent tenants publish through database-clock writer fences, and readers see only committed, hash-verified evidence. PostgreSQL holds operational state; the existing local deployment mode remains supported.

- Add stable virtual worker shards, tenant/source/UTC-date Parquet partitions, 32 physical PostgreSQL history partitions, bounded tenant job dispatch, and query indexes. Workers claim independently across tenants, respect cancellation races, and use database time for lease renewal and recovery. These partitions remain within one PostgreSQL cluster; storage replication and RAID are deployment-infrastructure responsibilities.

- Qualify concurrent replicas and worker recovery against a real S3-compatible service in CI, including conditional and multipart writes, replica scratch loss, PostgreSQL/S3 outages, and killed-writer fencing. This is a single-host synthetic qualification, not a production capacity or storage-replication certification.

- Preserve neighboring artifacts during failed downloads by using uniquely owned temporary files. Migration rollback refuses custom security policies on child partitions instead of silently discarding them.

- Let the distributed qualification wait up to 90 seconds for evidence reads after a storage restart. Bucket readiness can precede data availability; unavailable reads are retried within that bound, while changed publication versions or evidence hashes fail immediately.

- `frameworks sync` marks each fetch error `transient` when the upstream is temporarily unavailable (HTTP 403, 429, or 5xx, or a network failure). `python -m security_lakehouse.framework_sync report` emits a GitHub `::warning::` for those and exits 0, but emits `::error::` and exits 1 for any other fetch error, such as a 404, an invalid URL, or a registry entry with no source, so a broken source entry no longer passes silently.

- Shorten the PyPI package description to what the package does: read-only evidence collection, deterministic control tests, and reproducible assessment exports via API, CLI, and MCP. It no longer lists framework names or claims audit-ready proof.

- Audit readiness no longer counts a control with evidence but no verdict as assessed. Each framework's `assessed_controls` now excludes not-evaluated controls, so the coverage gate and the Overview agree (golden ISO 27001 reports 0 assessed, not 1). A new `observed_controls` field keeps the raw count.

- `fixtures load --company golden` now also seeds a small set of synthetic records for the local no-auth demo: four remediation tasks linked to findings the golden pipeline opened (one overdue), four risks, a published access-control policy, two vendor assessments, and a live metrics capture plus two earlier points so the Insights trends draw. Records are marked synthetic, re-running the load adds nothing, lake files and assessment hashes are untouched, and nothing is written when `GRC_LAKE_DATABASE_URL` points at an external database. `--no-demo-records` skips it. `make demo-local` and `docker compose up` pick this up through the same command.

- Console score and count labels now say what they measure. The Overview's assessment score is marked as the headline score with an info tooltip. Audit room shows the "Audit readiness index" and "Evaluated frameworks ready" (for example "0 of 3", naming the frameworks) as sub-indicators. AI governance shows the "AI governance indicator" with its formula in a tooltip, and each AI framework card is one line ("4 of 72 controls assessed · 3 failing") with the full breakdown in a tooltip. Frameworks counts requirements and Mapping review counts mappings, and each page now says so. An empty decision log reads "No org decisions logged yet" instead of "verified · 0". Insights says "findings", control results say "evidence confidence" and show its inputs on hover, and the local demo avatar is an icon. The onboarding card explains why a fixture-loaded demo shows 0% setup readiness.

- Console consistency pass. Below 640px, the Findings, Evidence, and Controls tables render each row as a card (title, severity or status chips, labelled metadata), and their filters fold behind one "Filters" toggle; desktop tables are unchanged. KPI tiles use one component everywhere (Insights and Graph included), empty lists share one empty state, Onboarding uses the standard page width, and the Frameworks safeguard section uses the collapsible card. The Graph opens on one fitted control path with "Show whole framework" one click away, labels counts as "in view" versus catalog totals, and shows a one-line summary on phones so the canvas is on the first screen. Workflows auto-arrange left to right with step edges between fixed left and right handles. The sidebar fits at 1440x900, keeps the current page scrolled into view, and fades the edge with hidden links. Logos at 40px and below draw the waves only. Charts, the graph, workflow nodes, tag chips, and the sign-in page use theme tokens in both themes, and chart tooltips no longer render as a white box in dark mode. Sign-in, invite, and shared trust pages have a `<main>` landmark and an `<h1>`, the Workflows sidebars have unique labels, and the axe end-to-end test now covers every route with the full WCAG 2.1 AA and best-practice rule set. Product copy no longer compares GRC Lake with other products.

- Add `GET /api/v1/platform/features` (`read` scope), which reports whether plan usage, billing, and SCIM are enabled. The console checks it once and skips routes that would return 501, so the Access & keys page no longer logs failed requests on a self-hosted server. Servers without this route fall back to the previous behavior of hiding panels on 501.

- Wrap MCP tool error text in the same untrusted-content envelope as results, since errors can echo API details or caller arguments. Errors still return `isError: true`.

- Validate an unchanged evidence file with one `stat` instead of re-reading and hashing it on every unfiltered `/api/v1/evidence` page. Files changed in the last two seconds are still hashed, so same-size rewrites are detected.

- Retry operation lease renewal on transient database errors such as SQLite `database is locked`, with short backoff, instead of stopping the job. A job is interrupted with `lease_renewal_failed` only when renewal can no longer succeed before its lease expires. Recording a job's result or interruption also retries such errors for up to 10 seconds before leaving the job to lease-expiry recovery.

- Bound unparameterized `/api/v1/graph` and `/api/v1/repo-graph` responses. Without `limit`, `offset`, or `cursor` they now serve the first page of 100 nodes and 100 edges, marked `meta.default_page: true`, with `meta.next_cursor` for the rest. The console graph page follows the cursor at 1000 rows per page, and the MCP `get_repository_graph` tool takes `limit` (1-100, default 100) and `offset` and reports `pagination.next_offset`.

- KnowBe4 (`knowbe4-training`, preview) now uses cursor pagination (`cursor=0`, `per_page=500`) because KnowBe4 deprecates the `page` parameter in November 2026. KnowBe4's spec does not yet say where the next cursor is returned. The client follows a `cursor` carried in a `Link: rel="next"` header and always sends requests to the configured regional host. If a full page arrives with no next cursor, it falls back to `page` paging from page 1. If KnowBe4 ignores `page` or repeats a cursor, the sync fails with a clear error and stores no duplicate rows. A 429 that outlasts the backoff budget now fails as "rate limit reached, retry the sync later" instead of a generic error.

- Security: the audit log no longer returns connector credential values to any role. Each credentials field keeps its name with a `***` marker. `apikey`, `authorization`, and `passphrase` fields are now redacted at rest like `token` and `password`. Connector configuration rejects URLs that embed `user:password@` with a 400.

- Security: escape snapshot reason, organization name, timestamps, bundle ID, and hash in the executive PDF. Markup in a snapshot reason could fail the export, make the renderer open a local file, or embed a `javascript:` link.

- Security: look up API keys and browser sessions by a keyed SHA-256 digest instead of 210,000 PBKDF2 iterations per request. Unknown or malformed tokens are rejected without the KDF, which removes an unauthenticated CPU exhaustion path. The tokens carry 192 or more random bits.

- Security: for state-changing `/api` requests authenticated by the session cookie, and for `POST /api/v1/auth/session-from-key`, require `Content-Type: application/json`. Refuse an `Origin` that matches neither the request host nor `TRUSTOPS_PUBLIC_URL`. Bearer-token requests and the SAML ACS post are unaffected.

- Security: OIDC auto-provisioning admits only verified emails whose domain is listed in the new `TRUSTOPS_OIDC_ALLOWED_DOMAINS` (comma-separated, exact match).

- Security: SSRF validation rejects percent-encoded hostnames. The tenant-facing Iceberg REST catalog connects only to an address validated as public for each connection, which closes a DNS-rebinding window. The operator CLI export is unchanged.

- Security: console and public trust pages send a Content-Security-Policy. Authenticated API JSON responses send `Cache-Control: no-store`.

- Helm pods no longer mount a Kubernetes API token. Set `serviceAccount.automountToken: true` only for CLI runs of the Kubernetes connector with `in_cluster: true`. The framework-sync workflow no longer persists its checkout token.

### Upgrade notes

- For distributed mode, configure PostgreSQL and an S3-compatible bucket explicitly; local mode does not migrate itself. Follow [distributed deployment](docs/DISTRIBUTED.md) for import, shard placement, provider preflight, and recovery. Back up PostgreSQL and quiesce writers before migration `0029_distributed_scaling`, which takes an exclusive lock and temporarily requires a second copy of retained manifest history.

- Migration `0027_api_key_hash_version` adds `api_keys.hash_version`. Existing keys keep working: each one is rehashed to the new digest on its first successful use, and existing browser sessions are upgraded the same way. Once a key has been rehashed, downgrading below this release orphans it. The downgrade refuses while any rehashed key exists, so reissue keys if you must roll back.

- If `TRUSTOPS_OIDC_AUTO_PROVISION=true`, set `TRUSTOPS_OIDC_ALLOWED_DOMAINS`, for example `example.com`. If it is unset, no new SSO user is provisioned and the server logs an error at startup. Users who already exist still sign in. The documented POC values and compose example now set it.

- Custom browser or script clients that mutate the API with the session cookie must send `Content-Type: application/json`, including for empty bodies such as `POST /api/v1/auth/logout`. They must also run from the same origin as the server or from `TRUSTOPS_PUBLIC_URL`; other requests receive 415 or 403. The console already does both. API-key clients are unaffected.

- A saved connector configuration whose URL embeds credentials must be re-saved without them. Supply the secret through a credential field or a secret reference.

- API clients that read `/api/v1/graph` or `/api/v1/repo-graph` without paging parameters receive at most 100 nodes and 100 edges per response. Follow `meta.next_cursor` until it is `null` and concatenate `nodes` and `edges`, or check `meta.parts.nodes.count` and `meta.parts.edges.count` for the totals. The legacy `/api/graph` and `/api/repo-graph` routes are unchanged.

- MCP agents calling `get_repository_graph` get one page; read `pagination.has_more` and pass `pagination.next_offset` as `offset` to continue.

## 0.2.24 - 2026-10-07

- Run retention automatically from the scheduler when `TRUSTOPS_RETENTION_SCHEDULE` is set. It is off by default, and only previews candidates until `TRUSTOPS_RETENTION_ARCHIVE_DIR` names an archive outside the lake root. Scheduled runs use the CLI's protections, record each run in `gold/retention_runs.jsonl`, and expose the settings under Helm `scheduler.retention`.

- Run background operations on a bounded worker pool (`TRUSTOPS_OPERATION_WORKERS`, default 2, range 1-16) with at most one in-flight job per tenant per replica, so one tenant's long job no longer blocks others.

- Cap every MCP tool output, including write tools, with an explicit `mcp_truncation` marker instead of an error. Tool annotations now report read-only, destructive, idempotent, and open-world behavior per tool. Text shown to the model wraps free-text values in an untrusted-content envelope; `structuredContent` keeps exact values.

- Page `/api/v1/graph`, `/api/v1/repo-graph`, `/api/v1/graph/coverage`, and `/api/v1/frameworks/coverage` with the standard `limit`/`offset`/`cursor` contract when paging parameters are sent. Evidence pages stream instead of loading every row, and graph ordering no longer depends on the Python hash seed.

- Keep a revoked trust share revoked when a copy of its record still sits in another lake the owner can reach, such as a flat root copied into a scoped tenant directory. List copied shares once.

- Report duplicate control IDs during catalog validation, and guard ISO 42001 Annex A controls against colliding with management clause IDs.

### Upgrade notes

- Since 0.2.23, trust shares stored in a flat root lake resolve publicly only while no server tenant exists or after one tenant owns that lake. In a deployment with several tenants and no recorded flat-lake owner, CLI-issued links stored in the flat root return 404. Reissue them from the tenant that should own them.

- After scheduled retention runs, releases before 0.2.24 reject the new `retention` rows in `gold/scheduler_state.jsonl` and stop scheduling. Do not downgrade below 0.2.24 once retention is enabled.

- In-process callers of the MCP server's `FastMCP.call_tool` now receive a `CallToolResult`; read `structuredContent` for the previous dict. Remote MCP clients are unaffected.

## 0.2.23 - 2026-10-07

- Keep legacy flat-lake shares visible and revocable by their original tenant after a scoped tenant directory is created. Reject public access to ambiguous tenant-managed flat-root shares without an established owner, and add mutation-verified coverage for snapshot payload/ledger predecessor mismatches.

- Prevent braces stack exhaustion in console build tooling with an exact, provenance-verified depth-guard replacement. Check transitive parser behavior in CI and block high-severity development dependency advisories alongside production advisories.

## 0.2.22 - 2026-10-07

- Update the locked Mako dependency to 1.4.3, resolving its Windows template-lookup path traversal advisory.

- Align self-hosted deployment examples with runtime authentication, require cookie signing configuration in hosted Helm profiles, and launch scheduler CronJobs through the container's CLI executable. Refresh the EKS reference version, add staged infrastructure bootstrap and operator Helm values, and cover deployment plans and chart-to-server startup in CI.

## 0.2.21 - 2026-10-07

- Harden evidence verdicts, human approval authority, tenant isolation, recovery, background operations, and portable reports.

### Added

- Supporting and inherited mapping relationships remain visible without coverage credit or OSCAL implementation claims.
- Evidence-bound N/A, inherited, and compensating assessment context in period workpapers, preserved through independent human review without changing machine verdicts.

- Durable tenant-scoped background operations for console and remote MCP evaluation, connector sync, scheduler ticks, and snapshots, with idempotent acceptance and explicit interrupted-work recovery.

### Fixed

- Reject symlinked audit-source parents during retention, make cancellation atomic with claims, and enforce isolated native-code deadlines in the operating system.
- Revalidate current CMMC source evidence before SPRS credit or POA&M closure, and bind catalog discovery to the imported installation.
- Render portable dashboard reports directly from frozen data, with offline browser support, exact embedded JSON, safe evidence markup, and explicit coverage.

- Share current credential authority across HTTP, queued work, and live streams;
  reject inconsistent tenant or source-key bindings and reconnect streams when
  persistent authority changes.
- Share tenant-aware framework mapping coverage across CCF, Frameworks, and AI Governance, keeping contextual relationships separate from reviewed implementation mappings.
- Require sufficient current catalog coverage before reporting AI governance as governed; retain the composite score formula and reject non-catalog control IDs as passing coverage.

- Align catalog/program evidence requirements and current AI/CCF summaries, preserve observation-only uncertainty, and compare evidence timestamps as instants.
- Preserve explicit imported control mappings, require positive Jira resolutions, retain unresolved Azure role uncertainty, and detect unsafe added Kubernetes capabilities.

- Make assessment scores a versioned percentage of fresh passing controls, so new failures cannot improve them and passing severity cannot increase control risk.
- Preserve remediation authority across owner changes, serialize access-review decisions and terminal campaigns, and revalidate queued session authority.
- Reconcile interrupted workflow claims without replay, preserve review evidence during rollback, and repair SQLite acknowledgment defaults.
- Reject unlisted generation files, unsafe workpaper recovery, forged export metadata, and missing-lake verification; preserve recovery provenance and compare timestamp instants across read projections.
- Bound MCP assurance pages, advertise mode-appropriate tools, keep human attestations out of API-key MCP, and return bootstrap API credentials once.

- Share rule-aware verdict evaluation between controls and CCF safeguards, preserve source-tenant freshness boundaries, and reject bronze pointers as proof of available source evidence.
- Keep excluded or unknown MFA populations out of passing coverage, and classify GCP organization policies by their relevant constraint and explicit unconditional enforcement.

- Resolve catalogs from the active user-installed wheel and add explicit, resumable quarantine of interrupted snapshot files without rewriting committed history.

- Accept normalized passing evidence in workpapers, preserve open POA&M items when evidence is unknown, reopen completed items on regression, and suppress readiness scores when framework coverage is insufficient.

- Reject every unauthenticated production-server entry point, require authenticated sessions for human mapping review, and restore tenant-scoped snapshot integrity reads.

- Stream bronze and silver integrity verification instead of retaining full evidence payloads, preserving hash linkage, duplicate detection, counts, and evidence-set digests.

- Remove an unused framework-score assignment flagged by CodeQL; retain control-risk scoring for capped and uncapped assessments.

- Patch the console build selector parser through scoped overrides while preserving generated CSS; retain the separate unpatched braces advisory in dependency security documentation.

- Restore the README distinction between assessing an existing evidence lake and collecting new evidence through connectors.

- Preserve flat-lake ownership and share revocation as tenants are added, isolate request audits, and enforce server-side auditor view scopes.
- Bound graph detail, index connector history, coalesce stream computation, and cache unchanged catalogs. Add verified generation archival with snapshot and reader protection.
- Carry control input digests and event-level OSCAL lineage, validate query filters, harden MCP schemas and tool authority, and correct packaged skills and AWS permissions.
- Clarify console permissions and approval eligibility, improve responsive overview and freshness detail, respect system theme, and refresh the concise README and synthetic demo screens.

- Preserve historical snapshot and workpaper recovery without rewriting recorded hashes, support independently retained integrity checkpoints, and reject malformed generation and integrity manifests.
- Keep scores consistent when finding details are capped; distinguish missing provider evidence, avoid duplicate control counts, and report incomplete connector pagination and unavailable factor reads explicitly.
- Pin mapping approvals to reviewed control versions, support explicit safeguard bindings, label the NIST 800-53B Moderate pack accurately, and reopen remediation tasks when published evidence regresses.
- Carry normalized v4 evidence availability through Parquet and Iceberg exports while preserving source account identities and generation tenant isolation.

- Correct ten SOC 2 criterion topics from the AICPA source manifest and regenerate catalog metadata without changing mapping review decisions.
- Require human SSO for exception approvals, remediation retests, access decisions, policy acknowledgments, and workflow gates. Reject self-verification and linked-task dismissal without an evidence retest.
- Keep the scheduler daemon alive after tick errors, fsync connector history, bound CronJob retries, and provide explicit runtime-tail recovery with preserved originals and deferred scheduling. Reject evidence timestamps that overflow UTC or freshness arithmetic.
- Report incomplete SPRS assessments without a numeric score, count only explicit current passes in metrics, bind share issuers to authenticated identities, and enforce framework scope with observed-versus-catalog coverage counts.

- Avoid repeated snapshot decoding and canonical hashing on unchanged history, allow concurrent verified readers, and decode only requested trend payloads after verification while retaining whole-chain tamper detection.

- Record failed agent decisions without blocking other proposals, and let independent SSO reviewers close abandoned execution claims without replaying side effects or racing a live worker.

- Route remote MCP reads and writes through authenticated APIs, reject incomplete remote configuration and credential-bearing redirects, and support explicitly configured private API destinations.

- Preserve evaluated control verdicts when activity observations are also present, while retaining unknown, observation-only, failure, and stale states. Incremental evaluation refreshes existing verdicts without rewriting historical generations.
- Accept changed connector records at the same source timestamp when their collection is newer, preventing alert status updates from blocking later syncs. Older redelivery cannot overwrite the newer collection; conflicting ties on both timestamps still fail without changing the store.
- Keep inventory observations unevaluated, respect configured failure thresholds, and include declared eligible assets without period evidence in workpaper sampling gaps.
- Keep declared workpaper assets in sampling even when evidence is missing or unbound; exclude only a known incompatible asset type established by the cutoff, preserving account isolation and earlier exports.
- Retain failed login attempts as observations, preserve GCP IAM conditions, and identify broad/public access grants and open repository alert severity.
- Reconcile missing HIPAA workstation, media, authentication, policy and documentation identities against eCFR, preserving historical catalog scope and proposed mapping review.
- Persist scheduler attempts before execution so failed or interrupted workflows, connector syncs, and lake evaluations respect their configured interval; reject corrupt scheduler state without discarding retry history.
- Read and index connector history once per status request, retain successful runs beyond the recent-history window, and reject malformed history instead of silently discarding it.
- Schedule registered tenant lakes in hosted root ticks with isolated state, locks, execution identity, and webhook attribution; authenticated Helm deployments now use explicit all-tenant scheduling.

- Atomically claim agent decisions across SQLite/PostgreSQL before execution, require independent SSO review, and retain interrupted claims for reconciliation. The console now reflects review eligibility and in-progress decisions.
- Preserve connector-local event identities through upsert, normalization, incremental evaluation, and lineage; reject conflicting equal-time observations and retain newer evidence on stale redelivery.
- Preserve UTC instants in DuckDB marts and sinks independently of connection timezone.
- Verify live assessment generations and ledger-backed snapshot history before export; detect changed normalized evidence and require workpaper HTML to match its JSON. Reject unexpected export files and symlinks.

- Retain API-key provenance in exchanged sessions, revoke derived access with the key, and reserve independent workpaper and mapping review for eligible SSO identities. Key issuance cannot impersonate another user.
- Claim workflow decisions durably before execution, bind them to reviewed content, and reject replay or retry of interrupted approvals.

- Reject ambiguous or non-standard JSON before API, CLI/MCP dispatch, and shared lake writes; validate evidence shapes and timezone-qualified timestamps consistently with packaged schemas.
- Serve dispatched API routes in live OpenAPI and fail explicitly on corrupt stored share records without rewriting evidence.
- Evaluate current freshness per source, asset, and evidence type so retained history cannot permanently stale a control. Compare timestamp instants in UTC and prevent future collection times from establishing freshness.

- Portable PostgreSQL Boolean migration defaults and migration/model index parity, with real PostgreSQL upgrade/downgrade and existing-data checks.
- Preserve percent-encoded database credentials and query parameters through Alembic configuration so migrations and server startup accept those connection URLs.
- Installed cloud-link templates and evidence schemas now ship as importable package resources; CI checks them against canonical sources.

- Export reproducible auditor workpapers with scoped citations, separate control and population conclusions, retained remediation receipts, and independent authenticated review. Add a synthetic walkthrough and artifact capture.

- Reconcile declared asset populations with sealed evidence, bounded gap details, freshness and collection-receipt checks, and explicit limits on inventory-completeness claims.

- Add reproducible CCF control test plans with separate design documentation, period samples, deviations, and explicit pending human review. Include five synthetic walkthrough controls.

- Require independent, authenticated, expiring exception approvals and fresh sealed-evidence verification before resolving control-linked remediation. Retain verification receipts and migrate legacy approvals to pending.

- Add `security-lakehouse --version` and `assessment status --format summary`, retaining JSON by default and showing unevaluated controls and full assessment totals.

- Exercise the built image through the Compose quickstart in CI, including readiness, golden posture, and volume persistence without reseeding after container recreation.

## 0.2.20 - 2026-10-03

- Package every framework source manifest and reject wheels with missing pack data, fixing installed demo and evaluation failures.

- Add dependency-aware deployment readiness, refresh the README product tour and demo screenshots, and align release artifacts.

- Read CCF summaries and asset pages from indexed, generation-pinned SQLite projections; preserve query semantics and fail closed on broken indexes.
- Refresh DuckDB sink tables atomically, remove obsolete rows, and reject cross-lake destination reuse; existing unowned destinations require a new database.
- Bind hosted assessments to the authenticated platform tenant and block ambient warehouse exports from tenant requests.

- Update urllib3, PyJWT, oauthlib, virtualenv, and brace-expansion to address dependency advisories.

- Preserve unknown evidence outcomes, refresh incremental assessments at freshness boundaries, and pin historical OSCAL findings to verified snapshot inputs.
- Publish explicit safeguard-to-asset evaluation and reviewed requirement rollups through the API, CLI, MCP, and Frameworks page, with observed-population limits.
- Reuse connector discovery across control tests, consolidate framework scoring and evaluation result serialization, and distinguish local publication from warehouse export failures.
- Reject unsupported Helm read replicas and multiple writers regardless of volume access mode; document current deployment and evaluation limits.

- CI type-checks the package with mypy (`make typecheck`).
- Workflow `action.connector_sync` no longer fails with an AttributeError
  after a successful sync.
- Snowflake and Databricks asset-risk rows with no status and a missing or
  non-numeric risk score are recorded as observed instead of failing the sync.
- An OpenAI-compatible model response whose first choice has no message is
  reported as a model error instead of an AttributeError.
- Posture gate fails closed: when an allowlist of failing controls is set and
  the control-tests request fails, the gate now fails instead of reporting zero
  failing tests, and failing tests beyond the fetched page count as unexpected
  instead of being dropped. Empty lists no longer crash on macOS bash 3.2.
- Hosted cloud linking: the console's Azure and GCP link forms collect the
  tenant's own app registration (tenant ID, client ID, and one secret,
  certificate, or federated token file reference) or service account to
  impersonate, validated in the browser and on the server with the readers'
  rules. Reference fields take env-var names only and show the tenant's
  `TRUSTOPS_TENANT_<ID>__` prefix, and connector form placeholders use it in
  hosted mode. `GET /api/v1/auth/whoami` reports `hosted` and
  `secret_ref_prefix`.
- The Azure admin-consent callback no longer copies the tenant it reports into
  connector options, and hosted mode offers no consent URL for an
  operator-owned multi-tenant app.
- Test reliability: the API rate-limit tests run on a frozen clock, and the
  connector registry tests restore process-global state and ignore connectors
  from installed packages.
- Framework packs: NIST SP 800-171 Rev 3 (all 97 requirements from NIST's
  OSCAL catalog, each with its Rev 2 predecessors from NIST's change
  analysis), EU NIS2 (Article 21(2)(a)-(j) measures and Article 23
  reporting) and EU DORA (99 financial-entity obligations across Articles
  5-30 and 45). Sources are pinned by sha256; every new CCF mapping is
  proposed, and requirements without an honest safeguard home are listed.
  CMMC 2.0 Level 2 stays on Rev 2.
- EU AI Act: `EU-AI-ACT-Art.49` carried the fundamental rights impact
  assessment title, which is Article 27. It is now "Registration" (version
  1.1.0; the old version stays in history), its risk-assessment mapping moved
  to the AI governance safeguard, and Article 27 is added.
- AI governance: 16 new life-cycle safeguards (evaluation, drift monitoring,
  AI incidents, model and dataset provenance, human oversight, and more), all
  proposed. NIST AI RMF coverage rises from 28 to 69 of 72 requirements and
  ISO/IEC 42001 from 26 to 37 of 39; the requirements left unmapped on
  purpose are listed in docs/CCF_AI_CONTEXT.md.
- Control categories: the 21 control families are grouped into 10 categories.
  `GET /api/v1/ccf/coverage` returns a `categories` ledger,
  `frameworks safeguards --format table` prints families under their category,
  OSCAL components carry a `trustops-category` property, and the console
  Control families tab groups families by category and links to each family's
  review queue.
- Fixed: a control family or category reported `state: reviewed` as soon as
  one of its mappings was reviewed, so 15 families and all 10 categories read
  as reviewed while most of their mappings were proposed. The state is now
  `reviewed` only when no mapping is proposed, `partially_reviewed` when some
  are, and `proposed_only` when none is reviewed.
- Adoption kit: a root `compose.yaml` (a loopback-only sample-data demo, and
  a `trustops-server` profile with authentication on), a
  [5-minute tutorial](docs/TUTORIAL_5_MIN.md), [CI gate](docs/CI_GATE.md)
  docs with a sample-data workflow, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT,
  and issue forms.
- Security: mapping-review endpoints return fixed error messages instead of
  exception text; the server logs only the exception class.
- Fixed: a lake with no evaluated controls reported Assessment score 100 and
  "Ready for review" (and fed that 100 into audit readiness). It now scores 0
  with posture state `not_evaluated`, shown as "Not assessed".
- Fixed: the AI governance page used stale framework ids and counted only
  evaluated controls as "mapped", so ISO/IEC 42001 and the EU AI Act read
  "0/0 mapped". Each pack now shows the requirements and safeguard-mapped
  counts the Frameworks page shows, a pass rate only when this lake has
  evidence, and packs with nothing evaluated no longer pull the governance
  score down as 0%. An inventory inferred from lineage no longer triggers the
  "no model inventory" gap.
- Console: "mapped" means mapped to a safeguard everywhere. The framework
  drawer's mapped count now matches the roster; official-source links read
  "source-cited" and the readiness gate reads "reviewed article mappings".
  A `/controls?id=` link to a control this lake has not evaluated (or an
  unknown id) says so and links to the requirement in Frameworks, and the
  crosswalk chips carry the framework for that link. "AI controls" becomes
  "AI safeguard mappings" and opens the AI governance review queue.
- Console: trust-center share links resolve in no-auth mode before the lake
  holds any data; the Azure link badge reads "No secrets stored" (a client
  secret is supported, only its env-var name is kept); date helpers show "—"
  for unparseable dates; identity marks meet 4.5:1 contrast, and the
  accessibility suite now checks color contrast, including /auth.
- Fixed: `GET /api/v1/policies?status=…` and
  `GET /api/v1/vendor-assessments?status=…` returned 500 for any status, which
  also broke the MCP `list_policies` status filter.
- Security: webhook delivery records store a fixed reason (for example "SSRF
  blocked" or the error class) instead of resolver and socket text, which
  could reveal the private address an internal hostname resolved to. Hosted
  Azure cloud links require the subscription ID to be a GUID, and a completed
  cloud-link session can no longer be completed again to overwrite its staged
  credentials.
- CI builds with the same uv version as the container image, and a test fails
  when the pins drift apart. The container's uv moves from 0.10.9 to 0.12.19
  and the `setup-uv` action from 7.6.0 to 10.2.0.
- The published image is multi-arch (`linux/amd64` and `linux/arm64`), so
  `docker compose up` runs natively on Apple silicon and Arm hosts.
- Console dependencies: Next.js 16.3.6, React Flow 12.12.0, framer-motion
  13.4.3, lucide-react 1.48, and TanStack Query 5.103.2.
- Console: GDPR, NIS2, and DORA use their own neutral marks instead of the EU
  AI Act badge; the crosswalk overlap matrices name each framework once, and
  the Control families tab states its category, family, and safeguard counts.
  README screenshots add the Control families tab and the crosswalk.

## 0.2.19 - 2026-09-28

- Operator note (hosted / multi-tenant server mode only; self-hosted
  single-tenant and CLI installs are unaffected): connector and workflow
  secrets now resolve only from tenant-prefixed variables
  (`TRUSTOPS_TENANT_<ID>__…`) or names the operator allowlists in
  `TRUSTOPS_CONNECTOR_SECRET_REFS` / `TRUSTOPS_WORKFLOW_SHARED_SECRETS`; move
  shared secrets before upgrading. Hosted AWS connectors need `role_arn` and
  `external_id`, GCP and BigQuery need `impersonate_service_account`, and Azure
  and Intune need a tenant-owned app registration. After rotating
  `TRUSTOPS_COOKIE_SIGNING_KEY`, run `frameworks review resign` once per tenant
  lake.
- Live-cloud readiness, verified against real AWS, Azure, and GCP tenants:
  `connectors probe` accepts the same credentials as sync (including a local
  CLI profile for AWS) and makes a real read-only call for Azure and GCP; GCP
  keeps collecting when an API is disabled or a permission is missing and
  reports it as a named coverage gap; connector errors say what to fix instead
  of only an exception name; and long asset IDs no longer collide, so every
  synced GCP row is counted.
- Console consistency: framework counts include only seeded packs (planned or
  superseded packs are listed separately), the superseded ISO/IEC 27701:2019
  row says so, badges use one set of labels, Preview has a keyboard-reachable
  explanation, and the overview and audit room name their different scores.
  Server-mode requests now record the signed-in user as the actor even if the
  request body names someone else. README screenshots are cropped to their
  content and include Mapping review and a phone-width overview.
- Org mapping review: your reviewers can approve, reject, or request changes
  to safeguard mappings for your tenant (console **Mapping review**, API
  `/api/v1/mapping-reviews/*`, CLI `frameworks review`). Decisions go to an
  append-only, hash-chained log in the tenant lake with reviewer, rationale,
  and time; `controls/safeguards.json` is never modified. Coverage, OSCAL, and
  snapshots report maintainer-reviewed, org-reviewed, and rejected separately.
  New `compliance_reviewer` role and `mapping_review` scope; API keys, agents,
  and MCP tools can list the queue but never decide.
- Hosted tenant isolation: in server mode, connector secret references resolve
  only under the tenant's `TRUSTOPS_TENANT_<TENANT_ID>__` prefix or the new
  operator allowlist `TRUSTOPS_CONNECTOR_SECRET_REFS`, and server secrets
  (`TRUSTOPS_*`, `DATABASE_*`, `AWS_*`, `STRIPE_*`, and similar) are always
  refused. Cloud readers need delegated access: AWS `role_arn` plus
  `external_id`, GCP and BigQuery `impersonate_service_account`, a tenant
  `kubeconfig_ref` for Kubernetes. Local Parquet paths are scoped to
  `$TRUSTOPS_LAKE_LOCAL_ROOT/<tenant_id>`. Iceberg REST and Glue readers keep
  only vended credentials from catalog metadata and accept only object-store
  locations (`s3://`, or the warehouse's `gs://`); local `file:` warehouses
  stay available in local and CLI mode only. Local and CLI runs are otherwise
  unchanged. Operator note: hosted
  tenants whose connectors name a shared or default secret must move it to a
  tenant-prefixed variable or add it to `TRUSTOPS_CONNECTOR_SECRET_REFS`; see
  docs/SERVER_AUTH.md#hosted-connector-credentials.
- Hosted Azure isolation: in server mode `azure-posture` and `intune-devices`
  authenticate only as the customer's own Entra app registration (`tenant_id`,
  `client_id`, and one of `client_secret_ref`, `client_certificate_ref`, or
  `federated_token_file_ref`). `DefaultAzureCredential`, the `az` CLI login,
  and the server-wide `AZURE_SUBSCRIPTION_ID`/`AZURE_TENANT_ID` overrides are
  refused for tenants. Local and CLI runs keep `DefaultAzureCredential`.
  Operator note: hosted Azure and Intune connectors that relied on the
  server's identity stop syncing until the tenant configures an app
  registration and the operator provisions its secret under the tenant prefix.
- Hosted workflow secrets: in server mode `{{secret.NAME}}` resolves from the
  calling tenant's `TRUSTOPS_TENANT_<TENANT_ID>__SECRET_<NAME>`, not the shared
  `TRUSTOPS_SECRET_<NAME>`. Operator note: before upgrading, copy each
  tenant's workflow secrets to its prefixed name (tenant `acme`:
  `TRUSTOPS_SECRET_SLACK_WEBHOOK` becomes
  `TRUSTOPS_TENANT_ACME__SECRET_SLACK_WEBHOOK`), or list a secret that is
  deliberately shared by every tenant in `TRUSTOPS_WORKFLOW_SHARED_SECRETS`.
  Unmigrated webhook, Slack, and Jira actions fail without sending. Local
  mode is unchanged.
- Mapping review: the new `frameworks review resign` command
  (`--lake <dir> --previous-key-env <NAME>`) re-signs the decision-log tip
  after `TRUSTOPS_COOKIE_SIGNING_KEY` is rotated. It verifies the hash chain and the old tip MAC with the
  previous key first, refuses and writes nothing if either fails, and records
  a `tip_resigned` entry in the workbench audit log. Operator note: after
  rotating the key, run it once per tenant lake. See
  docs/MAPPING_REVIEW.md#rotating-the-signing-key.
- SSRF guard: 6to4 (`2002::/16`) and Teredo (`2001::/32`) addresses are
  judged by the IPv4 addresses they embed, so one that tunnels to a private,
  loopback, or metadata IPv4 is refused on every supported Python version.

## 0.2.18 - 2026-09-27

- Operator note: this release adds database migration `0020`
  (`saml_assertion_replays`). The server applies it at startup; with more than
  one replica, upgrade with a single replica first.
- New connectors (preview): Jamf Pro (device encryption, OS patch level,
  screen lock, firewall, managed state), CrowdStrike Falcon (sensor coverage,
  prevention policies, detections), Kubernetes (cluster-admin bindings, pod
  security, network policies, image registries; new optional `kubernetes`
  extra), and KnowBe4 (training completion and phishing results). All are
  read-only, use credential references, and report against existing control
  IDs. Connectors not yet verified against a live tenant carry
  `release_stage: "preview"` and a Preview badge in the console.
- ISO/IEC 27701:2025 limited privacy pack (`iso-27701-2025`): 10 of the 78
  Annex A controls, each with its identifier and short title confirmed by two
  independent non-vendor sources; the other 68 are listed as gaps. The
  withdrawn 2019 edition stays planned. New privacy evidence types, connector
  hints, and proposed safeguard mappings.
- Docs: the README leads with the two evidence modes (ingest, or read the lake
  you already run), a self-host table, and a plain scope table, with each fact
  stated once. Connector, roadmap, deployment, and product-status docs match the
  live catalog (28 contracts, 25 executable) and coverage (17 packs, 2,031
  requirements; NIST RMF mapped, ISO 27701:2025 limited), and stale "scaffold"
  wording is gone. The Databricks reader is now marked preview in the connector
  catalog, matching its docs.
- Console visual system: neutral light and dark themes with clear elevation
  steps (page, rail, card, raised) and visible borders; one brand accent for
  primary actions, the active page, links, and focus; and a status palette
  (success, warning, serious, danger, info) whose tinted chips meet WCAG AA in
  both themes. Light mode now has a light shell. A contract test checks every
  text/surface pair.
- Overview is decluttered so each number appears once: one status line, KPI
  tiles with a label, number, one line of context, and an optional meter, a
  framework list with a single sort control, and a five-row findings preview
  (severity, title, control ID) that no longer clips. The collapsed
  "Operational detail" section and the duplicate Exports tab are gone; owner,
  environment, and source live in the finding drawer.
- The finding drawer is grouped into Summary, Details, Remediation (with
  button actions), and Triage. Page headers, tabs, filters, and the pipeline
  stepper share one pattern across routes, and graph layers use validated
  categorical colours with dimmed nodes that stay legible.
- Golden demo data: each event's source now follows its event type (a model
  drift alert comes from the SIEM, not AWS Config).
- Deepen the common control framework: 34 new safeguards split thin families
  (governance, incident response, privacy, change, vulnerability, configuration,
  secure development, architecture, processing integrity, third-party risk,
  system maintenance) into their sub-objectives, and map 43 of the 47 NIST RMF
  (SP 800-37 Rev 2) tasks with task-level citations. All 351 new mappings are
  `proposed`, so evaluatable coverage rises from 813 to 991 requirements while
  attestable (reviewed) coverage stays at 350.
- Bring your own lake (experimental): a declarative lake mapping spec maps
  existing tables to evidence, so the Snowflake, Databricks, and ClickHouse
  readers no longer need TrustOps-shaped views. Mappings compile to read-only,
  parameterized queries. Built-in OCSF presets cover Authentication, Account
  Change, API Activity, and Detection, Vulnerability, and Compliance Findings
  (OCSF 1.1.0), plus the legacy Security Finding (OCSF 1.0.0-rc.2).
  `security-lakehouse lake map --dry-run` previews mapped rows and errors. New
  preview readers: `iceberg-parquet-lake` (Iceberg via AWS Glue, including
  Amazon Security Lake, or REST catalogs, and Parquet on S3) and
  `bigquery-evidence-lake` (new optional `bigquery` extra). See
  docs/BRING_YOUR_OWN_LAKE.md.
- Widen mapping coverage on the existing safeguards: 180 title-theme mappings
  for ISO 27001:2022 (57 to 81 of 93), NIST CSF 2.0 (79 to 101 of 106),
  ISO 27017 (29 to 44 of 47), NIST AI RMF (20 to 28 of 72), FedRAMP Moderate
  (207 to 262 of 287, with their 800-53 twins), and GDPR (18 to 19 of 20),
  plus cited NIST RMF tasks P-3, P-14, and M-7 (43 to 46 of 47). All are
  `proposed`: evaluatable coverage rises from 991 to 1174 requirements while
  attestable (reviewed) coverage stays at 350.
- Outbound HTTP connects to the IP address it validated. Connectors, webhooks
  and workflow actions resolve each host once per connection, require every
  answer to be public, and open the socket to that address, so a DNS answer
  that changes between the check and the connect (rebinding) cannot reach a
  private address, including on redirect hops. TLS SNI and certificate checks
  still use the hostname. Requests through an operator egress proxy connect to
  the proxy.
- SAML replay protection is shared across replicas: consumed assertion IDs are
  stored in the application database under a unique constraint, so a replay to
  a different replica is rejected. A database error rejects the login.
- The golden demo names its assets ("Customer records bucket", "Risk scorer
  model"), and the console shows those names in findings, evidence, drawers,
  the command palette, AI inventory and the graph, keeping the stable IDs in
  drawers and tooltips. Raw events may set the optional `entity.asset_name`;
  the API returns it as `asset_name`. Normalized events and their Parquet and
  Iceberg exports are unchanged.
- `fixtures load --rebase-times` puts the newest demo row three hours back
  instead of one, so the demo's freshness counts and posture score stay the
  same for about a day instead of changing minute to minute after a load.
- `frameworks sync` reports drift only when a source's content hash changes;
  `pulled_at` now records when the current content was first seen, so the
  scheduled job no longer opens a PR for every run.
- The package declares its license as the SPDX expression `Apache-2.0`
  (wheel metadata 2.4, `License-Expression`); building needs setuptools 77 or
  newer.

## 0.2.17 - 2026-09-27

- Operator note: this release adds database migration `0019` (a
  `resolution_note` column on remediation tasks). The server applies pending
  migrations automatically at startup, so back up the database before
  upgrading. With more than one replica, upgrade with a single replica first
  (or scale to one) so only one process runs the migration.
- Add SCIM provisioning and Billing panels to the console's Auth page for
  commercial hosted admins: create SCIM tokens with a one-time reveal, revoke
  them, see plan and access state, and open Stripe checkout or the customer
  portal. Both panels stay hidden on OSS installs. Listing SCIM tokens now
  returns 501 when SCIM is disabled, matching create.
- Console polish: dark-mode contrast across every route, layouts that fit at
  390px, a graph that wraps wide ranks instead of shrinking to unreadable zoom,
  a paginated crosswalk, sign-in options first on phones, and one page width
  and gutter scale. `/api/v1/platform/usage` returns 501 instead of 404 without
  commercial hosting, and the POC "Agent/API access" step links to the console.
- Stop overclaiming readiness, freshness, and review status. Readiness numbers
  change on upgrade: a framework is ready only when at least 50% of its catalog
  controls are assessed (not on score alone), controls without evidence are
  `missing` rather than fresh, the audit score no longer counts shipped product
  features, and the crosswalk shows each mapping's real status (reviewed or
  proposed). The readiness payload adds per-framework coverage and
  `framework_ready_criteria`.
- Persona-driven console fixes: findings carry into tasks and link back,
  resolving a task records proof in the new `resolution_note` field, owner
  filters, trust shares with a copyable URL and preview (public shares no
  longer expose violation or stale counts), adoptable policy templates, and
  refreshed demo data.
- Reviewers can reject a proposed agent decision with a reason
  (`POST /api/v1/agent-runs/{id}/decisions/{i}/reject` and a matching MCP tool);
  a rejected decision never runs and approving it returns 409. The OpenAPI
  document is regenerated. Frameworks and Crosswalk now name their mapping
  units, and console pages mount once per navigation, so input typed right
  after a navigation is no longer lost.
- Security fixes. ClickHouse evidence-lake cursors are sent as typed query
  parameters and every query runs with `readonly=1` (a crafted row value could
  previously break out of the SQL literal). SAML responses must answer a login
  this server started and each assertion is accepted once; IdP-initiated login
  now requires `TRUSTOPS_SAML_ALLOW_IDP_INITIATED=true`. Self-service signup
  fails closed without `TRUSTOPS_SIGNUP_SECRET` unless
  `TRUSTOPS_ALLOW_OPEN_SIGNUP=1`. The local stdlib server rejects foreign
  `Host` and cross-origin `Origin` headers, requires JSON bodies, and caps
  request size. Rate limits key on the client until a bearer token
  authenticates. Egress checks block all non-global addresses (including
  CGNAT). Invite acceptance records the new user, returns 409 for existing
  members, and validates the role.
- Console: mobile navigation drawer, one name per page across the sidebar,
  headings, and command palette, Graph and Settings in the sidebar, keyboard
  and screen-reader support in the shell and command palette, contrast fixes,
  loading and error states where pages showed empty data, and a flat KPI strip
  on the overview. README, roadmap, and deployment docs now match the code,
  and README screenshots are captured from one frozen dataset in both themes.
- Harden the release pipeline: a tag publishes only a commit that is on main
  and passed CI, and only when the package, chart, console, `package.json`,
  and changelog agree on the version. Wheels, sdists, and the container image
  carry signed build provenance; the image also carries an SBOM, and the
  release attaches a CycloneDX SBOM of the Python dependencies. Fixable HIGH or
  CRITICAL image vulnerabilities fail CI and block the release. Workflow
  actions and container base images are pinned by digest. `latest` moves only
  on stable releases. Framework sync retries rate-limited or failing regulator
  sites and reports per-source errors without failing the job.

## 0.2.16 - 2026-09-24

- Add production SCIM 2.0 for commercial hosted tenants: per-tenant hashed
  bearer tokens with rotation, raw `application/scim+json` responses, user
  filters, PUT/PATCH in the shapes Okta and Entra ID send, soft delete that
  keeps the audit trail, and Groups whose membership maps to TrustOps roles
  through `TRUSTOPS_SCIM_ROLE_MAP`.
- Add Stripe billing for commercial hosted tenants: Stripe Checkout and the
  customer portal, signature-verified and idempotent webhooks that re-read the
  current subscription, plan tier driven by the subscription price, and a
  past-due grace period followed by read-only access (data and reads kept).
- Add a Databricks evidence-lake reader (preview) over Unity Catalog views via
  the SQL Statement Execution API with OAuth M2M, plus a bootstrap SQL script;
  live-workspace verification is pending.
- NIST SP 800-53 mappings that duplicate a human-reviewed FedRAMP Moderate
  mapping now inherit that review (attestable 254 -> 350 of 2,021), and NIST AI
  RMF titles use the official NIST AI 100-1 subcategory statements.

## 0.2.15 - 2026-09-24

- Add the full NIST SP 800-53 Rev 5.2.0 catalog (1,014 active controls and
  enhancements, 20 families) generated from a pinned official OSCAL commit,
  with LOW/MODERATE/HIGH/PRIVACY baseline tags, and the NIST Risk Management
  Framework (SP 800-37 Rev 2, all 47 tasks). Both are source-reconciled and
  proposed, not human-reviewed.
- Add CIS Controls v8.1 at the control level (all 18 controls) and a governed
  CCF family taxonomy (`controls/families.json`, 21 families with NIST 800-53
  and CIS crosswalks) replacing a catch-all family.
- Add proposed CCF mappings that raise evaluatable coverage for ISO 27001
  Annex A (11 → 43 of 93), NIST AI RMF (10 → 20), and NIST CSF 2.0 (29 → 46);
  attestable (reviewed) coverage is unchanged.
- Cite PCI DSS v4.0.1 across all 12 principal requirements via versioned
  control successors; document why SOC 1 stays planned (no official control
  catalog).
- Add Microsoft Intune device-posture and BambooHR, Rippling, and Workday
  (RaaS) employment-record connectors with a minimal PII boundary, and an
  offboarding check that flags terminated employees whose Okta or Google
  Workspace account can still sign in.
- Let installed packages register connector catalog metadata through a
  `trustops.connector_catalog` entry-point group.
- Fix: readiness no longer treats proposed mappings as reviewed; framework
  coverage reports reviewed identifier mappings separately from
  source-cited ones; the review queue no longer lends a crosswalk citation to
  title-theme mappings; OAuth connectors (including `identity-provider`) can be
  enabled from the console; `controls/families.json` ships in the wheel.

## 0.2.14 - 2026-09-23

- Export OSCAL Component Definition and Assessment Results (NIST's
  control/assessment interchange format) via a new CLI command and API
  endpoints, so auditor tooling and other GRC platforms can consume TrustOps
  assessment data without a bespoke adapter. Only reviewed (human-confirmed)
  safeguard mappings are represented as implemented requirements.
- Let third-party packages register connectors via a `trustops.connectors`
  Python entry-point group, alongside the existing in-repo adapters, without
  forking the repository.
- Add outbound event webhooks (`finding.created`, `assessment.completed`,
  `control.failed`) with HMAC-signed, retried delivery and a dedicated,
  opt-in destination allowlist separate from workflow-automation egress.
- Convert 12 of 13 framework packs from bespoke Python functions to
  JSON manifests read by a shared builder, verified row-identical
  (including every control id) against the prior generated output.

## 0.2.13 - 2026-09-22

- Serialize hash-chain writers with a cross-process lock so concurrent
  violation-triage and assessment-snapshot requests can no longer fork the
  tamper-evident audit chain.
- Resolve two `anyio` CVEs (CVE-2026-63374, CVE-2026-64847) via a transitive
  dependency bump; no functional changes.
- Show the product tour screenshots by default in the README instead of
  behind a collapsed section.
- Promote 209 Common Control Framework safeguard mappings from proposed to
  reviewed across CMMC 2.0, ISO 27017, FedRAMP Moderate, ISO 42001, and CIS
  AWS, raising audit-defensible (attestable) coverage from 4.8% to 27.0%.
- Routine web dependency updates (`@tanstack/react-query`, `framer-motion`,
  `lucide-react`, `tailwind-merge`, `@types/node`, `autoprefixer`).

## 0.2.12 - 2026-09-15

- Lead the dashboard overview with overall posture, an assessment score out of 100,
  and a prominent control pass rate with passing-test counts. Keep findings and
  exports alongside them, and distinguish unevaluated controls from a zero pass rate.
- Unify overview cards with matching navy surfaces, labeled test-outcome and
  finding-severity charts, and aligned actions. Preserve compact tablet layouts
  and mobile accessibility. Test outcomes outside pass/fail/warning remain Other.
- Keep control-drawer status badges readable beside long control titles.
- Refresh release-readiness documentation and align package, console, and Helm
  versions. Assessment calculations and connector behavior are unchanged.

## 0.2.11 - 2026-09-14

- Compact the app header and assessment overview, with direct workspace links,
  expandable assessment details, and an account menu available on mobile.
- Read the versioned health response correctly so a healthy API is not shown
  as unavailable in the console header.
- Refresh selected workflow-node parameters when the loaded workflow changes,
  and clear test results associated with the previous parameters.
- Replace an accepted invite's URL with sign-in so Back does not reopen the
  consumed invite link. Preserve full session-cache reset on authentication loss.
- Stabilize console effect dependencies and workflow keyboard handlers.
- Restore the README cloud/vendor banner and visible framework and common-control
  sections, with generated mapped-versus-reviewed coverage totals.
- Update compatible console dependencies together, align React and React DOM,
  and patch transitive JavaScript dependency vulnerabilities. Retain the MCP 1
  compatibility bound because the MCP 2 entry point is incompatible.
- Group routine dependency updates weekly by ecosystem, limit outstanding
  version-update PRs, and group security fixes separately.

## 0.2.10 - 2026-09-14

- Reject truncated, unknown-completeness, and malformed public repository trees
  before replacing collected evidence.
- Stop saving source-text excerpts in public repository audit events. Keep paths
  and sample hashes; existing collected evidence is not rewritten.

- Stream artifact SHA-256 checks through a reusable 1 MiB buffer during evidence
  integrity creation/verification, generation sealing/verification, and Parquet
  export. Preserve digest formats, tamper detection, and publication failure
  behavior. Add a reproducible synthetic hashing memory benchmark; full-pipeline
  capacity, live accuracy, and cost savings remain unverified.

## 0.2.9 - 2026-09-13

- Add an optional, generation-pinned Parquet evidence export with explicit tenant
  checks, private atomic publication, provenance, and independent DuckDB parity
  tests.
- Add optional Iceberg REST publication to one tenant-scoped evidence table.
  Verify local Polaris commits and DuckDB reads, retained-snapshot retries,
  historical reads, nullable schema additions, and catalog permission denial.
- Require externally issued bearer tokens, HTTPS outside explicit loopback tests,
  bounded requests, and confirmed snapshot provenance. Reject redirects, remote
  authentication plugins, incompatible schemas, and silent concurrent replacement.
- Include the optional export dependencies in the container and align package,
  console, chart, and documentation at 0.2.9. Constrain container dependencies to
  the audited lockfile. Cloud object storage, distributed
  scale, live accuracy, and cost savings remain unverified.
- Allow empty assessments to create typed DuckDB tables without failing on
  empty insert batches.

## 0.2.8 - 2026-09-13

### Fixed

- Stop incomplete pagination and failed required GCP reads before replacing
  retained evidence. Reject invalid evaluation rules and duplicate control IDs.
  Preserve unknown/retired controls as not evaluated instead of applying a default rule.
- Publish verified assessment generations through an atomic current pointer;
  interrupted publication preserves the prior generation.
- Compute AI framework posture from passing controls, separately from evidence
  presence. Correct CSF 2.0 identifiers against the pinned NIST source and retain
  prior control definitions in history.
- Include safeguard definitions in catalog hashes and installed packages. Ship
  framework pack data, equivalence mappings, history, fixtures, and agent skills.
- Restore supported Azure resource-policy and MCP dependency bounds.

### Changed

- Apply the TrustOps identity across the console, README, shared images, and MCP.
  Add independent collapsible dashboard panels, readable framework rows,
  control-family icons, contextual triage, and reviewable evidence requests.
- Organize the README into a short setup path and expandable reference sections.
- Add proposed AI inventory/context and risk/monitoring safeguards. The catalog
  now has 44 safeguards mapping 559/942 requirements; 45 remain reviewed.
- Add the TrustOps operator skill alongside six specialist skills. Document
  evidence completeness, scoped conclusions, authorization, and retry boundaries.

Mapping coverage does not establish framework compliance. Live precision,
recall, production capacity, and vendor cost savings have not been established;
the benchmark protocol separates those measurements from synthetic validation.

## 0.2.7 - 2026-09-01

Release theme: **secure dependencies + clearer first-run story**. Restores the
release security gate and makes the README's product journey readable at a
glance without changing TrustOps proof semantics.

### Security

- Raised the optional Snowflake connector floor to 4.7.1 and regenerated the
  lockfile, replacing 4.6.0 after `pip-audit` identified CVE-2026-15925.

### Added

- Common Control Framework safeguards for controlled maintenance and
  separation of duties, sourced from the NIST SP 800-171 Rev. 2 crosswalk.
  Their new mappings remain proposed pending human review.
- CMMC Level 2 awareness and role-based training mappings sourced from NIST SP
  800-171 Rev. 2 Appendix D. They raise evaluatable CMMC coverage to 96/110;
  attestable coverage is unchanged pending human review.

### Changed

- Rebuilt the README identity system around a crisp scalable hero, transparent
  wordmark, simpler four-stage operating-loop banner, and clearer navigation.
- Consolidated the queued Python and web dependency updates into one verified
  lockfile refresh.
- Mapping review output now carries validated crosswalk provenance, preferring
  the exact per-mapping locator when a safeguard is backed by multiple rows. CLI
  and MCP consumers can filter by normalized risk-domain category/family and
  receive framework/domain plus source-backed/unsourced backlog rollups.

## 0.2.6 - 2026-08-17

Release theme: **maintenance + unattended Google Workspace sync**. Closes the
last gap left by the 0.2.4 OAuth refresh work and refreshes dependencies.

### Added

- Google Workspace can be enabled with refresh-token material alone
  (`refresh_token_ref` + `client_id` + `client_secret_ref`) instead of a
  pre-minted access token. The runner already minted tokens from that triple;
  enablement validation and the console connector form previously demanded a
  static `credential_ref` anyway, so unattended sync could not be configured
  through the console. A partially-supplied triple is now rejected by name at
  probe and enable time rather than silently falling back to the static-token
  path.

### Changed

- Web console dependencies updated: `next` and `eslint-config-next` 16.3.0 ->
  16.3.1, `@xyflow/react` 12.11.2 -> 12.11.3, `@dagrejs/dagre` 3.1.0 -> 3.1.1,
  `caniuse-lite` -> 1.0.30001809, `postcss` -> 8.5.26. The console still builds
  with the pinned Webpack builder.
- Release workflow actions updated to their current majors:
  `docker/login-action` v4, `docker/metadata-action` v6,
  `softprops/action-gh-release` v3.
- The example MCP host config moved from `.cursor/mcp.json.example` to
  `examples/mcp/mcp.json.example`; it is a generic stdio MCP config, not
  editor-specific. Contents are unchanged.
- `ROADMAP.md` P7 no longer presents its issue table as open work; all nine
  linked issues are closed on GitHub, and `docs/PRODUCT_SHAPE.md` carries the
  honest per-item status (two are still _Partial_).

## 0.2.5 - 2026-08-14

Release theme: **complete the connector-resilience pass**. Closes the last gap
from the resilience audit — the append-mode readers that pulled a whole window
in one request now paginate it.

### Fixed

- ClickHouse, SIEM, and runtime-gateway readers paginate their `since`-window
  instead of truncating it at the server's first page. ClickHouse keyset-paginates
  on the composite `(event_time, event_id)` cursor with `LIMIT`, so rows sharing an
  `event_time` across a page boundary are never dropped and the loop always
  terminates. SIEM and runtime-gateway follow an optional `next_cursor` envelope
  via `?cursor=`; an export that returns a bare list is still read as a single
  page, so a non-paginating endpoint keeps working unchanged.

## 0.2.4 - 2026-08-14

Release theme: **honest framework coverage + connector resilience**. Separates
the coverage a compliance product may attest to from the coverage it merely
touches, and hardens the read-only connectors against redirects and rate limits.

### Security

- Repo-governance connector (GitHub/GitLab) now reaches its APIs through the
  same SSRF guard as every other HTTP connector, re-validating each redirect hop
  and stripping `Authorization` across origins. The GitLab base URL is
  operator-configurable, so a redirect could otherwise pivot the request and its
  bearer token at an internal address.

### Added

- Framework coverage matrix that splits **evaluatable** (any safeguard mapping)
  from **attestable** (human-reviewed — the only coverage an auditor accepts),
  surfaced via `frameworks coverage`, an MCP tool, and a committed, gated doc.
- Mapping review-queue (`frameworks review-queue`, `--framework` to scope, plus
  an MCP tool) that lists the proposed safeguard→requirement mappings awaiting
  expert sign-off, each paired with the reviewed anchors on the same safeguard.
  It never auto-promotes a mapping — accepting one stays a domain-expert call.
- Google Workspace connector supports OAuth refresh tokens for unattended sync,
  exchanging the refresh token when the access token is missing, near expiry, or
  rejected once with 401. The refresh token and client secret resolve file-first,
  and the resolved access token is held in memory only, never persisted.

### Fixed

- Connectors retry transient rate-limit / gateway errors (429/5xx, honoring
  `Retry-After`, with exponential backoff + jitter) instead of failing a whole
  sync on a single blip: SIEM, runtime-gateway, ClickHouse, and repo-governance.
  4xx stays terminal.
- Google Workspace connector follows the Directory API `nextPageToken` instead
  of a single request, so a tenant with more than a page of users/groups/members
  is no longer silently truncated.

## 0.2.3 - 2026-08-13

Release theme: **security + supply-chain currency**. Publishes the fixes and the
new connector work that landed on `main` after 0.2.2.

### Security

- Upgraded the bundled web console to Next.js 16, clearing four high-severity
  production advisories (nanoid, postcss, sharp, and the transitive next chain).
- AWS connector: `password_policy`/`console_access` now surface unexpected IAM
  errors instead of swallowing them into a false control pass.
- `required_post_scope` fails closed — a mutating route not explicitly scoped is
  denied rather than accepting the low `write` scope.

### Added

- AWS connector cloud-linking: read-only posture role, a dedicated connector
  runtime role, and the cloud-link console flow.

### Fixed

- Dropped the opaque `/api/{rest}` catch-all from the published OpenAPI spec and
  catalogued six previously undocumented served routes.
- Helm: pin the scheduler CronJob to the API pod's node when the lake PVC is
  ReadWriteOnce, so it can mount; chart version is now gated against the release.
- Corrected the `db upgrade` command in the hosted deployment guide.

### Docs

- README status badges + PyPI classifiers; architecture diagrams now use real
  vendor logos and the official Snowflake/ClickHouse marks with proportionate
  arrowheads.

## 0.2.2 - 2026-08-12

Release theme: **audit follow-through**. Applies the confirmed findings from a
four-lane audit (code / CI / product surfaces / packaging).

### Security

- Routed the Google Workspace connector client through the shared `netguard`
  guarded opener — the one credentialed client still on raw `urllib` after the
  0.2.1 egress hardening, so its OAuth bearer can no longer follow a cross-origin
  redirect.
- Stripped local-only options (`fixture_dir`) from the connector configure
  forward-merge so a value seeded off-API cannot re-attach on a later API call.
- Constant-time trust-share token comparison.

### Fixed

- AWS access keys with an unparseable `CreateDate` no longer score a false pass
  on the rotation control.
- `__version__` is derived from installed distribution metadata (no more drift).
- Helm chart version tracks the released image tag; release verification now
  gates on it.

## 0.2.1 - 2026-08-12

Release theme: **egress SSRF hardening**. Closes three confirmed server-side
request forgery findings that shared one root cause — the outbound guards
validated only the first URL, then followed redirects (and server-supplied
pagination `Link` headers) to unvalidated hosts.

### Security

- Added `netguard.open_guarded`/`open_public`: a shared HTTP opener that re-runs
  the caller's SSRF/allowlist validator on every redirect hop and drops
  `Authorization`/`Cookie` headers on any cross-origin hop.
- Routed all host-based connector clients (Okta, SIEM, ClickHouse, runtime
  gateway, Jira) through the guarded opener, closing the connector probe/discover
  SSRF and the Okta `Link`-header token-pivot.
- Reran the workflow webhook/Slack/Jira egress path through the guarded opener so
  a 302 from an allowlisted host can no longer pivot the request (or its secret
  headers, or the response body) at an internal address.

## 0.2.0 - 2026-06-29

Release theme: **invite-only hosted POC readiness**. This release turns the repo
from a local/security-lake proof into a more coherent self-hosted TrustOps
platform: deployable by URL, usable by humans, and callable by headless agents.

### Product

- Added a first-run launch surface at `/console/poc/` that checks public URL,
  human auth, headless access, source sync, trust shares, and agent review state.
- Streamlined connector onboarding so Snowflake setup starts with identity,
  discovers granted scope, then lets the operator select read objects before
  testing/enabling.
- Added connector sync proof in the drawer so operators can see latest sync
  result, evidence count, fingerprint, and timing without opening raw logs.
- Added a governed agent harness launcher in the console with sequential vs.
  LangGraph orchestration, model toggle, budget profiles, persisted runs,
  decision review, and approval-gated writes.
- Added agent review readiness to the launch flow so the hosted POC path can go:
  connect source -> sync -> assess -> run governed review -> share trust.

### Evidence, Connectors, And Ingestion

- Proved live AWS, Azure, and Snowflake ingestion paths through the same
  scenario contract used by fixtures and CI.
- Added Snowflake read-scope discovery for warehouses, databases, schemas, and
  granted views.
- Hardened continuous ingestion docs around incremental reads, idempotency,
  retry safety, scheduler operation, and customer-owned lake boundaries.
- Added pluggable sink and lake-adapter guidance for Snowflake, ClickHouse,
  DuckDB, local files, and existing evidence-lake reads.

### Agent And Workflow Runtime

- Added persisted `agent_runs` with input hashes, budget metadata, evaluation
  results, proposed decisions, approval state, and API/MCP access.
- Added optional LangGraph orchestration while keeping the deterministic
  assessment engine model-independent and usable with zero LLM configured.
- Added model budget controls for context size, fact count, and output tokens.
- Kept writes behind RBAC, allow-listed action types, idempotency, and approval.

### Security And Operations

- Hardened API error handling and CodeQL findings around path use and exception
  exposure.
- Added API pagination/rate-limit robustness and safer connector error surfaces.
- Added hosted POC, AWS + Snowflake, live cloud, and continuous ingestion
  runbooks.
- Added OIDC/SAML/API-key server-mode docs, tenant lake boundaries, redaction,
  hashes, append-only audit records, and trust-share guidance.

### Known Gaps Before Public SaaS

- No public self-serve signup, billing, SCIM lifecycle, or multi-customer
  account marketplace.
- Connector auth is POC-capable but still needs more OAuth/service-role wizards,
  secret-manager integrations, and provider-specific hosted UX polish.
- Framework packs are seeded and source-linked, but not full certification-grade
  coverage for every framework.
- Workflow automation has a usable DAG/canvas, templates, and runs, but still
  needs deeper run inspection, retries, approvals, and action logs.
- Production operations need backup/restore drills, external secret sync,
  multi-replica guidance, alerting, WAF/API gateway guidance, and hosted
  observability before a broad public launch.
