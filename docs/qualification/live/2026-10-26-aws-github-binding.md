# AWS and GitHub framework-binding receipt: 2026-10-26

<a id="aws-posture"></a>
<a id="github-security"></a>

A bounded, read-only pilot against one maintainer-owned AWS test account and the
public GitHub repository of this project, run before and after safeguard binding
for flagship connectors (#1064). It records whether real connector evidence moves
framework (CCF) results. It is not qualification of other accounts, private
repositories, GitHub App installations, production scale or operating
effectiveness.

## Setup

- AWS: assume-role into a reader role with the AWS-managed SecurityAudit policy
  and an External ID; IAM posture collection only.
- GitHub: a user OAuth token supplied through `credential_ref`; probe, configure
  and sync for one repository. The token value never appeared in lake files or
  command output.
- Each run used a separate, empty lake and the shipped catalog.

## Before binding (source `3235c9ad`, 2026-10-25)

| Source   | Records | Collected outcomes                                                         | Framework (CCF) result                                      |
| -------- | ------- | -------------------------------------------------------------------------- | ----------------------------------------------------------- |
| GitHub   | 6       | 6 `observed` governance signals                                            | none                                                        |
| AWS IAM  | 12      | 3 open access-key findings, 1 open password-policy finding, 8 observations | none                                                        |
| Combined | 18      | 5 failing control tests                                                    | 2,196 `not_evaluated`, 86 `unmapped`; 0 safeguards assessed |

Independent checks against the providers: the default branch requires one
approving review, includes administrators and has five required status checks
(GitHub API); the account has no password policy and three active access keys
older than 90 days (IAM credential report). The four users without MFA have no
console password, so their MFA records correctly stay observations.

## After binding (source `0dbe7c73`, 2026-10-26)

| Source  | Records                                          | Bound to a safeguard                    | Safeguard result                                                                                     |
| ------- | ------------------------------------------------ | --------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| GitHub  | 7 (adds `repository.governance.change_approval`) | 1                                       | `SG-CHANGEAPPROVAL-001` pass: reviews required, admins included, force pushes and deletions disabled |
| AWS IAM | 12                                               | 4 (access-key hygiene, password policy) | `SG-IDENTITY-001` fail                                                                               |

Framework results: 103 requirements `fail`, 1 `pass` (NIST-CSF-ID.RA-07, through
an already reviewed change-approval mapping), 2,092 `not_evaluated`, 86
`unmapped`. Failing requirements include SOC2-CC6.1 and ISO27001-A.5.15 through
their reviewed identity mappings. SOC2-CC8.1 and ISO27001-A.8.32 stay
`not_evaluated`: their change-approval mappings are still proposed, so a passing
branch-protection verdict does not attest them.

## Limits

One account, one public repository, one region and one point in time. Private
repositories, GitHub App installation tokens, organization rulesets, other AWS
services, throttling and credential expiry were not exercised. Account,
principal and user identifiers and raw evidence are excluded from this receipt.
