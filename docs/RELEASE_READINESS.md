# Release readiness

Source version **0.3.10** is prepared for qualification and is not yet published.
The versioned Compose, Helm and CI examples on this branch target that candidate;
use the verified v0.3.9 templates below until publication completes. The candidate
requires independent review, green CI on its merged main commit, and fresh
AMD64/ARM64 vulnerability and authenticated runtime checks before tagging.

There are no new database migrations between v0.3.9 and this candidate. The
experimental canonical-entity ledger is additive and does not migrate existing
findings or assessments. The KnowBe4 preview connector is retired: remove external
sync jobs and revoke unused credentials separately. AWS role-policy collection
is off by default and requires six additional read-only IAM grants when enabled.
Published-artifact hashes, signatures and installation checks must be recorded
after publication; historical v0.3.9 receipts do not qualify 0.3.10.

GRC Lake **0.3.9 is published and verified** on
[PyPI](https://pypi.org/project/grc-lake/0.3.9/),
[GitHub](https://github.com/koda-ai-studio/grc-lake/releases/tag/v0.3.9), and as
`ghcr.io/koda-ai-studio/grc-lake:0.3.9`.
Use the [v0.3.9 release templates](https://github.com/koda-ai-studio/grc-lake/tree/v0.3.9)
for a published deployment. Later commits on `main` may contain unreleased changes.

The shell-free runtime uses pinned Wolfi Python and matching system libraries.
Both published architectures match images qualified with zero reported vulnerabilities.
CI and release gates continue to block all HIGH/CRITICAL and fixable MEDIUM findings.
See [runtime construction and scan scope](DEPENDENCY_SECURITY.md#039-release-qualification-scans).
Earlier published images and their historical scan results remain unchanged.

The release includes repaired SOC 2 governance contracts, 35 receipt-bound
mapping approvals, explicit legacy-review provenance, safeguard fan-out limits,
the MCP SDK security floor, and refreshed [graph](benchmarks/INVESTIGATION.md) and
[CCF/distributed](benchmarks/CCF_PIPELINE.md) measurements. Local measurements do
not establish production capacity. At 10k records, the proposed 1 GiB graph
memory budget is not qualified; 100k remains outside the interactive target.

Mapped coverage is 1,803 of 2,252 requirements (80.1%). Reviewed coverage is
1,163 (51.6%): 381 source-native self-maps and 782 crosswalk-reviewed requirements.
Separately, 824 reviewed requirements have a decision receipt and 339 rely only
on legacy reviews with no recorded reviewer. These dimensions do not establish
operating effectiveness, certification, or uniform review depth across frameworks.
The [coverage matrix](FRAMEWORK_COVERAGE.md) reports each framework's counts.
The [SOC 2 and ISO review queue](reviews/SOC2_ISO_REVIEW.md) retains 115 requirements
in 13 batches. See the [review-method record](MAPPING_REVIEW.md#pending-soc-2-and-iso-review)
for scope, source limitations, and recorded human decisions.

Existing `trustops-security-data-lake` releases remain available under their
original PyPI name. Use a fresh Python environment when moving between distributions
because they own overlapping module files. Legacy CLI aliases and Python imports
remain supported. Local deployment remains supported; distributed mode remains
opt-in and requires the [migration and recovery procedures](DISTRIBUTED.md).
Upgrading from 0.3.2 requires signing secrets of at least 32 bytes and, for SAML
deployments, non-deprecated IdP signature and digest algorithms. Existing browser
sessions must sign in again. See [deployment](DEPLOYMENT.md) and
[server authentication](SERVER_AUTH.md).

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
| Changelog             | A `## <version> - <date>` section in `CHANGELOG.md`                                                     | The section exists and becomes the GitHub release notes                                                                     |
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

The `grc-lake` PyPI project exists, and 0.3.9 was published from the current
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
3. The v0.3.9 release templates align Compose and the chart default to
   `ghcr.io/koda-ai-studio/grc-lake:0.3.9`; Terraform inherits the chart default
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
