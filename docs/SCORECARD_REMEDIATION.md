# Scorecard evidence and remediation

A successful Scorecard workflow uploads observations; it does not mean every
check passes. Keep the SARIF finding open until its underlying evidence changes.
See the [Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md).

| Check              | Required evidence                                                                   | Closure boundary                                                                                                      |
| ------------------ | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Code-Review        | Independent human approval of changes, plus required pull-request review policy     | Bot reviews and a policy change do not retroactively approve past changes. Scorecard inspects recent merged changes.  |
| Fuzzing            | A recognized fuzz integration that builds real targets and runs against the project | A workflow file alone is not proof of a successful fuzz run. Confirm build, execution, and the next main-branch scan. |
| CII-Best-Practices | A project entry in the OpenSSF Best Practices program with supported responses      | Repository documents alone do not register or earn a badge. Do not claim a badge until its public record exists.      |

## Review coverage

The Code-Review check evaluates recent merged changes, so enabling required
reviews does not immediately repair the historical score. Follow the
[human review requirements](../CONTRIBUTING.md#human-review-before-merge) for
each new change. Do not add empty commits or post-merge approvals merely to
alter the score. Keep the alert open until a fresh scan recognizes sufficient
reviewed changes.

## Best Practices assessment

The existing [project entry](https://www.bestpractices.dev/en/projects/15368)
tracks the canonical `https://github.com/koda-ai-studio/grc-lake` repository.
Use that entry rather than registering a duplicate. Its live status is the
authority for whether a badge has been earned.

A maintainer can use the following repository sources while completing the
[passing-badge criteria](https://www.bestpractices.dev/en/criteria/0):

- Project purpose and installation: `README.md` and `docs/`.
- License: `LICENSE`; contribution and test policy: `CONTRIBUTING.md`.
- Change history: Git history, `CHANGELOG.md`, and published release tags.
- Reporting: GitHub issues and `SECURITY.md` for vulnerability reporting.
- Build and validation: `Makefile`, `.github/workflows/ci.yml`, and `tests/`.
- Static analysis: `.github/workflows/codeql.yml` and security checks in CI.

These are evidence pointers, not completed questionnaire answers. Maintainers
must separately verify response-time history, security expertise, cryptographic
practices, and unresolved vulnerability age. Register the current repository URL
and verify the resulting badge through the program's public project record.

### Cryptographic evidence and deployment boundaries

- API keys use 192 random bits and browser session tokens use 256 random bits
  from Python's `secrets` module. Token lookup uses SHA-256; legacy token rows
  retain a PBKDF2-HMAC-SHA256 verification path. See
  [`auth/tokens.py`](../src/security_lakehouse/auth/tokens.py) and
  [`auth/sessions.py`](../src/security_lakehouse/auth/sessions.py).
- Browser cookie and OIDC state signing use SHA-256 and reject configured
  secrets shorter than 32 bytes. Operators must generate random secrets;
  length validation alone cannot prove entropy. See
  [`auth/signing.py`](../src/security_lakehouse/auth/signing.py) and
  [`auth/session_middleware.py`](../src/security_lakehouse/auth/session_middleware.py).
- SAML requires signed assertions and rejects the toolkit's deprecated
  signature/digest algorithms. The configured IdP certificate, key strength,
  and optional integrations still need review. See
  [`auth/saml.py`](../src/security_lakehouse/auth/saml.py) and
  [server authentication](SERVER_AUTH.md).
- Guarded HTTPS requests use Python's default verifying SSL context. Incoming
  TLS terminates at the operator's proxy or ingress. Forward secrecy and the
  enabled TLS algorithms require evidence from that deployment; a local HTTP
  smoke test or application-level signing test cannot establish them.

These implementation facts support assessment review; they do not establish
all cryptographic criteria for every supported integration and deployment.

### Vulnerability and release evidence

CI retains `image-vulnerabilities/trivy-ci-amd64.json`. Release qualification
retains `release-image-vulnerabilities/trivy-release-amd64.json` and
`trivy-release-arm64.json`. These reports include every severity and findings
without a vendor fix, and remain available for 14 days even if the image policy
gate fails. A failed earlier build can leave no report; a failed AMD64 gate can
leave ARM64 unqualified. Missing reports are missing evidence, not clean scans.

Review each report's image identity, advisory publication dates, installed and
fixed versions, and component applicability. The candidate image policy blocks all HIGH/CRITICAL findings and fixable
MEDIUM findings. It does not prove the
Best Practices requirement concerning medium-or-higher vulnerabilities older
than 60 days. Retain unresolved distribution findings until a patched artifact
or a reviewed applicability decision supplies evidence. See
[dependency security](DEPENDENCY_SECURITY.md) and
[published-image qualification](RELEASE_READINESS.md#authenticated-image-qualification).

For the release-notes criterion, reconcile published project advisories and
release notes, including assigned CVE/GHSA identifiers for runtime fixes.
Dependency advisories have a different scope under that criterion. Assess
critical-vulnerability response using dated reports and fixes; an empty scan
alone does not demonstrate response history.

## Refresh after remediation

Once changes are on `main`, or the external badge record changes, run:

```bash
gh workflow run scorecard.yml --repo koda-ai-studio/grc-lake --ref main
```

The pinned Scorecard action labels manual dispatch experimental. If that event
is rejected, rerun the latest main push run from GitHub Actions; do not add an
empty commit just to trigger a scan.

Confirm the run succeeded, inspect the uploaded SARIF and current alert
instances, and match their commit SHA to the intended main revision. Workflow
success means the scan completed; only the resulting evidence can establish
alert closure. A draft questionnaire or an unmerged fix cannot do that.
