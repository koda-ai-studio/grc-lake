# GCP effective org-policy receipt: 2026-10-26

<a id="gcp-posture"></a>

A bounded, read-only live run against one maintainer-owned GCP project, with the
user's application-default credentials, before and after reading inherited
organization policies from the effective policy. It is not qualification of
other projects, folders, organizations or production scale.

## Before (v0.3.14, `8b2500cf`)

Probe and two syncs each returned 185 records with no coverage gaps and no
duplicates on recollection (167 asset observations, 16 IAM bindings, 2 org
policies). Neither expected constraint is set on the project itself, so both
org-policy rows were `not_evaluated` (`set_on_project: false`) and no framework
result moved: 2,196 requirements `not_evaluated`, 86 `unmapped`.

## After (this change)

| Constraint                             | Effective policy (checked with `gcloud org-policies describe --effective`) | Row    |
| -------------------------------------- | -------------------------------------------------------------------------- | ------ |
| `iam.disableServiceAccountKeyCreation` | inherited, `enforce: true`                                                 | `pass` |
| `compute.requireOsLogin`               | inherited, `enforce: false`                                                | `open` |

The same 185 records were collected with no coverage gaps. `SG-IDENTITY-001`
failed on the unenforced OS Login constraint, and 104 framework requirements
moved to `fail` through that safeguard's crosswalk; 2,092 stayed
`not_evaluated` and 86 `unmapped`. Both effective reads succeeded with the
operator's existing read access; a denied `orgpolicy.policy.get` was not
exercised live.

## Limits

One project at one point in time. The 104 failing requirements include
provider-specific benchmark items from other clouds, because the safeguard's
crosswalk is cross-framework; scoping provider benchmarks to their own provider's
evidence is a separate follow-up. Project, organization and principal
identifiers and raw evidence are excluded from this receipt.
