# Security policy

## Report a vulnerability

Please report security vulnerabilities privately through GitHub:
**[Report a vulnerability](https://github.com/koda-ai-studio/grc-lake/security/advisories/new)**
(the repository's **Security** tab, then **Report a vulnerability**).

Do not open a public issue, pull request, or discussion for a vulnerability.

Include what you can of:

- the affected version (`pip show grc-lake`, or the image tag);
- the component: API, console, CLI, MCP server, a connector, the Helm chart,
  the container image, or the posture-gate action;
- steps to reproduce, and the impact you expect;
- whether the issue needs authentication, and which role.

Do not include real credentials or customer evidence. We will acknowledge the
report, work on a fix in the private advisory, and credit you when the advisory
is published unless you ask us not to.

## Public repository data

Keep personal credentials, account and subscription identifiers, tenant URLs,
private infrastructure details, and raw provider receipts out of source, docs,
tests, screenshots, issues, and pull requests. Use clearly synthetic fixtures
and placeholders; supply live values through private runtime configuration.
Do not include real identifiers even in assertions that check they are absent.

Secret scanning runs in pre-commit and across Git history in CI. It does not
identify every personal account detail, so review examples and evidence before
publishing them. If a real credential is exposed, revoke or rotate it; deleting
it from the latest revision does not remove it from Git history.

## Supported versions

Security fixes go into the latest release of the current minor line and ship
as a new patch release. Upgrade to the newest patch to receive them.

| Version                      | Supported |
| ---------------------------- | --------- |
| Latest `0.3.x` patch release | Yes       |
| Earlier releases             | No        |

## Published assessment-integrity advisory

[GHSA-76q3-wh53-hvv2](https://github.com/koda-ai-studio/grc-lake/security/advisories/GHSA-76q3-wh53-hvv2)
is fixed in **0.3.22 and later**. Version 0.3.21 is confirmed affected; earlier
versions have not been qualified. The advisory remains published as a record of
the issue and its fix.

Upgrade to the latest patch, then reevaluate existing lakes. An explicit
safeguard binding alone cannot establish applicability: the evaluator requires
a declared evidence-type contract and matching evidence. Unrelated evidence
must produce neither a passing nor a failing safeguard verdict. Missing
applicable evidence remains `not_evaluated`.

Historical generations and snapshots retain their original results. Use the
corrected generation after reevaluation; do not treat an old snapshot as a
corrected assessment. The fix does not supply missing safeguard contracts or
approve framework mappings; those need requirement-specific human review.

The [published-advisory regression](tests/test_ccf_published_advisory.py) uses
the shipped catalog with synthetic MFA evidence bound to `SG-PHYSICAL-001` and
`NIST-CSF-PR.AA-06`. It checks the materialized assessment, API, OSCAL export,
incremental replay and snapshot preservation. It makes no live-provider claim.

## Scope

In scope:

- the `grc-lake` Python package and its CLI, API, console,
  and MCP server;
- the `ghcr.io/koda-ai-studio/grc-lake` container image and the Helm chart in
  [`deploy/helm/grc-lake`](deploy/helm/grc-lake/);
- the posture-gate GitHub Action in [`.github/actions/posture-gate`](.github/actions/posture-gate/);
- deployment templates in [`deploy/`](deploy/) and [`compose.yaml`](compose.yaml).

Examples of issues we want to hear about: authentication or tenant-isolation
bypass, privilege escalation between roles, credential or secret disclosure,
server-side request forgery through connectors, injection, and tampering with
evidence or review logs that goes undetected.

Out of scope:

- running with authentication disabled (`--allow-insecure-no-auth`, or the
  default `grc-lake` service in `compose.yaml`). That mode is unauthenticated
  by design, for local demos only;
- vulnerabilities in third-party dependencies with no GRC Lake-specific impact;
  report those upstream. Dependabot opens weekly version-update PRs;
- findings in the bundled sample data under `mockup_companies/`;
- results that need an already compromised host, or physical access.

For how authentication, tenancy, and credentials are designed, see
[server auth](docs/SERVER_AUTH.md) and [architecture](docs/ARCHITECTURE.md).

The current dependency audit scope and the build-tool advisory mitigations are documented in
[dependency security](docs/DEPENDENCY_SECURITY.md).
