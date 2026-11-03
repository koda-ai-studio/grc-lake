# GitHub repeat-collection receipt: November 2, 2026

<a id="github-security"></a>

- Adapter: `github-security`; existing Implemented stage retained.
- Source: merged main `cc1c8724b9f15be6212fc1b21df7d1de3a4ddb76`.
- Runtime: local source installation, Python 3.13.5. This is not a published
  0.3.26 receipt.
- Scope: one public repository, existing user OAuth credential passed through
  an environment secret reference, read-only calls and a fresh named connection.
  Provider/account identifiers and raw evidence are omitted.
- Sequence: independent API reads, create/probe/configure, two materialized
  syncs, independent API rereads, integrity and snapshot-chain verification.

| Check                       | Observed result                                                                                                                                          |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Collection                  | Seven records on each successful sync; no duplicates; stable event IDs                                                                                   |
| Source reconciliation       | 32 code-scanning alerts (29 fixed, three dismissed), three fixed Dependabot alerts, zero secret-scanning alerts; all matched independent paginated reads |
| Governance reconciliation   | Branch-protection fields, workflow permissions, collaborator/team counts and records matched independent reads                                           |
| Repeat differences          | Independent source reads unchanged; raw fields unchanged except observation timestamps and derived hashes; requirement verdicts unchanged                |
| Change-approval observation | Collector reported pass for the checked default-branch settings                                                                                          |
| CCF safeguard               | `SG-CHANGEAPPROVAL-001` remained `not_evaluated`: no declared evidence-type contract                                                                     |
| Framework assessment        | 2,198 requirements `not_evaluated`, 86 unmapped; no attested pass inferred from branch settings                                                          |
| Graph explanations          | SOC2-CC8.1, SOC2-CC7.2 and SOC2-CC6.1 graph CCF states matched the assessment                                                                            |
| Integrity                   | Evidence integrity and snapshot-chain checks passed                                                                                                      |
| Credential handling         | No plaintext credential found in retained JSON, JSONL, log or Markdown trial outputs                                                                     |

The first attempt failed during DNS resolution and was retained separately.
After DNS recovered, the fresh retry connection completed both syncs. The failed
attempt is not counted as successful collection. The safeguard result differs
from the older 0.3.21 receipt because the evidence-contract gate now blocks an
unsupported assessment, not because the source branch settings failed.

Alert details are intentionally aggregated rather than imported as individual
alert evidence; raw alert content and identities are omitted. This bounded run
does not reconcile all repository activity, prove organization rulesets, private
repository coverage, GitHub App onboarding, permission loss, live rate limits,
historical population completeness or operating effectiveness. Six governance
signals remain observations. No mappings or safeguard definitions were changed.
