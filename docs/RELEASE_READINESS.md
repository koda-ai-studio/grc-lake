# Release readiness

GRC Lake **0.3.13 is published** on
[PyPI](https://pypi.org/project/grc-lake/0.3.13/),
[GitHub](https://github.com/koda-ai-studio/grc-lake/releases/tag/v0.3.13), and as
`ghcr.io/koda-ai-studio/grc-lake:0.3.13`.
Use the [v0.3.13 release templates](https://github.com/koda-ai-studio/grc-lake/tree/v0.3.13)
for a published deployment. The package, provenance and container verification
below are scoped to that release; later commits on `main` may contain unreleased fixes.

0.3.13 aligns graph CCF results, scopes OCSF identities to source accounts, exposes
incomplete mappings and repairs Databricks audit bootstrap handling. Existing OCSF
evidence retains its original identities: preserve it and re-ingest source history
into a fresh lake to adopt the new preset IDs. See the qualification boundaries below.

There are no new database migrations between v0.3.10 and v0.3.13. 0.3.11 restores
the bare installation (fixture loading, pipeline replay, snapshots and local-mode
serving without SQLAlchemy) and adds `grc-lake demo`. The 0.3.11 OCSF rule presets
introduced pass, open and pending results; add `"rules": []` to a preset reference to
keep presence-only mapping (see the [changelog](../CHANGELOG.md)). Upgrading from
0.3.9 or earlier: the KnowBe4 preview connector is retired (remove external sync
jobs and revoke unused credentials separately), and AWS role-policy collection is
off by default and requires six additional read-only IAM grants when enabled.

The shell-free runtime uses pinned Wolfi Python and matching system libraries.
Release qualification covers both architectures and reports zero vulnerabilities.
CI and release gates block all HIGH/CRITICAL and fixable MEDIUM findings.
See [runtime construction and scan scope](DEPENDENCY_SECURITY.md#0313-release-qualification-scans).
Earlier published images and their historical scan results remain unchanged.

Use the generated [coverage matrix](FRAMEWORK_COVERAGE.md) for current mapped and
reviewed counts, and the [SOC 2 and ISO review queue](reviews/SOC2_ISO_REVIEW.md)
for pending mapping decisions. Proposed mappings do not grant review credit;
reviewed mappings do not establish operating effectiveness or certification.
The [graph cache and navigation measurements](benchmarks/INVESTIGATION_CACHE.md)
retain their exact source revisions and synthetic workload limits. They do not
establish production capacity or qualify a deployment memory budget; 100k records
remain outside the proposed interactive workload.

## 0.3.13 qualification

Framework and repository maps now carry the same CCF result and reviewed/proposed
mapping counts as Controls and Investigation. A missing framework result is not
shown as a passing control. Regression coverage includes `SOC2-CC6.8`, whose
control test passes while its proposed-only framework mapping is not evaluated.

The [October 25 capacity measurements](benchmarks/INVESTIGATION_CACHE.md#october-25-2026-sustained-traffic-expiry-and-process-memory)
add sustained hot/cold tenant traffic, idle expiry, forced eviction, 100k cache
comparison and simultaneous worker RSS. The 100k models were not retained by the
128 MiB cache. Reviewer-approved capacity budgets remain outstanding.

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
