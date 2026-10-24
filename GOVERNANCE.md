# Governance

GRC Lake is an open-source project under the [Apache 2.0 license](LICENSE).
This document describes who decides what, and how contributors become
maintainers. It is intentionally small and will grow with the project.

## Roles

- **Contributors** open issues, discussions, and pull requests. Anyone who
  follows the [Code of Conduct](CODE_OF_CONDUCT.md) can contribute.
- **Reviewers** are contributors with a record of accurate reviews in one area,
  such as a connector family, framework packs, or the console. Maintainers can
  request their review; their approval counts toward the human review rule in
  [CONTRIBUTING.md](CONTRIBUTING.md#human-review-before-merge).
- **Maintainers** are listed in [MAINTAINERS.md](MAINTAINERS.md). They merge
  pull requests, triage issues, cut releases, and own security response.

## Decisions

- Day-to-day changes are decided in pull requests. Every pull request needs
  approval from a human other than its author, and required checks must pass.
- Changes to evaluation semantics, mapping review state, the data model, public
  APIs, or security boundaries need an issue or design note first, and approval
  from a maintainer.
- A mapping becomes `reviewed` only when a person has checked the requirement
  text, as described in [mapping review](docs/MAPPING_REVIEW.md). Automated
  tools and agents can propose mappings; they cannot review them.
- When maintainers disagree, they seek consensus in the issue or pull request.
  If consensus is not reached, the lead maintainer decides and records the
  reasoning publicly.

## Becoming a reviewer or maintainer

- **Reviewer:** several merged contributions or substantive reviews in one area.
  A maintainer proposes the role in a public issue.
- **Maintainer:** sustained contributions and reviews across releases, sound
  judgment about evidence accuracy and security, and willingness to share
  triage and release work. An existing maintainer nominates the candidate in a
  public issue; it is accepted when no maintainer objects within seven days.
- Inactive maintainers (no activity for six months) move to emeritus status and
  can return by asking.

## Releases and security

Releases follow [release readiness](docs/RELEASE_READINESS.md): version gates,
provenance, SBOM, and post-publication verification. Report vulnerabilities
privately as described in [SECURITY.md](SECURITY.md); maintainers coordinate the
fix and disclosure.

## Changes to this document

Changes to governance follow the same pull request process and need approval
from a maintainer.
