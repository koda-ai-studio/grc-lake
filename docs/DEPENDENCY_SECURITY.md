# Dependency security scope

Lockfile review: 2026-10-12. Release image scan: 2026-10-15. Dependency advisories
change; rerun both production and full build-tool audits when reviewing or
upgrading the lockfiles.

## Container runtime findings

The published Python SBOM covers the locked application dependencies. It
does not include all packages inherited from the container base. A full image
scan of 0.3.2 on 2026-10-10 found vulnerable copies of pip 25.0.1 in the base interpreter
and application virtual environment, and a fixable liblzma advisory on both
AMD64 and ARM64.

The 0.3.3 image creates the virtual environment without pip, removes the
base interpreter's pip and ensurepip, and refreshes liblzma from Debian security
for [DSA-6549-1](https://security-tracker.debian.org/tracker/DSA-6549-1).
`tools/check_image_dependencies.sh` checks both installed interpreters, the
minimum patched liblzma version, compression and SQLite operations, and TLS
context creation.
The image also removes setuid/setgid permission bits from system utilities and
checks that they remain absent. This reduces privilege-elevation paths; it does
not patch or suppress unresolved util-linux, ACL or other distribution findings.
The unused `infocmp` executable is removed for CVE-2025-69720; the image check
verifies its absence while keeping the ncurses libraries available for Python.
Install optional application dependencies in a derived image's build stage;
the runtime image intentionally has no Python package installer.

CI and release scans reject fixable MEDIUM, HIGH and CRITICAL findings. Run a
second scan without severity or fix-availability filters to retain unresolved
distribution findings. No available vendor fix does not mean not affected, and
passing this gate does not satisfy the Best Practices 60-day criterion. The
published 0.3.2 digests remain unchanged; these remediations are in 0.3.3.

CI and release qualification also retain full, unfiltered JSON vulnerability
reports for 14 days, including when the fixable-only scan blocks the job. See
[Scorecard evidence](SCORECARD_REMEDIATION.md#vulnerability-and-release-evidence)
for artifact names and the separate Best Practices review requirements.

### 0.3.5 release qualification scans

The [release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/38686161848)
on source `a81782af` completed on 2026-10-15 UTC. Both AMD64 and emulated ARM64
passed installed-dependency checks, the fixable-vulnerability gate and authenticated
runtime probes. Each unfiltered image report contains 164 Debian package/advisory
findings: 44 HIGH, 58 MEDIUM, 61 LOW and one UNKNOWN, with no listed fixed versions.
The gate therefore passed with zero fixable MEDIUM/HIGH/CRITICAL findings; this
is not a vulnerability-free result or closure of the Best Practices age criterion.

Published AMD64 and ARM64 filesystem layers and runtime configuration match the
scanned images. The workflow retains full scan reports and architecture receipts;
[release verification](RELEASE_READINESS.md#verified-035-publication) records the
published digests, package hashes and provenance checks. The eight distinct HIGH
CVEs remain open; the release does not establish non-exploitability.

### 0.3.3 release qualification scans

The AMD64 and ARM64 reports from the [0.3.3 release workflow](https://github.com/koda-ai-studio/grc-lake/actions/runs/38211832124)
on source `fee5a7b8` each contain 102 medium-or-higher package findings (44 HIGH,
58 MEDIUM; 37 distinct advisories), with no listed fixed versions. On 2026-10-12, 41 occurrences across
21 advisory IDs were more than 60 days old. Those counts describe scanner
matches, not individually confirmed exploitability. They describe the images
scanned during release qualification, not a later deployment. The unresolved age review
still prevents claiming the Best Practices passing criteria are satisfied.

### Unfixed HIGH findings: applicability review

The full 0.3.2 scans reported 44 HIGH package/advisory pairs representing eight
distinct CVEs per architecture. The table records a review of the published
AMD64 digest `455b944fab439f25dd8d7ae63346628d59eb6e5581d115edfa8f1185f317bb7b`
and ARM64 digest `c3b3c13676681e20366a8669c28e9997375dc90d0fba5a65e6b5fa90a3b10a2c`.
These observations do not carry over automatically to another image or deployment.

| Component  | Evidence and disposition                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| util-linux | [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), and [78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) concern privileged mount or namespace operations. Debian trixie has no listed fixed package. Keep open; removing setuid/setgid bits is mitigation, not a vendor patch or proof for privileged deployments. |
| libacl     | [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) affects pathname-based ACL operations. The library remains installed. Keep open; non-root execution does not prove every caller is unreachable.                                                                                                                                                                                                                                                                               |
| ncurses    | [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) concerns `infocmp`, which is present in both published images. The 0.3.3 build removes that executable and tests its absence. Keep the published-image finding open; review applicability again against the replacement digest.                                                                                                                                                                                               |
| systemd    | [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) concerns `systemd-homed`. Probes found neither `/usr/lib/systemd/systemd-homed` nor `/usr/libexec/systemd/systemd-homed` in either image. This supports component-absence triage of the libsystemd/libudev matches, subject to review before any VEX or suppression.                                                                                                                                                          |
| Perl       | [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) concerns `Archive::Tar`. `perl -MArchive::Tar` fails with the module missing in both images. This supports component-absence triage of the perl-base match, subject to review before any VEX or suppression.                                                                                                                                                                                                                    |

Retain the raw scan alongside any applicability decision. Accepted risk is a
separate, time-limited human decision; it does not patch the image, change a
control result to pass, or supply the missing Best Practices evidence.

```bash
uv export --frozen --all-extras --no-emit-project --format requirements-txt --no-hashes > /tmp/grc-lake-requirements.txt
uv run pip-audit --strict -r /tmp/grc-lake-requirements.txt
cd app/web
npm audit --omit=dev --audit-level=high
npm audit
```

## Patched template lookup

The Python lockfile uses Mako 1.4.3, above the 1.4.2 fix for Windows drive-letter
path traversal in `TemplateLookup`. Mako is used by Alembic migration tooling.
The server and development extras require Mako 1.4.3 or newer so package
upgrades also replace vulnerable versions in existing environments.

## Patched selector parser

[GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf)
(CVE-2026-104844) affects `postcss-selector-parser <7.1.6`: flat selector input can
cause quadratic CPU usage. Scoped npm overrides pin the copies used by Tailwind 3
and `postcss-nested` to patched version `7.1.6`. This removes the two affected
moderate dependency nodes without changing the Tailwind major version.

The console's static build produces byte-for-byte identical CSS before and after
the override. Keep lint, typechecking, static builds, and browser regressions in
the validation path. Remove the overrides once both upstream dependency ranges
resolve to a patched parser without them, and regenerate the lockfile.

## Bounded braces replacement

[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
(CVE-2026-93687) affects `braces <=3.0.3`: deeply nested brace patterns can exhaust
the stack. There is still no official patched upstream release. The console
uses an exact npm override to
[`@dieub/braces-depth-guard@3.0.3-pn.3`](https://www.npmjs.com/package/@dieub/braces-depth-guard/v/3.0.3-pn.3),
a separately maintained MIT-licensed derivative of braces 3.0.3.

The reviewed package caps brace/parenthesis nesting and recursive AST traversal
at 100 levels. Excessive string nesting raises a controlled `SyntaxError`;
excessive direct AST depth raises a controlled `RangeError`. It retains ordinary
alternatives, ranges, escapes, and stringify behavior. This intentionally rejects
patterns deeper than 100 rather than allowing JavaScript stack exhaustion. It
does not establish general bounds on expansion cardinality, AST width, arbitrary
malformed objects, or regular-expression complexity.

The initial adoption review compared the published runtime files with both
upstream 3.0.3 and derivative source commit
[`305a2e4bfe324bb53c336c1b03387ee1251c926f`](https://github.com/dieub/braces-depth-guard/tree/305a2e4bfe324bb53c336c1b03387ee1251c926f).
The tarball matches that tagged source; registry signatures and publishing
provenance verify with `npm audit signatures`. The lockfile records the tarball
SHA-512 integrity. There are no install lifecycle scripts in the replacement.
Do not replace this exact pin with a floating range without reviewing the new
artifact and provenance.

`npm run test:dependencies` exercises the copies resolved by micromatch and
chokidar: 100/101 boundaries, 4,000-level inputs in a small-stack child process,
direct ASTs, stricter limits, and ordinary syntax. A clean npm audit alone does
not establish that a renamed dependency fixes the issue. Keep these behavioral
regressions, lint, typechecking, static builds, and browser checks in the gate.
Remove the override only when an official patched upstream dependency chain
passes those checks.

The runtime image contains Python and static browser assets, not the Node build
environment. CI blocks known Python vulnerabilities and high-or-critical npm
vulnerabilities across both production and development dependencies, and retains
the complete npm audit report. Builds still process untrusted repository content
and must remain isolated from deployment credentials.
