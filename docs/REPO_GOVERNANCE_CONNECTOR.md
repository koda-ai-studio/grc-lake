# Repository Governance Connector

GRC Lake can sync authenticated **GitHub** and **GitLab** repository governance
evidence for private repos and organization-only controls that public audit
cannot observe. The connector emits raw JSONL evidence that can be validated and
routed into the security data lake.

```bash
GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN=... grc-lake repo governance-sync OWNER/REPO --out build/repo-governance.jsonl
GRC_LAKE_GITLAB_ACCESS_TOKEN=... grc-lake repo governance-sync NAMESPACE/PROJECT --provider gitlab --out build/gitlab-governance.jsonl
grc-lake validate --raw build/repo-governance.jsonl
```

Offline fixture mode is available for tests, demos, and CI without credentials:

```bash
grc-lake repo governance-sync OWNER/REPO \
  --fixture-dir tests/fixtures/github-governance \
  --out build/repo-governance.jsonl

grc-lake repo governance-sync acme/private-agent-api \
  --provider gitlab \
  --fixture-dir tests/fixtures/gitlab-governance \
  --out build/gitlab-governance.jsonl
```

## Access Boundary

### GitHub

Use a GitHub App installation token with read-only repository permissions. The
connector does not need write, delete, admin, secret value, or package publish
permissions.

| Scope or permission    | Unlocks                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `metadata:read`        | repository identity, default branch, visibility, source health     |
| `contents:read`        | repo-level metadata needed to link evidence to the repo asset      |
| `administration:read`  | branch protection, collaborators, teams, workflow permissions      |
| `security_events:read` | security setting and alert availability summaries where allowed    |
| fixture bundle         | deterministic local evidence with `credential_fingerprint=fixture` |

### GitLab

Use a project or group access token with read-only API access (`read_api`,
`read_repository`). Optional `GRC_LAKE_GITLAB_API_URL` overrides the default
`https://gitlab.com/api/v4` base for self-managed instances.

| Scope or permission | Unlocks                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `read_api`          | project metadata, protected branches, members, shared groups       |
| `read_repository`   | repository identity and default branch                             |
| `read_user`         | member username resolution                                         |
| fixture bundle      | deterministic local evidence with `credential_fingerprint=fixture` |

Installation token values are never emitted. GRC Lake stores only a short
SHA-256 credential fingerprint so operators can tell which credential boundary
produced evidence without exposing the credential itself.

## Evidence Signals

| Event type                                   | Why it matters                                     |
| -------------------------------------------- | -------------------------------------------------- |
| `repository.governance.branch_protection`    | required reviews, status checks, admin enforcement |
| `repository.governance.collaborators`        | direct user access and role inventory              |
| `repository.governance.teams`                | team-based maintainers and approver boundaries     |
| `repository.governance.workflow_permissions` | GitHub Actions default token behavior              |
| `repository.governance.security_settings`    | security alert availability where the API permits  |

Each emitted record includes:

- `event_id`
- `tenant_id`
- `workspace_id`
- `event_time`
- `source=github-repo-governance` or `source=gitlab-repo-governance`
- `event_type`
- `entity.asset_id`
- `entity.asset_type=repository` (`repo` for the change-approval verdict below)
- `entity.repo`
- `controls`
- `evidence.evidence_id`
- `evidence.evidence_ref`
- `evidence.evidence_collected_at`
- `evidence.raw_sha256`
- `attributes.source_health`

The signals above are observations (`status=observed`), except that
`repository.governance.security_findings` is `open` while open alerts exist. None
of them is bound to a safeguard.

For GitHub, the connector also emits one evaluated
`repository.governance.change_approval` record for the default branch, bound to
the `SG-CHANGEAPPROVAL-001` safeguard (asset `github:repo:OWNER/REPO#default-branch`,
`entity.asset_type=repo`, controls `SOC2-CC8.1` and `ISO27001-A.8.32`). Its
status comes from the branch-protection record:

| Status          | When                                                                                                                                                                       |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pass`          | protection is readable, `required_approving_review_count >= 1`, `enforce_admins.enabled` is true, and `allow_force_pushes.enabled` and `allow_deletions.enabled` are false |
| `open`          | protection is readable and any of those is not met; `attributes.unmet_requirements` lists which (no pull request review requirement counts as zero approvals)              |
| `not_evaluated` | protection is unreadable (HTTP 401, 403 or 404; a 404 is not read as "unprotected") or a required setting is missing or malformed (`attributes.unknown_requirements`)      |

Re-syncs replace the record (its `event_id` is stable per repository).
Framework requirements still need a reviewed mapping before this safeguard
result can be attested. Compliance posture is evaluated by the assessment
engine from normalized facts, mappings, freshness, and control rules.

## Relationship To Public Audit

Use `grc-lake repo audit` first for fast public inventory and code
graph evidence. Use `grc-lake repo governance-sync` when a control
depends on private or organization-scoped GitHub settings.

```bash
grc-lake repo audit https://github.com/OWNER/REPO --out build/repo-audit.jsonl
grc-lake validate --raw build/repo-audit.jsonl
```

Public audit needs no token and collects only what GitHub exposes without
credentials: repository metadata, `CODEOWNERS` and `SECURITY.md` locations, CI
workflow files, dependency manifests and lockfiles, container and IaC
indicators, AI artifacts (model cards, eval and prompt files), and a
repository code graph. Each record carries a stable `event_id`, `evidence_id`,
`evidence_ref`, `evidence_collected_at`, and SHA-256 hash. Source text is read
only to hash samples and is never retained (`sample_excerpt` is always null).
The tree response must report `truncated: false`; a truncated or malformed
tree fails before the output is replaced, so very large repositories need a
scoped collector.

Public audit emits `repository.authenticated_signal_gap` with
`status=requires_authenticated_connector` when it reaches a signal that needs
authenticated access, such as branch protection, rulesets, secret scanning,
Dependabot, or code scanning alerts. Governance sync closes that gap with
provable evidence instead of guessing.
