# Release readiness

GRC Lake **0.3.22 is published** on
[PyPI](https://pypi.org/project/grc-lake/0.3.22/),
[GitHub](https://github.com/koda-ai-studio/grc-lake/releases/tag/v0.3.22), and as
`ghcr.io/koda-ai-studio/grc-lake:0.3.22`.
Use the [v0.3.22 release templates](https://github.com/koda-ai-studio/grc-lake/tree/v0.3.22)
for a published deployment. The [publication receipt](#verified-0322-publication)
records the verified source, artifact hashes and runtime checks. Later changes
on `main` are unreleased until a new tag passes the release gates.

Current source includes a review-policy correction: missing review status and
354 historical mappings without an attributed decision are proposed. These
changes reduce attestable coverage; they do not mean a provider's operating
posture deteriorated. New endpoint and remediation-tracking mappings also remain
proposed. Follow the [mapping-review procedure](MAPPING_REVIEW.md) for human
decisions, and check the [0.3.17 changelog](../CHANGELOG.md#0317---2026-10-27) before
comparing results with an earlier release.

The shell-free runtime uses pinned Wolfi Python and matching system libraries.
CI and release gates block all HIGH/CRITICAL and fixable MEDIUM image findings.
Historical publication receipts and scan results below apply to their recorded
artifacts, not to future builds or current vulnerability databases.

Use the generated [coverage matrix](FRAMEWORK_COVERAGE.md) for current mapped and
reviewed counts, and the [SOC 2 and ISO review queue](reviews/SOC2_ISO_REVIEW.md)
for pending mapping decisions. Proposed mappings do not grant review credit;
reviewed mappings do not establish operating effectiveness or certification.
The [graph cache and navigation measurements](benchmarks/INVESTIGATION_CACHE.md)
retain their exact source revisions and synthetic workload limits. They do not
establish production capacity or qualify a deployment memory budget; 100k records
remain outside the accepted local interactive profile.

## 0.3.23 release candidate

0.3.23 is being prepared and is not yet published. Installation instructions
remain on the verified 0.3.22 artifacts until publication checks complete.

This patch adds an explicit second-review packet mode and tightens qualification
receipt and benchmark correctness checks. No provider is newly live-qualified,
no mapping approval is recorded, and no capacity limit is expanded. The 0.3.22
evidence-applicability fix remains in place. There is no database migration or
dependency upgrade. Re-prepare derived graph indexes after upgrading because
index identity includes the installed runtime source.

Local candidate checks passed for version consistency, changelog, package data,
release provenance and image gates (50 tests), plus evidence applicability
(23 tests). A built wheel passed isolated core and server installation smoke
checks, including the bundled console, replay, integrity and snapshots. The
advisory reproduction against that installed wheel kept both the unrelated
safeguard and framework requirement `not_evaluated`. These are synthetic local
checks; they are not publication or additional provider receipts.

Independent human approval, exact merged-main CI, final package/install checks,
and the release workflow's image, chart and provenance gates remain required
before publication can be claimed.

## 0.3.22 release

0.3.22 is published; see the [publication receipt](#verified-0322-publication).

The release adds evidence applicability checks, collection-gap readiness,
compact console pages and scoped persistent graph preparation/navigation.
Reevaluate existing lakes after upgrading: unsupported safeguard or requirement
results can become `not_evaluated`. Incremental evaluation invalidates its prior
evaluator fingerprint and creates a new generation; existing generations and
snapshots retain their original content. No database migration or mapping-review
approval is introduced by this release.

Derived graph indexes include runtime source identity. After upgrading, prepare
them again with `grc-lake graph prepare-index --lake PATH`, supplying the platform
tenant where required. Local synthetic 500k prepared-index measurements do not
qualify ingestion or production capacity. The million-record preparation reached
its 30-minute watchdog; broader capacity work remains in issue #910. Retain the
supported profile in [release qualification](benchmarks/RELEASE_PROFILE.md).

Local candidate checks passed: 40 packaging/release tests, lint, formatting,
type checking and console build/lint. The clean wheel contains the same 263
console files as the static export. An isolated core install passed fixture,
replay, integrity, snapshot and console checks. Upgrading a copied 0.3.21 lake
created a corrected generation while preserving previous generation and snapshot
bytes. Authenticated loopback reads rejected missing/invalid credentials and
cross-tenant access. These checks do not establish publication or live-provider
qualification.

Independent human approval, exact merged-main CI, package/install/upgrade checks,
both image architectures' vulnerability and authenticated runtime checks, and
chart/provenance verification passed. The [security advisory](https://github.com/koda-ai-studio/grc-lake/security/advisories/GHSA-76q3-wh53-hvv2)
is published with 0.3.22 as the patched version.

## 0.3.21 release

0.3.21 is published; see the [publication receipt](#verified-0321-publication).
It includes source-account isolation, organization account selection, partial-read
safeguards, authentication recovery, dependency security fixes and investigation
hierarchy with readable focus, overview and roll-up. Kubernetes node/accelerator
discovery and the synthetic AI-lab walkthrough are included. See the
[changelog](../CHANGELOG.md#0321---2026-10-30) for the release scope.

There is no database migration relative to 0.3.20. A fresh candidate install and
an upgrade from a separate 0.3.20 environment over a copied synthetic lake retained
59 records, verified historical snapshots and preserved replay integrity. The
original baseline was retained. The final candidate tree is identical to the
merged release tree; local qualification does not establish publication.

The final candidate passed the [bounded graph profile](benchmarks/RELEASE_PROFILE.md)
at 1k and 10k records per tenant: warm p95 at 10k was at most 150 ms, cold and
post-expiry reads stayed below 2.5 seconds, and peak process RSS was 429.3 MiB.
This is a synthetic local SQLite profile, not a million-finding, full-ingestion
or production-capacity qualification. TLS/IdP integration, backup/restore and
provider scope require their own deployment receipts.

Use `ghcr.io/koda-ai-studio/grc-lake` in current deployment instructions. Older
receipts retain the registry namespace and digest that were actually verified.
After publication, follow the [14-day pilot stability period](PILOT.md#stability-period)
and record useful real-evidence outcomes and repeat use separately from downloads
or synthetic demo completion.

## 0.3.20 release

0.3.20 is published; see the [publication receipt](#verified-0320-publication).
It packages audit fixes for review-state validation, provider redirects, append
watermarks, Jamf passcode verdicts and investigation-graph accuracy. See the
[changelog](../CHANGELOG.md#0320---2026-10-28) for the release scope.

Package, chart, console, Compose and MCP versions are aligned. This release adds
no dependency upgrade or database migration. Connector redirects stay on the
request's host and never downgrade from https to http, so a provider configured
on a host that redirects elsewhere (for example the wrong CrowdStrike region)
fails collection instead of following the redirect; configure the provider's
canonical host. Graph control nodes show the control-test verdict, and identity
aliases link only through evidence with current freshness. The install guides
now name the verified publication.

Exact merged-main CI, both image architectures' release checks and chart
qualification preceded publication. A bounded live GitHub collection on the
candidate source succeeded with no collection gaps; other providers are covered
by fixture tests only, and no new live-provider receipt is claimed.

## 0.3.19 release

0.3.19 is published; see the [publication receipt](#verified-0319-publication).
It includes the transport, request-body and response-budget fixes, focused CCF
family organization, and the bounded FedRAMP KSI identity subset. That subset
covers 2 of 46 pinned source indicators; both mappings remain proposed and require
human review. See the [changelog](../CHANGELOG.md#0319---2026-10-28) and
[KSI limitations](FEDRAMP_KSI_ASSESSMENTS.md).

Package, chart, console, Compose and MCP versions are aligned. This release adds
no dependency upgrade or database migration. Private-address framework sources
and oversized responses are rejected; operators must reconcile those errors
rather than treat them as successful collection. The install guides now name
the verified publication.

Independent human approval, exact merged-main CI, both image architectures'
vulnerability and authenticated runtime checks, and chart qualification preceded
publication. Live-provider qualification and independent mapping/workpaper
decisions remain separate dependencies; no new live-provider receipt is claimed.

## 0.3.18 release

0.3.18 is published; see the [publication receipt](#verified-0318-publication).
It includes first-run assessment/workpaper guidance, stronger synthetic workpaper
regression proof, four source-pinned OCSF observation presets, CI duration balancing
and browser navigation regression coverage, and Authlib/msgpack security updates.
It introduces no database migration or change to control evaluation, framework
mappings or review states. Package, chart, console, Compose and MCP versions are
aligned, and the install guides now name the verified publication.

Independent human approval and exact merged-main CI preceded publication. Both
image architectures passed vulnerability and authenticated runtime gates; Python
artifact hashes/provenance, anonymous Helm pull/provenance and registry visibility
were verified. Authorized live-provider checks and independent mapping or
workpaper review remain separate dependencies; no new live receipt is claimed.

## 0.3.17 release

0.3.17 is published; see the [publication receipt](#verified-0317-publication).
This release introduces no database migration or dependency upgrade.

The graph follow-up in [#1113](https://github.com/koda-ai-studio/grc-lake/pull/1113)
preserves explicit review states, exact filter hops and readable zoom, with a
visible relationship key and limits on both nodes and relationships. Its local
validation passed 46 graph checks (including mobile, light/dark and accessibility)
and 129 documentation, screenshot and release checks. The release build also
pins the PyPI description's Docker quick start to the version being packaged.
Its merged main commit `5988d77a` [passed CI in 7m27s](https://github.com/koda-ai-studio/grc-lake/actions/runs/40447456279).
The final packaging commit `96c79d6c`
[passed CI in 11m47s](https://github.com/koda-ai-studio/grc-lake/actions/runs/40449361384),
including 5m08s installing browser dependencies.

- Unattributed legacy mappings and missing review status are proposed. Reviewed
  requirements are 886/2,282 (38.8%); the mapped count remains 2,196. This is a
  correction to review credit, not a change in observed provider posture.
- Scoped endpoint and Jira evidence bindings preserve unknowns and proposed
  mappings. Candidate-focused review packets and reviewer provenance support
  human review without treating attribution as reviewer independence.
- The full synthetic console tour is recaptured with the release build,
  including graph, review, light/dark and mobile views. The README summary and
  framework coverage are regenerated from the same catalog.
- CI retains its tests and security gates while reducing redundant waits. The
  earlier frozen-source PR and main runs passed in 7m53s and 7m52s. Later runs
  took 8m14s (Docker critical path) and 13m11s (including 6m26s installing browser
  dependencies). The under-eight-minute target remains inconsistent and is
  tracked in [#1111](https://github.com/koda-ai-studio/grc-lake/issues/1111);
  browser-package cache measurements are recorded there.
- Helm OCI publication, round-trip chart-byte verification and package/OCI
  provenance join the existing Python and image gates. Artifact Hub registration
  is separate. The MCP Registry workflow publishes only after the package exists.

Required publication checks: independent approval, exact merged-main CI, version
and changelog consistency, both image architectures with vulnerability/runtime
qualification, Python artifact hashes and provenance, public Helm pull and
provenance verification, and registry visibility. A dry run does not publish.

## 0.3.16 candidate

0.3.16 is published; see the [publication receipt](#verified-0316-publication).
A correctness patch on the verified 0.3.15 release that removes a false pass. It
introduces no database migration and no safeguard or review-state change.

- **Provider benchmarks:** CIS AWS requirements are assessed only from AWS
  evidence (`aws`, `aws_config`), declared as `provider_sources` in the framework
  registry. In 0.3.15, enforced GCP org policies could pass `CIS-AWS-1.10` and
  other CIS AWS identity recommendations with no AWS evidence, because the
  identity safeguard is shared with SOC 2, ISO 27001 and NIST. Without AWS
  evidence these requirements are now `not_evaluated`. Cross-framework results
  are unchanged.
- **Coverage gaps:** AWS and GCP gap rows and AWS inventory-absence rows have their
  own assets, so a denied read or a missing CloudTrail trail no longer hides a
  failing password-policy or org-policy verdict. A source's gap still keeps the
  safeguards it binds from passing.

Release gates are unchanged: exact-main CI on the tagged commit, version
consistency, the changelog gate, and published-artifact verification.

## 0.3.15 candidate

0.3.15 is published; see the [publication receipt](#verified-0315-publication).
A security and correctness patch on the verified 0.3.14 release. It introduces no
database migration.

- **Security:** certifi 2026.10.23 removes the distrusted "emSign ECC Root CA - C3"
  and "emSign Root CA - C1" roots from the Python CA bundle used for outbound HTTPS.
  The 0.3.14 image's Python bundle still trusted them (its system CA bundle did not).
  pip moves to 26.2.2 and uv to 0.13.5 in CI and the image build.
- **GCP:** inherited organization policies are read from the effective policy, so
  constraints not set on the project produce real verdicts; verified live
  ([receipt](qualification/live/2026-10-26-gcp-effective-policy.md)).
- **Azure:** Microsoft Defender for Cloud assessment verdicts are collected and
  conservatively mapped ones bind to safeguards, so Azure moves framework results
  for the first time; verified live
  ([receipt](qualification/live/2026-10-26-azure-defender.md)).
- **Databricks:** the reader's `databricks-sql-access` entitlement is documented, and
  a live multi-chunk run is recorded
  ([receipt](qualification/live/2026-10-25-databricks.md#databricks-multichunk)).
  The connector stays Preview.

Release gates are unchanged: exact-main CI on the tagged commit, version
consistency, the changelog gate, and published-artifact verification.

## 0.3.14 candidate

0.3.14 is published; see the [publication receipt](#verified-0314-publication).
This release adds strict
Databricks result completeness and OAuth renewal, focused mapping-review packets,
and a repeatable local graph performance gate. It introduces no database migration
or dependency change.

The maintainer accepted the [bounded graph profile](benchmarks/RELEASE_PROFILE.md):
two tenants with up to 10k synthetic records each and four clients, warm p95 at most
500 ms, first/expired reads at most 5 seconds and process RSS at most 1 GiB, with
both tenants making progress under overload. The checker uses a maximum two-second
success gap to measure that progress and reports admission rejections separately.
Two initial clean-source runs and candidate `488dbc4cf7737ea3074f2d9854803c1eba1ede5c`
passed. The candidate measured about 40 ms successful warm p95, 1.15–1.18 second
first reads and 457 MiB peak RSS at 10k records per tenant. Admission rejections
remain separate, as recorded in the receipt. These results do not qualify 100k
interactive use, browser rendering or production sizing.

Local candidate checks also passed 172 targeted Python cases, console build/lint,
static/catalog validation, dependency audits and wheel-content checks. Fresh
bare wheel and source-archive installs exercised fixtures, replay, integrity,
snapshots and the local console; a separate wheel installation exercised server
startup, catalog isolation and integrity routes. Synthetic connector-to-export
qualification and all 20 control-workpaper cases passed at source `488dbc4c`.
These checks do not replace required CI or qualification of published bytes.

The content and visual pass refreshed 42 synthetic console captures and passed
96 screenshot checks; the combined public-copy, README, adoption and screenshot
suite passed 141 cases. Catalog-derived checks now guard the connector overview
counts. The README exposes the local performance profile and keeps detailed
coverage counts expandable. Desktop/mobile preview checks found no broken images
or horizontal overflow at the inspected widths; these are layout checks, not a
browser capacity qualification.

Accuracy and value changes since the candidate was opened:

- A control test is not an attestation anywhere it is reported. OSCAL
  assessment results mark a finding `satisfied` only for a framework (CCF) pass
  through reviewed mappings; the public trust summary adds attested counts and
  reads `ready` only when every requirement is attested; the CLI status summary
  adds an attested framework line. On the golden demo, OSCAL satisfied findings
  equal the three attested requirements exactly.
- Flagship connectors now bind evaluated evidence to safeguards inside the
  connector: AWS IAM, GitHub change approval, Okta and Google Workspace MFA and
  GCP organization policies. A live read-only pilot on one AWS account and this
  repository moved from no framework results to 103 failing requirements and one
  attested pass, each verified against the provider
  ([receipt](qualification/live/2026-10-26-aws-github-binding.md)).
- The maintainer approved 71 SOC 2 and ISO 27001 mappings as one recorded batch
  decision (SOC 2 59/61, ISO 27001 53/93 reviewed; 1,225 reviewed requirements in
  total). Title-theme suggestions and two requirements with open recommendations
  stay proposed.
- The golden demo reaches three honest attested ISO 27001 passes alongside its
  failures and unattested control tests.
- Databricks was re-run against a populated system audit log (928 records,
  failed requests reconciled 16/16) and stays Preview
  ([receipt](qualification/live/2026-10-25-databricks.md#databricks-populated-audit)).
- Connector plugin discovery is cached per process, and CI balances six Python
  shards by recorded time and splits console e2e in two; a full CI run fell from
  15–18 to about 9 minutes.

The [focused recovery/confidentiality packet](reviews/RECOVERY_CONFIDENTIALITY.md)
records the additional evidence needed for SOC2-A1.3 and SOC2-C1.1. The
maintainer's 2026-10-25 [batch decision](MAPPING_REVIEW.md#pending-soc-2-and-iso-review)
excluded both, so they stay proposed until those recommendations are met. Only an eligible
human reviewing the full requirement text can approve a mapping; code approval
does not substitute for that decision.

Databricks remains Preview. Synthetic regression coverage exercises malformed and
multi-chunk results, expiry, one bounded authorization retry and rate limiting.
Fresh live expiry, throttling and multi-chunk checks remain pending an authorized
workspace. The prior bounded live receipt does not establish those behaviors.

The [pilot guide](PILOT.md) separates first useful real assessments, repeat use and
accepted contributions. It adds no telemetry and reports no adoption outcome.
Its 14-day feature freeze starts at the next stable publication, with exceptions
for security, correctness, supported-workload performance and setup/documentation
repairs. Independent human review, required PR checks, exact-main CI and published
artifact/runtime verification remain release gates; this candidate section is not
a completion receipt.

## Verified 0.3.22 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/41256398524)
passed every job on source `15b461e88119715fe42762aca6478ffe8b11ed09`, after
independent human approval and merge of [#1196](https://github.com/koda-ai-studio/grc-lake/pull/1196)
and successful [exact-main CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/41255691338).
The annotated `v0.3.22` tag resolves to that commit. Publication was verified on
October 31, 2026 (November 1 UTC). Wheel and source-archive bytes match between
PyPI and GitHub; an anonymous Helm pull matches the GitHub chart asset.

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.22-py3-none-any.whl` | `0a95b131f5d5f869d85940d03e891c697013691928da61ff0d0dca1e53c82ef9` |
| `grc_lake-0.3.22.tar.gz`           | `29384fdae699d58a9ac309517139db9fa6e706f7a8d5c17daa689184014be56b` |
| `grc-lake-0.3.22.tgz`              | `657bf70a369f07dc569bf6d87828726ca7414194ce2f3b6c01635aa6e2511541` |

The image `ghcr.io/koda-ai-studio/grc-lake:0.3.22` and `latest` resolve to
`sha256:542fe99cf56c21ce9a09bd3bb1b1ae4bebdc9ee8b466acdd41739a7e7df789b3`.
Anonymous downloads verified all 21 distinct layer blobs and both image
configurations by digest. Published AMD64 and ARM64 root filesystems and runtime
configuration match the scanned and exercised images. Each architecture's
unfiltered Trivy report contains zero reported vulnerabilities, and each passed
11 authenticated runtime checks, including tenant isolation, revoked-key denial,
persistence, snapshot integrity, non-root execution and the bundled console.
These are dated synthetic checks, not TLS/IdP, provider or capacity qualification.

The chart `oci://ghcr.io/koda-ai-studio/charts/grc-lake`, version `0.3.22`, has
OCI digest `sha256:ce77081a5326ae0e68c07e56a5f0193fb231748d6eb7a9de921ec7545b25d97b`.
Wheel, source archive, chart package, chart OCI and image provenance verified
against this repository's release workflow, exact source commit and tag. The
chart renders with shipped self-hosted values. GitHub retains the SBOM and
Python/chart provenance bundles.

Fresh public-PyPI core and server/MCP installations passed their package smoke
checks outside the checkout. The published wheel is byte-identical to the
workflow wheel used for upgrade and authenticated tenant-isolation checks.
A copied 0.3.21 lake reevaluated into a corrected generation while preserving
previous generation and snapshot bytes. The wheel contains 263 console files.
The public MCP Registry lists 0.3.22. Artifact Hub still listed 0.3.21 at this
check; listing refresh is tracked separately from the verified chart publication.

The [assessment-integrity advisory](https://github.com/koda-ai-studio/grc-lake/security/advisories/GHSA-76q3-wh53-hvv2)
is published. Missing safeguard contracts still require independent review.
Million-record preparation timed out at its 30-minute limit; capacity remains
unqualified in [#910](https://github.com/koda-ai-studio/grc-lake/issues/910).

## Verified 0.3.21 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/41167894154)
passed every job on source `2aced4a393a5768d528f6ddd7d0514bcb907e488`, after
independent human approval and merge of [#1172](https://github.com/koda-ai-studio/grc-lake/pull/1172)
and successful [exact-main CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/41167239513).
The annotated `v0.3.21` tag resolves to that commit. Publication was verified on
October 31, 2026. Wheel and source-archive bytes match between PyPI and the GitHub
release; an anonymous Helm pull matches the GitHub chart asset byte-for-byte.

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.21-py3-none-any.whl` | `234aa26cdc0c13fd7e9c3f7433b933299c455079df1d7ee2b6cbd965f87e5c2a` |
| `grc_lake-0.3.21.tar.gz`           | `67a27aeec516888d23d728d69245d8cdff437d8d73516580ada747ec6226dedb` |
| `grc-lake-0.3.21.tgz`              | `e489e3959d4be7dce8f36c8aec23ddbd4529ba6f2a40a3c1b91c6c7b417145af` |

The container `ghcr.io/koda-ai-studio/grc-lake:0.3.21` and `latest` resolve to
index `sha256:1d7f75a9fa48341dfaa743ce929c9646bb6bd16cadc3c8170804df051777a582`. It contains Linux AMD64
and ARM64 images. Anonymous downloads verified every layer and configuration
blob by digest. Both published filesystems and runtime settings match the
images scanned and exercised by the release workflow. Each architecture's
unfiltered Trivy report contains zero reported vulnerabilities, and each passed
11 authenticated runtime checks, including tenant isolation, revoked-key denial,
persistence after recreation, snapshot integrity, non-root execution and the
bundled console. These are dated synthetic runtime checks, not TLS/IdP or
production-capacity qualification.

The chart `oci://ghcr.io/koda-ai-studio/charts/grc-lake`, version `0.3.21`, has
OCI digest `sha256:a439f4d4bfb224de2b594f75067840e8c30cf496638f28650bd6d8966d981542`.
Wheel, source archive, chart package, chart OCI and image provenance verified
against this repository's release workflow, exact source commit and version tag.
GitHub retains the CycloneDX SBOM and Python/chart provenance bundles. The chart
renders with the shipped self-hosted values.

The [published GitHub connector trial](qualification/live/2026-10-31-github-published.md)
collected and recollected seven records through a fresh named connection, with
provider counts, account binding and integrity reconciled. Its limited scope
does not qualify other providers.

Separate fresh PyPI installations passed the bare-core and server/MCP package
smoke checks outside the checkout. Both the public MCP Registry and Artifact Hub
list version `0.3.21`. These listing checks establish publication, not deployment
or provider qualification. Exact-main CI took 8m32s; the stable under-eight-minute
target remains open in [#1111](https://github.com/koda-ai-studio/grc-lake/issues/1111).

## Verified 0.3.20 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40635022131)
passed every job (tested-commit and version checks, build, image, chart, PyPI,
GitHub release, MCP Registry) on source `4c067dcb152a23912e0621806bba089a092ee897`,
after [#1137](https://github.com/koda-ai-studio/grc-lake/pull/1137) merged and
[exact-main CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40634152712)
passed. The annotated `v0.3.20` tag resolves to that commit. Wheel and source
archive bytes match between PyPI and the GitHub release, and an anonymous Helm
pull matched the GitHub chart asset byte-for-byte:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.20-py3-none-any.whl` | `bdd56d13f6ac7926f72b861d7d92349564351f77123ea30a066ffdfeacfe05b1` |
| `grc_lake-0.3.20.tar.gz`           | `5f77534003afdc597c9fa7855d65faad6fabfab5ee0a39032e3c847ed9692799` |
| `grc-lake-0.3.20.tgz`              | `8fe97444a39e19e883aeb82c72096628a150962731d5535bcc0e57c6a8eb9e13` |

The image `ghcr.io/koda-ai-studio/grc-lake:0.3.20` resolved to index
`sha256:32b9144cd373193232eff1d209852b216340b33b3f2b3548c26ab4d1cfa6ecc4`,
containing `linux/amd64` and `linux/arm64`. The chart
`oci://ghcr.io/koda-ai-studio/charts/grc-lake`, version `0.3.20`, has OCI digest
`sha256:347378cf98071109fe2393657c7325af0d8ec836063654d0570bc0c0a89005e6`.
Wheel, source archive, chart-package, chart-OCI and image attestations verified
with `gh attestation verify` for the `koda-ai-studio` owner. GitHub retains the
CycloneDX SBOM and Python/chart provenance bundles.

A fresh PyPI installation of `grc-lake[server]==0.3.20` outside the checkout
reported version 0.3.20, loaded the golden fixture, served the bundled console
and answered an investigation-graph request. This is a smoke check, not a
qualification of TLS, an IdP, live providers or production capacity.

The public MCP Registry lists `io.github.koda-ai-studio/grc-lake` at version
`0.3.20`. Artifact Hub still reported chart version `0.3.19` when this receipt
was recorded; its indexing runs on its own schedule. Exact-main CI completed in
9m10s, so the under-eight-minute target remains open in
[#1111](https://github.com/koda-ai-studio/grc-lake/issues/1111).

## Verified 0.3.19 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40612991004)
passed on source `567620f8884f6477610b1a8cce5606b89f6ed971`, after independent
human approval of [#1132](https://github.com/koda-ai-studio/grc-lake/pull/1132)
and successful [exact-main CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40612042954).
The annotated `v0.3.19` tag resolves to that commit. Wheel and source archive bytes
match between the release build, PyPI and GitHub:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.19-py3-none-any.whl` | `6ebfbe80c77bccaca971ebd81f37502a768faa250bda8d95379baeaa15b9900c` |
| `grc_lake-0.3.19.tar.gz`           | `78bb8dd4eb602c0cdff0a163c3189f173b32152fde05fec0357ea4524cbce2d8` |
| `grc-lake-0.3.19.tgz`              | `39d95dd6515928237b151ff3e764d74bfb10d73f970512d962c79170547860ea` |

The anonymous image lookup resolved to index
`sha256:7b96acb9ede4ae65b14a82dd7260543623a4952af0592be761b40868df40c994`,
containing `linux/amd64` and `linux/arm64`. Both architectures passed dependency,
vulnerability and authenticated runtime checks before publication. Both retained
scan reports contained zero reported vulnerabilities at release time. Each
architecture passed 11 synthetic authorization, tenant-isolation, persistence,
integrity, non-root and bundled-console checks. A fresh anonymous pull of the
published ARM64 image also passed those checks locally. These checks do not
qualify TLS, an IdP, live providers or production capacity.

The chart `oci://ghcr.io/koda-ai-studio/charts/grc-lake`, version `0.3.19`,
has OCI digest `sha256:0cc68da9fd16ab6bfa8d6798a67868efb0da254523bed053c66638e36873c360`.
An anonymous Helm pull matched the GitHub chart asset byte-for-byte. Wheel,
source archive, image, chart-package and chart-OCI attestations verified against
the release workflow, exact source commit and tag using `gh attestation verify`.
GitHub retains the CycloneDX SBOM and Python/chart provenance bundles.

The wheel contains 263 console files and its catalogs. A fresh PyPI installation
outside the checkout, with no optional dependencies, passed fixture loading,
replay/idempotency, evidence integrity, assessment snapshots and console/API smoke
checks. A draft exported from the unchanged historical control-assurance fixture
verified against the content digest retained at export. Its verifier explicitly
reported `hash_consistency_only; review identity requires server record`; no
workpaper approval or live-provider qualification was recorded.

The PyPI description pins its Docker quick start to `v0.3.19`. The public MCP
Registry lists `io.github.koda-ai-studio/grc-lake` at version `0.3.19` as active
and latest. The public [Artifact Hub listing](https://artifacthub.io/packages/helm/grc-lake/grc-lake)
now reports chart and application version `0.3.19` for the registered repository.
Registry indexing and verified publisher ownership do not qualify the deployment.
Exact-main CI completed in 8m12s, so the consistently-under-eight-minute
target remains open in [#1111](https://github.com/koda-ai-studio/grc-lake/issues/1111).

## Verified 0.3.18 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40577845071)
passed on source `1c1a702f72b18d1be71087725230a4a3f762cc45`, after independent
human approval of [#1122](https://github.com/koda-ai-studio/grc-lake/pull/1122)
and successful [exact-main CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40576425894).
The annotated `v0.3.18` tag resolves to that commit. Wheel and source archive bytes
match between the release build, PyPI and GitHub:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.18-py3-none-any.whl` | `9d68830506f55345629ed2732f2d44c25e2e17b19d8b3046fa8ab7de3518eed6` |
| `grc_lake-0.3.18.tar.gz`           | `a1cee600b8d2d8789adb15716fdf16441fcf25d5f1884752a9a5b26aefe8b151` |
| `grc-lake-0.3.18.tgz`              | `08dc5d623449d54d7c519cf491e13eda33492a12305a049e1b00b1cd0c33cba5` |

The anonymous image pull resolved to index
`sha256:574df5d3b24ff97da3242338113dc7bf9e00a7b706cd207e04513fbdfa9adda9`,
containing `linux/amd64` and `linux/arm64`. Both architectures passed dependency,
vulnerability and authenticated runtime checks before publication. The retained
scan reports contained zero reported vulnerabilities at release time. A fresh
anonymous pull of the published ARM64 image also passed non-root, authorization,
two-tenant isolation, snapshot integrity and persistence-after-recreation checks.
These synthetic checks do not qualify TLS, an IdP, live providers or capacity.

The chart `oci://ghcr.io/koda-ai-studio/charts/grc-lake`, version `0.3.18`,
has OCI digest `sha256:d6bcdce62de8d3e245c42cd86d02701a9b0daacfd8db8deb72a037bf0f6bee1d`.
An anonymous Helm pull matched the GitHub chart asset byte-for-byte. Wheel,
source archive, image, chart-package and chart-OCI attestations verified against
the release workflow, exact source commit and tag using `gh attestation verify`.
GitHub retains the CycloneDX SBOM and Python/chart provenance bundles.

The wheel contains 263 console files and its catalogs. A fresh PyPI installation
outside the checkout, with no optional dependencies, passed fixture loading,
replay/idempotency, evidence integrity, assessment snapshots and console/API smoke
checks. A draft exported from the unchanged historical control-assurance fixture
verified against the content digest retained at export. Its verifier explicitly
reported `hash_consistency_only; review identity requires server record`; no
workpaper approval or live-provider qualification was recorded.

The PyPI description pins its Docker quick start to `v0.3.18`. The public MCP
Registry lists `io.github.koda-ai-studio/grc-lake` at version `0.3.18` as active
and latest. Artifact Hub registration remains separate from Helm OCI publication.
Main CI passed in 9m02s, with browser jobs finishing 22 seconds apart; the
under-eight-minute target remains tracked in [#1111](https://github.com/koda-ai-studio/grc-lake/issues/1111).

## Verified 0.3.17 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40450498738)
passed on source `96c79d6c2b86a9915e276a3d712cb9e2620b123b`, after independent
human approval and successful [exact-main CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40449361384).
The annotated `v0.3.17` tag resolves to that commit. The wheel and source archive
match byte-for-byte between the release build, PyPI and GitHub:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.17-py3-none-any.whl` | `b48724f91e750b53dbf69623b2fee0cf1ab13f4adb388e37f21ee56b4355812a` |
| `grc_lake-0.3.17.tar.gz`           | `1db437a7224ca87aa7b0bca7648deda3273f5439b3e45527553faccb17e71ce6` |
| `grc-lake-0.3.17.tgz`              | `ab2ff15d98ce45fe349057df4e6760aaf4d149d7f6fed32e1f7bdf29344db66e` |

The public image `ghcr.io/koda-ai-studio/grc-lake:0.3.17` has index digest
`sha256:7d5567f39031965f3311005a847c67e5068e2fd29ddbaeb591a18a2d27814e57`
and contains `linux/amd64` and `linux/arm64`. Both architectures passed the
release vulnerability and authenticated runtime gates before publication.
The public chart `oci://ghcr.io/koda-ai-studio/charts/grc-lake`, version `0.3.17`,
has OCI digest `sha256:aaaa6acf4eb50c2510ae0b26cf0cb281d62beb05f272a103bcdb33bb94c7be76`.
An anonymous Helm pull matched the GitHub chart asset byte-for-byte. Wheel,
image, chart-package and chart-OCI attestations verified against the release
workflow, exact source commit and tag using `gh attestation verify`.
GitHub also carries the CycloneDX SBOM and Python/chart provenance bundles.
Artifact Hub registration remains separate from this public OCI publication.

The installed release wheel includes 263 console files and its catalogs. A fresh
installation outside the source checkout loaded the synthetic golden fixture,
verified a new assessment snapshot and exported both OSCAL documents. Assessment
results contained exactly three `satisfied` requirements, matching the three
attested framework results. The console graph page and health route responded
successfully. The graph kept `SOC2-CC6.1` at `ccf_status=not_evaluated`, with zero
reviewed and one proposed safeguard, while preserving its failing control test.
These are synthetic runtime checks, not new live connector qualification.

The PyPI description pins its Docker quick start to `v0.3.17`. The public MCP
Registry lists `io.github.koda-ai-studio/grc-lake` at version `0.3.17`.

## Verified 0.3.16 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40362446730)
passed on source `15a12a0a0c82dc04d3c385f2f7b46f48c445404f`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40359572087).
The `v0.3.16` tag resolves to that commit. Wheel and sdist bytes match between
PyPI and the GitHub release:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.16-py3-none-any.whl` | `8b0bb7085bb8a7703068d82eda1f3707ae2612ad58b9dcfdf386a9ae4d359ebc` |
| `grc_lake-0.3.16.tar.gz`           | `0db3e57cc9c4b0f55aed43bf7a9008b0e387a3332806a32da1f9d7d167902393` |

The Python provenance for the wheel and the registry image attestation verify
against this repository with `gh attestation verify`. The multi-platform image
index `ghcr.io/koda-ai-studio/grc-lake:0.3.16` (digest
`sha256:97ec2ac1639cd6ff118b99ee4e5fa4d74757e342030fd745d0a1b69baf7c9de9`)
publishes `linux/amd64` and `linux/arm64`. The GitHub release carries the wheel,
sdist, CycloneDX SBOM and Sigstore provenance.

A fresh installation of `grc-lake[server]==0.3.16` from PyPI loaded the golden
fixture, printed the framework summary (3 attested, 0 failing), exported OSCAL
assessment results with exactly the three attested requirements `satisfied`, and
verified a new assessment snapshot. Its framework registry declares CIS AWS
`provider_sources` as `aws` and `aws_config`, and the provider-scope tests, run
against the installed package, show GCP-only evidence leaving `CIS-AWS-1.10`
`not_evaluated` while AWS evidence still fails it. The hosted demo was redeployed
from the release commit.

## Verified 0.3.15 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40339679764)
passed on source `26c75d8aed33d92ce6987d824a1fd7d656953857`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40337907024).
The `v0.3.15` tag resolves to that commit. Wheel and sdist bytes match between
PyPI and the GitHub release:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.15-py3-none-any.whl` | `66dd576a8189ad63f0d82b267b948d53067ead16e87a4800fff06e86d6a4f002` |
| `grc_lake-0.3.15.tar.gz`           | `1c74bbfdf0df1c48c44fb0385a39de577fe60c222a14cf6fc39651038879bef3` |

The Python provenance for the wheel and the registry image attestation verify
against this repository with `gh attestation verify`. The multi-platform image
index `ghcr.io/koda-ai-studio/grc-lake:0.3.15` (digest
`sha256:e990ca316739f66e2bee04752aaff41b6528f031e69064cf88500e7f5c81cfc9`)
publishes `linux/amd64` and `linux/arm64`. The GitHub release carries the wheel,
sdist, CycloneDX SBOM and Sigstore provenance.

The image's Python environment has certifi 2026.10.23, and its bundle no longer
contains "emSign ECC Root CA - C3" or "emSign Root CA - C1"; the only remaining
emSign entry is "emSign Root CA - G1". The image ships no pip.

A fresh installation of `grc-lake[server]==0.3.15` from PyPI loaded the golden
fixture, printed the framework summary (3 attested, 0 failing), exported OSCAL
assessment results with exactly the three attested requirements `satisfied`, and
verified a new assessment snapshot. The hosted demo was redeployed from main,
which contains the release commit.

## Verified 0.3.14 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40269042080)
passed on source `8b2500cf568d9b4544a55f4aca67045b68bdb2d8`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40266471319).
The `v0.3.14` tag resolves to that commit. The full Python suite on main recorded
6,948 passed and 86 skipped tests, with no failures, before the last two merges,
whose suites passed in CI. Wheel and sdist bytes match between PyPI and the
GitHub release:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.14-py3-none-any.whl` | `a90571252226c9ecaacec965349923181a114f6accda0fbae52d8cc700dbe13f` |
| `grc_lake-0.3.14.tar.gz`           | `f1fc0b9408c87b3cef8a4429d50cc8456ff981969ae77d0c6271d84c001c5bb4` |

The Python provenance for the wheel and the registry image attestation verify
against this repository with `gh attestation verify`. The multi-platform image
index `ghcr.io/koda-ai-studio/grc-lake:0.3.14` (digest
`sha256:de002d4573327082d134367d7b6dea20c9952f28449e29731e71d03fa20139a3`)
publishes `linux/amd64` and `linux/arm64`. The GitHub release carries the wheel,
sdist, CycloneDX SBOM and Sigstore provenance.

A fresh installation of `grc-lake[server]==0.3.14` from PyPI loaded the golden
fixture, printed the framework summary (3 attested, 0 failing), exported OSCAL
assessment results with exactly the three attested requirements `satisfied`, and
verified a new assessment snapshot. The hosted demo was redeployed from the same
commit and shows "11 of 41 control tests · 3 attested".

## 0.3.13 qualification

Framework and repository maps now carry the same CCF result and reviewed/proposed
mapping counts as Controls and Investigation. A missing framework result is not
shown as a passing control. Regression coverage includes `SOC2-CC6.8`, whose
control test passes while its proposed-only framework mapping is not evaluated.

The [October 25 capacity measurements](benchmarks/INVESTIGATION_CACHE.md#october-25-2026-sustained-traffic-expiry-and-process-memory)
add sustained hot/cold tenant traffic, idle expiry, forced eviction, 100k cache
comparison and simultaneous worker RSS. The 100k models were not retained by the
128 MiB cache. The later 10k local profile has maintainer acceptance; production capacity budgets remain outstanding.

Synthetic connector-to-export and 20 control-workpaper cases passed on source
`6268edbdc625f894859837dc6fabdb8376e54f32`. These checks do not approve pending
SOC 2/ISO mappings or qualify live providers. Use the bounded review-packet
procedure in [Mapping review](MAPPING_REVIEW.md) for human decisions.

The release also includes source-account-scoped OCSF event IDs, missing-subject
rejection and partial mapping gaps. Preserve existing evidence and re-ingest OCSF
source history into a fresh lake; stored raw rows do not acquire the new identities
through pipeline replay alone. There are no new database migrations or dependencies.

The [Databricks trial receipt](qualification/live/2026-10-25-databricks.md) records
eight synthetic rows and two unknown summaries from an empty audit log. It found
and fixed bootstrap response-field compatibility and empty-window verdicts.
Databricks remains Preview; the trial does not qualify real audit coverage,
production capacity, multi-chunk results, throttling or credential expiry.

These changes are included in v0.3.13. The publication checks below are separate
from provider qualification, human mapping decisions and production capacity.

## Verified 0.3.13 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40217572156)
passed on source `3b1a2c5a557515e7bab8a9a02d0c00f3a18d359e`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40216581845).
The `v0.3.13` tag resolves to that commit. Main's Python suites recorded 6,817
passed and 86 skipped tests, with no failures; browser and container gates also passed.
Wheel and sdist bytes match between PyPI, GitHub and the workflow build:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.13-py3-none-any.whl` | `cae6bb5524c8d041496754bf4cf575bdbd7f60e86ebf46fe7406c241b2f3a3d4` |
| `grc_lake-0.3.13.tar.gz`           | `303d5b2dfbe54b4d21f3f9063ea7f4c8f80f812bf5480c8a80acf7092fbdfa36` |

The Python provenance for both files and the registry image attestation verify
against this repository, the release workflow, the source commit and `v0.3.13` tag.
Fresh bare installations from the wheel and sdist passed fixture loading, replay,
integrity, snapshots and local console checks. The wheel also passed server-mode
package/catalog isolation, console HTTP and integrity-route checks with frozen
server dependencies. These installations used the workflow files whose bytes
were subsequently matched to both published distributions.

The anonymously readable multi-platform index is
`sha256:865e1cc7e4f19974eb9d716b4c1ccb89ee7e12fa381f41afc7eb0128cb445b52`
(also `latest`):

- AMD64: `sha256:9eda591c74b22dcffaf568949b016c12de110f92c4aca8e5a892674e8640d362`
- ARM64: `sha256:1e6436289af5db6ce0012faba4826af12bd06580f803a3b86d3419e96c612215`

Both public manifests and configurations hash-verify, name version 0.3.13 and the
release source commit, and retain a non-root runtime user. The release workflow
qualified both architectures with 11 authenticated checks covering tenant isolation,
authorization, key revocation, snapshots, persistence, integrity and console serving.
Its full Trivy 0.70.0 reports contain **zero reported vulnerabilities** for both
architectures. These checks do not qualify production scale, live providers, TLS
or an IdP, and a zero-findings scan does not establish the absence of unknown flaws.

## Verified 0.3.12 publication

0.3.12 changed only the published package description: README links and screenshots
were pinned to the release tag so the PyPI project page renders them. Apart from
version strings, its code, dependencies and system packages match 0.3.11.

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40164154790)
passed on source `73e9b5014b31bde75bcf42ae664bb97709e493ad`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40160747032).
The `v0.3.12` tag resolves to that commit. Wheel and sdist bytes match between PyPI,
GitHub and the workflow build:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.12-py3-none-any.whl` | `4b3c500bbb79a6325dc08b662efb6f07e1279c5a70c4ff0ccf640f36360e1ac9` |
| `grc_lake-0.3.12.tar.gz`           | `03d15bda11b4e1f28d9aaf373063c669bdfb8d82cab61d03e6361b33fd900839` |

The Python provenance for both files and the registry image attestation verify
against this repository, the release workflow, the source commit and the `v0.3.12`
tag. The PyPI description contains no repository-relative links; all 53 tag-pinned
image and document URLs returned 200. A base-only PyPI installation passed fixture
loading, pipeline replay, integrity verification, snapshots and local-mode console
and API requests. `uvx --from "grc-lake[server]==0.3.12" grc-lake demo` served the
console and core API, reported 0.3.12, and stopped cleanly on interrupt.

The anonymously readable multi-platform index is `sha256:dbf6eebf5093ca676a9b433d01733603dcca335432d0ecb228b80f77d78488e4`
(also `latest`):

- AMD64: `sha256:d2bea4764e6093604dbec9d71e2163c6cc67221a58105a6dd223fc48acf47c96`
- ARM64: `sha256:f000497786d4e39a277ab9925f022e8e72d7d3b6462f19a2a97240ace3a71957`

Both published platform images have the same filesystem layers and runtime settings
as the images qualified by the release workflow; only OCI metadata labels differ, and
they name version 0.3.12 and the source commit. Each architecture passed the
authenticated two-tenant release smoke. The workflow's Trivy reports and an
independent Trivy 0.69.3 scan of the published tag report **zero vulnerabilities**
for both architectures. This is a dated scan result for recognized components, not
proof that application behavior or unknown vulnerabilities are absent.

## Verified 0.3.11 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/40155762881)
passed on source `dc8aaef4833a7fe8530f536460b899dd2b33582f`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/40155244804).
The `v0.3.11` tag resolves to that commit. An earlier `v0.3.11` tag on `2493e8e4`
was refused by the tested-commit gate after a new brotli advisory failed main's image
policy; nothing was built or published from it, and the tag was moved after the fix.
Wheel and sdist bytes match between PyPI, GitHub and the workflow build:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.11-py3-none-any.whl` | `3b8acc698d6bf3e7d53dc26b9aa6055a0757aa51f658349cef0cdb5b675b13ba` |
| `grc_lake-0.3.11.tar.gz`           | `cc0779e6e9a8deed558fa131fe9d7acedb4ef05687a2198ce2388dce62ec0a55` |

The Python provenance for both files and the registry image attestation verify
against this repository, the release workflow, the source commit and the `v0.3.11`
tag. A base-only PyPI installation (no SQLAlchemy) passed fixture loading, pipeline
replay, integrity verification, snapshots and local-mode console and API requests.
`uvx --from "grc-lake[server]==0.3.11" grc-lake demo` installed from PyPI, served
the console and core API on loopback, reported 0.3.11, and stopped cleanly on
interrupt.

The anonymously readable multi-platform index is `sha256:157e65bc9f7025d24bd688acd9a3e1fd239f8cb1b8d708c7d6c6b9918ebd3480`
(also `latest`):

- AMD64: `sha256:2a6cc1c17140a54cdbc36a2572351c9df39a15b03f5e34cd70c0d6152d46edfc`
- ARM64: `sha256:2abaa14ac692197d8e307299c0ac8453c6423c5b92ece058947a38cf1e35b3c9`

Both published platform images have the same 11 filesystem layers (21 unique across
platforms) and runtime settings as the images qualified by the release workflow;
only OCI metadata labels differ, and they name version 0.3.11 and the source commit.
Each architecture passed the authenticated two-tenant release smoke. The workflow's
full Trivy reports contain **zero reported vulnerabilities** across 29 Wolfi and
105 Python packages, and an independent Trivy 0.69.3 scan of the published tag
also reported zero for both architectures. This is a dated scan result for
recognized components, not proof that application behavior or unknown
vulnerabilities are absent.

The [live console demo](https://koda-ai-studio.github.io/grc-lake/) serves the
0.3.11 build from recorded synthetic responses. These checks do not qualify live
providers, TLS, an IdP, production capacity or a deployment.

## Known 0.3.10 package limitation

The published bare installation (`pip install grc-lake==0.3.10`) imports SQLAlchemy
when running the local evidence pipeline, even without a configured application
database. Fixture loading and pipeline evaluation therefore fail with
`No module named 'sqlalchemy'`. Install `grc-lake[server]==0.3.10` as a workaround;
the documented server and container paths pass the qualification checks below.
Fixed in 0.3.11, including local-mode serving and a base-only installed-wheel
gate; the published 0.3.10 bytes are unchanged.

Existing `trustops-security-data-lake` releases remain available under their
original PyPI name. Use a fresh Python environment when moving between distributions
because they own overlapping module files. Legacy CLI aliases and Python imports
remain supported. Local deployment remains supported; distributed mode remains
opt-in and requires the [migration and recovery procedures](DISTRIBUTED.md).
Upgrading from 0.3.2 requires signing secrets of at least 32 bytes and, for SAML
deployments, non-deprecated IdP signature and digest algorithms. Existing browser
sessions must sign in again. See [deployment](DEPLOYMENT.md) and
[server authentication](SERVER_AUTH.md).

## Verified 0.3.10 publication

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/39790934886)
passed on source `60d1b6a0292ab2e2ec4084082e2e15201a7d31cf`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/39787177686)
and [release qualification](https://github.com/koda-ai-studio/grc-lake/actions/runs/39787278141).
The `v0.3.10` tag resolves to that commit. Wheel and sdist bytes match between
PyPI, GitHub and the workflow build:

| Artifact                           | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.10-py3-none-any.whl` | `c2d0f1b2e05c2a3675ed21a0ab2cd388660161c77ece9a331245bace42e2ca3b` |
| `grc_lake-0.3.10.tar.gz`           | `9b6a05adc64bfd9a9099633e4b3b3e68b4581187f61d8aef8d5f5dbadb11c4bb` |

The retained Python provenance bundle and registry image attestation verify
against this repository, release workflow, source commit and `v0.3.10` tag.
An isolated hash-locked PyPI wheel installation with server dependencies passed
catalog, console redirect and integrity-route checks; an installation built from
the published sdist passed those checks too.

The anonymously readable multi-platform index is `sha256:8bfc359318a4c1e9aeff54dd14c0d050a7e694c057eb57a2f3df6facdd5f0ea5`:

- AMD64: `sha256:5b5fe015f607e58add4a655fc79dbe94b92118a5cd8e44725e2dd2755b7c3a09`
- ARM64: `sha256:03129c39b957f39dda9bcf72083d113b1f2f3a8da9eae172497ee27107b9ec4a`

Both platform manifests, configurations and all 21 unique filesystem layers
were fetched anonymously and hash-verified. Filesystems and runtime settings
match the images qualified by the release workflow. Each architecture passed
11 authenticated checks covering tenant isolation, authorization, key revocation,
snapshot access and integrity, persistence after recreation, the bundled console
and non-root execution. Published-image probes also passed on an ARM host, with
AMD64 emulated. The Compose demo retained its seed and posture after recreation.

Each full Trivy report contains **zero reported vulnerabilities** across 29 Wolfi
and 111 Python packages. This is a dated scan result for recognized components,
not proof that application behavior or unknown vulnerabilities are absent.

Extended synthetic checks exercised 352 distinct console cases across the main
run and targeted follow-ups, including offline HTML reports with JavaScript on
and off and an authenticated evidence-request write. Some console cases mock
provider responses. Local CLI checks with server dependencies covered replay,
evidence-hash stability, snapshots, framework and OSCAL exports, and rejection
of tampered evidence. These checks do not qualify live providers, TLS, an IdP,
production capacity or a deployment.

## Verified 0.3.9 publication

Version 0.3.9 adds SSO signing-key strength checks, exact OIDC issuer and audience
binding, and a bounded TLS endpoint checker. Weak IdP keys and shared-secret
ID-token signing must be replaced before upgrading; see [server authentication](SERVER_AUTH.md).

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/39160555436)
passed on source `f7c9256fc94488338e2f49e3bc8d6f52b6939392`, after that exact
main commit [passed CI](https://github.com/koda-ai-studio/grc-lake/actions/runs/39148426622)
and [release qualification](https://github.com/koda-ai-studio/grc-lake/actions/runs/39148736277).
The `v0.3.9` tag resolves to that commit. Published wheel and sdist hashes match
between GitHub, PyPI, and the release build:

| Artifact                          | SHA-256                                                            |
| --------------------------------- | ------------------------------------------------------------------ |
| `grc_lake-0.3.9-py3-none-any.whl` | `e88d7660fa44653df51c85a84aef509c8706e4fb536d5f95a5899f9a1494c480` |
| `grc_lake-0.3.9.tar.gz`           | `1d7bacfd7c754d9e91cedc428333dc034272728c92519793132abd06f529ee68` |

The retained signed Python bundle and image provenance verify against this
repository, release workflow, source commit, and `v0.3.9` tag. A fresh hash-locked
PyPI wheel installation passed package, catalog, console and integrity-route
checks outside the checkout.

The anonymously readable multi-platform index is `sha256:e4a2b2d0049221f34c6009e82a70cabacbc440870a0284933a4588951fdf5f89`:

- AMD64: `sha256:e6dcba4dc6e581305911de797629e0e1056494385c2c4e1ede93a68a7525d00f`
- ARM64: `sha256:084072cc7fb5bc42b809d374aa97c2baea6abf77b3313e17440bfecb5911529f`

Every platform manifest, configuration and compressed layer was fetched anonymously
and hash-verified. Published filesystem layers and runtime configuration match the
images scanned and probed by the release workflow. Both architecture runtime
receipts pass authentication, tenant isolation, revocation, persistence, snapshot
integrity, bundled console and non-root checks. AMD64 and emulated ARM64 were
qualified on the hosted runner; these checks do not establish production capacity,
live IdP behavior, or production proxy configuration.

Both full image scans contain **zero reported vulnerabilities** in the recognized
29 Wolfi and 110 Python packages per architecture. This is a dated scanner result,
not proof that every component or application behavior is free of vulnerabilities.

## Verified 0.3.8 publication

[Package hashes, image digests and verification scope](https://github.com/koda-ai-studio/grc-lake/blob/f7c9256fc94488338e2f49e3bc8d6f52b6939392/docs/RELEASE_READINESS.md#verified-038-publication)
remain available in the historical record. Both image scans reported zero vulnerabilities in recognized packages.
These results describe those release bytes and do not qualify later builds.

## Verified 0.3.7 publication

[Package hashes, image digests and verification scope](https://github.com/koda-ai-studio/grc-lake/blob/f7c9256fc94488338e2f49e3bc8d6f52b6939392/docs/RELEASE_READINESS.md#verified-037-publication)
remain available in the historical record. Each image scan retained 26 MEDIUM and 10 LOW findings, including advisories older than 60 days.
These results describe those release bytes and do not qualify later builds.

## Verified 0.3.6 publication

[Package hashes, image digests and verification scope](https://github.com/koda-ai-studio/grc-lake/blob/f7c9256fc94488338e2f49e3bc8d6f52b6939392/docs/RELEASE_READINESS.md#verified-036-publication)
remain available in the historical record. Each image scan retained 44 HIGH findings across eight CVEs.
These results describe those release bytes and do not qualify later builds.

## Verified 0.3.5 publication

[Package hashes, image digests and verification scope](https://github.com/koda-ai-studio/grc-lake/blob/f7c9256fc94488338e2f49e3bc8d6f52b6939392/docs/RELEASE_READINESS.md#verified-035-publication)
remain available in the historical record. Each image scan retained 44 HIGH findings across eight CVEs.
These results describe those release bytes and do not qualify later builds.

### Historical 0.3.4 receipt

The [0.3.4 publication record](https://github.com/koda-ai-studio/grc-lake/blob/f7c9256fc94488338e2f49e3bc8d6f52b6939392/docs/RELEASE_READINESS.md#historical-034-receipt)
retains its workflow, source commit, image digest and verification scope.

## Assessment and recovery qualification

The assessment contract separates execution, publication, control verdicts and
exports. Queued evaluations and snapshots call shared application services and
retain authorized result receipts. A lost completion response remains recoverable
when its receipt was committed; no receipt authorizes automatic replay. Local
publication and receipt persistence have a documented crash gap. See the
[assessment application contract](ASSESSMENT_APPLICATION_CONTRACT.md).

The required built-image Docker gate exercises coordinated backup recovery with
PostgreSQL and SeaweedFS S3. It stops writers, captures the database and all retained
object references, removes its original disposable stores and scratch volumes,
then restores into fresh stores. The report verifies revision identities, evidence
hashes, snapshot chains, operation receipts, corrupt-backup rejection and tenant
isolation. Match the retained report's application image digest to the intended
candidate; an older successful run is not evidence for a newer image.

Read-only inspection enforces object, attempted-byte and scheduling budgets;
failed integrity checks consume the download allowance. Lease loss stops pending
upload/publication work, with database fencing remaining authoritative. These
checks qualify the tested single-host synthetic scenario, not production RPO/RTO,
replicated storage, automatic failover or live-provider accuracy. See
[distributed qualification](DISTRIBUTED.md#qualification-backup-restoration).

## Release gates

A source test, successful CI run, published artifact, and authenticated deployment
are separate evidence. Run the checks below on the final revision; publish only
when its required CI checks pass.

| Gate                  | Verification                                                                                            | Required outcome                                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Version alignment     | `uv run pytest -q tests/test_release_version_consistency.py`                                            | Python package, lockfiles, console, chart, and changelog agree; workflow actions are SHA-pinned and every job has a timeout |
| Core contracts        | `uv run pytest -q`                                                                                      | Correctness, collection failure, generation integrity, auth, and tenant-boundary tests pass                                 |
| Public artifacts      | `uv run pre-commit run --all-files` and `make validate validate-doc-images validate-brand`              | Valid catalogs, references, branding, and secret checks                                                                     |
| Console               | `npm --prefix app/web run lint`, `npm --prefix app/web run typecheck`, `npm --prefix app/web run build` | A bundled static console with no lint or type errors                                                                        |
| Browser interactions  | `bash tools/run_e2e_console.sh`                                                                         | Dashboard, links, disclosures, accessible interactions, and responsive layouts pass against synthetic fixtures              |
| Dependency security   | `make pip-audit npm-audit`                                                                              | No audit-blocking vulnerabilities in the resolved dependencies                                                              |
| Image vulnerabilities | CI `docker-build` job (Trivy)                                                                           | No HIGH/CRITICAL finding, or fixable MEDIUM finding, in the built image                                                     |
| Packaging             | `make release-build`                                                                                    | A clean `dist/`; wheel verification confirms that the console and required runtime assets are included                      |
| Deployment templates  | `make deploy-check`                                                                                     | Helm rendering and Terraform validation pass; no resources are provisioned                                                  |
| Changelog             | A `## <version> - <date>` section in `CHANGELOG.md`                                                     | The section has entries, `## Unreleased` has none, and the section becomes the GitHub release notes                         |
| Publication           | Version tag on a main commit whose `ci` run passed                                                      | GitHub, PyPI, and container publication jobs succeed                                                                        |
| Published artifacts   | Fresh install and container smoke checks; `gh attestation verify`                                       | Version, bundled console, health, authenticated authorization, persistence, and integrity checks pass; provenance verifies  |

A branch merge alone does not publish a release. On a `v*` tag, the release
workflow enforces these gates before anything is published:

1. **Tested commit.** The tagged commit must be on `main`, and the `ci`
   workflow's latest main-push run must have concluded `success` for that exact SHA.
   An older green run or a PR-only run does not satisfy this gate. A tag pushed while
   CI is still running waits for it (up to 40 minutes); a tag on an unmerged or
   failing commit stops the release.
2. **Version.** The tag must equal the version in `pyproject.toml`,
   `Chart.yaml` (`version` and `appVersion`), `app/web/src/lib/brand.ts`, and
   `app/web/package.json`, and `CHANGELOG.md` must have a `## <version>` section.
3. **Build.** The console is built, then the wheel and sdist with `uv build`
   (uv pinned to the same version as the Dockerfile) and a bounded setuptools.
   `tools/verify_wheel.py` checks the wheel. Docker and console CI use Node 22 LTS;
   upgrade that major together after checking the [Node release schedule](https://nodejs.org/en/about/previous-releases).
4. **Both image architectures.** AMD64 and ARM64 are built and loaded separately.
   Installed dependency checks, Trivy scans and authenticated tenant-isolation /
   persistence probes must pass before the multi-platform image is pushed. Any
   HIGH/CRITICAL finding, or fixable MEDIUM finding, blocks publication. ARM64 runtime
   qualification on the AMD64 runner uses emulation.
5. **Publication order.** PyPI waits for the image job, including its checks and
   provenance publication. An image failure cannot leave a new Python version
   published first. Registry publication is not transactional: a later PyPI failure
   can still leave the qualified container available. Verify the final published
   digests and packages separately.

What each release publishes:

| Artifact                      | Where                      | Supply-chain evidence                                                                                                |
| ----------------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Wheel and sdist               | PyPI (trusted publishing)  | SLSA build provenance attestation; PyPI publish attestations                                                         |
| Container image               | `ghcr.io/<owner>/grc-lake` | BuildKit provenance (`mode=max`) and SBOM attestations; a GitHub build provenance attestation pushed to the registry |
| CycloneDX SBOM (`*.cdx.json`) | GitHub release             | The locked Python runtime dependencies (base plus the extras the image installs), generated by `uv export`           |
| Release notes                 | GitHub release             | This version's `CHANGELOG.md` section, followed by GitHub's generated PR list                                        |

Image tags are the exact version, `<major>.<minor>`, and `sha-<short>`. `latest`
moves only for a stable tag; a prerelease such as `v1.0.0-rc.1` never updates it.

Verify artifacts against the identity that signed that release. Releases through
0.3.1 were published from `msaad00/grc-lake`; a repository redirect does not
rewrite their signing certificates or move their GHCR package. Version 0.3.2 was
published from `koda-ai-studio/grc-lake`. Use that repository
and the exact artifact digest when verifying 0.3.2 or a later release.

```bash
# Historical 0.3.1 image: fetch the signed bundle directly from the registry.
gh attestation verify \
  oci://ghcr.io/msaad00/grc-lake@sha256:d8cd294bbe5b761ab98f38931657711b1aa94edc08d7687b757d4973a89d7625 \
  --repo msaad00/grc-lake --bundle-from-oci \
  --signer-workflow msaad00/grc-lake/.github/workflows/release.yml \
  --source-digest 62360213113726240b89c8e00769311768bcd3a8

# For a future release published from the current repository:
gh attestation verify grc_lake-<version>-py3-none-any.whl --repo koda-ai-studio/grc-lake

# Releases using bundle retention also attach python-provenance.sigstore.json.
# Download it from the same release as the wheel/sdist, then verify each file:
gh attestation verify grc_lake-<version>-py3-none-any.whl \
  --bundle python-provenance.sigstore.json --repo koda-ai-studio/grc-lake \
  --signer-workflow koda-ai-studio/grc-lake/.github/workflows/release.yml \
  --source-digest <release-commit> --source-ref refs/tags/v<version>
```

The workflow retains the original signed Python bundle as a `python-provenance`
Actions artifact before publishing to PyPI, then attaches it to the GitHub
release. Missing or empty bundle output stops publication. The bundle stays
outside `dist/` and is not uploaded to PyPI as a distribution. It covers both the
wheel and sdist; run verification for each. This provides an independent retrieval
path for future releases, but does not restore missing bundles for older releases.
The staging tests check byte preservation and missing-file failures; actual
signature verification requires the signed release bundle.

If the GitHub attestation API returns 404, retain the retrieval failure separately
from artifact-integrity checks. For containers, `--bundle-from-oci` provides an
independent retrieval path for the signed GitHub bundle. It is not the same as
merely inspecting unsigned BuildKit metadata. PyPI publishing attestations also
provide distinct evidence for Python artifacts; they do not establish that a
GitHub SLSA bundle is retrievable. Never change the expected signer just to make
verification pass. See [GitHub attestation verification](https://cli.github.com/manual/gh_attestation_verify).

All workflow actions are pinned to a full commit SHA with the release tag in a
comment, and the Dockerfile pins its base images by digest. Dependabot's
`github-actions` and `docker` ecosystems propose updates to both.

## Publication from the current repository

The `grc-lake` PyPI project exists, and 0.3.10 was published from the current
repository. Preserve and verify its
[ordinary trusted publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
configuration before the next release:

| Field             | Value            |
| ----------------- | ---------------- |
| PyPI project      | `grc-lake`       |
| GitHub owner      | `koda-ai-studio` |
| Repository        | `grc-lake`       |
| Workflow filename | `release.yml`    |
| Environment       | `release`        |

Verify the `release` GitHub environment and its intended reviewer/tag restrictions
as well. A successful dry run exercises builds, not PyPI authorization or registry
write permissions. Historical provenance proves the earlier upload's identity;
it does not show the project's current trusted-publisher settings.

The release workflow derives its image destination from `github.repository_owner`,
so the next release targets `ghcr.io/koda-ai-studio/grc-lake`. Before tagging:

1. Confirm this repository's Actions token can update the existing public package.
   The workflow already requests `packages: write`; package grants and organization
   creation policy are separate. Publishing another version of the existing package
   should not require broadening organization-wide public-package creation permissions.
2. Preserve `ghcr.io/msaad00/grc-lake` for historical releases. GHCR uses granular
   permissions: a [repository transfer does not transfer package ownership](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages#about-repository-transfers)
   and can remove repository linkage and Actions access.
3. The v0.3.10 release templates align Compose and the chart default to
   `ghcr.io/koda-ai-studio/grc-lake:0.3.10`; Terraform inherits the chart default
   when its image tag is empty. For later releases, update these references
   together and verify publication before recommending them.
4. After user-authorized publication, verify anonymous pulls (if public delivery
   is intended), both architecture digests, signed provenance, and runtime smoke
   checks against the newly published bytes. Registry visibility may need explicit
   configuration; a successful workflow alone is not anonymous-pull evidence.

Keep the old distribution and its releases intact. Do not delete or replace a
publisher until its replacement is confirmed and remaining workflows are accounted
for. Merge, tag, publication, and deployment remain separate operator decisions.

## Authenticated image qualification

Use an already-pulled image and an explicit platform. The probe starts the
Compose server profile with authentication required, creates two synthetic tenants
and expiring admin/reader API keys, and checks authorization, evidence isolation,
snapshot reads/exports, revocation, integrity, and persistence after container
recreation. It reuses the image's installed application and never mounts source
code into the server. It removes its containers, volume, and temporary signing key.
Choose a fresh output directory for each run:

```bash
IMAGE=ghcr.io/msaad00/grc-lake@sha256:d8cd294bbe5b761ab98f38931657711b1aa94edc08d7687b757d4973a89d7625
docker pull --platform linux/amd64 "$IMAGE"
python tools/authenticated_smoke.py --image "$IMAGE" --platform linux/amd64 \
  --output /tmp/grc-lake-auth-amd64
```

Repeat with `linux/arm64` and another output directory. Record native versus
emulated execution. These are bounded local API-key checks; they do not establish
OIDC/SAML, TLS, live-provider behavior, production deployment, or capacity.
Use `tools/compose_smoke.py` separately when qualifying the unauthenticated demo.

Scan each published architecture against a fresh vulnerability database. Retain
all severities in the report, then separately evaluate the release policy of no
HIGH/CRITICAL findings, including unfixed ones, and fixable MEDIUM findings.
A policy pass is not a vulnerability-free image.

## What the overview means

- **Assessment score** is the percentage of observed controls with fresh passing evidence; catalog coverage is reported separately.
- **Assessed coverage** is the share of catalogued requirements with an assessment
  result. It describes assessment scope, not the percentage passing. Requirements
  still needing evidence remain visible separately.
- **Open findings** and severity counts describe the current assessment. Other
  findings are those outside the critical and high groups.
- **Frameworks assessed** describes assessed coverage, not certification or a
  complete assessment of every requirement in a framework.
- **Evidence freshness** and **assessment export** are separate from the score.
  A connected update stream does not establish that evidence is current.

## Evidence boundaries

Synthetic fixture tests demonstrate reproducible application behavior, including
failure and authorization paths. They do not establish live collection accuracy,
precision, recall, customer capacity, vendor cost savings, or production readiness.

Local Polaris/Iceberg and independent-reader tests establish only the catalog,
snapshot, schema, and data-parity behaviors covered by those tests. They do not
establish interoperability with every hosted warehouse or object store.

A Docker build or Helm render is not an authenticated cloud deployment. Private
cloud-account experiments must be documented separately with sanitized results;
never commit credentials, account identifiers, raw customer evidence, or private
commercial information to this public repository.

## Deployment probes

`GET /api/healthz` reports process liveness. `GET /api/readyz` returns 200 only
when local mode has the tenant table and its lake root accepts a temporary write
and fsync. Distributed mode additionally checks access to its S3 bucket while
using PostgreSQL for the tenant-table check and private scratch for the write
probe; otherwise it returns a sanitized 503. Both
are unauthenticated. Readiness is excluded from request audit and rate limiting,
returns `Cache-Control: no-store`, and never enumerates tenants or hashes all
assessment artifacts. An empty, initialized deployment can be ready.

SQLite is checked with a fresh existing-file connection, so removal or corruption
is detected even if the application pool still holds an earlier connection.
Restoring the database makes the next probe succeed. Remote database connection
timeouts follow the configured SQLAlchemy driver. The Helm chart uses readiness
to route traffic and keeps liveness separate to avoid restarting on dependency
outages. These probes do not certify assessment freshness, per-tenant artifact
integrity, backup recovery, or remote provider health.

## Deployment acceptance

Before sharing a hosted pilot, validate the target environment directly:

1. HTTPS, external authentication, tenant isolation, and role-based access.
2. Required read-only connector grants and complete collection with failure
   reporting, freshness, and provenance.
3. Integrity verification, durable evidence and snapshots, backup and restore.
4. Scheduler behavior, resource limits, logs, monitoring, and incident ownership.
5. Scoped export/share creation, expiry, revocation, and audit records.
6. Workload-specific throughput, data volume, latency, and operating cost.

Certification decisions require the applicable independent assessment process.
Framework mappings and executable checks support evidence review; they do not
replace that process.
