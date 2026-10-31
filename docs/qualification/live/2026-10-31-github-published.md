# Published GitHub connector receipt: 2026-10-31

<a id="github-security"></a>

- Adapter: `github-security`; existing Implemented stage retained.
- Execution window: October 31, 2026, 04:35:39–04:35:58 UTC.
- Artifact: fresh PyPI `grc-lake[server,mcp]==0.3.21`, CPython 3.13.5, outside
  the source checkout. Release source `2aced4a393a5768d528f6ddd7d0514bcb907e488`.
- Published wheel SHA-256: `234aa26cdc0c13fd7e9c3f7433b933299c455079df1d7ee2b6cbd965f87e5c2a`;
  matched the GitHub asset and verified release provenance.
- Operator: maintainer-authorized automated qualification.
- Scope: one public repository, existing user OAuth token through an environment
  secret reference, read-only GitHub calls, and a fresh local named connection.
  This is not a GitHub App installation or browser onboarding trial.
- Sequence: `connections create`, `connectors probe`, `connectors configure`,
  two `connectors sync` calls, `pipeline verify-integrity`, then
  `assessment verify-snapshots`. Provider identifiers and secret values omitted.

| Check                   | Observed result                                                                                                | Limit                                                                                     |
| ----------------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Probe                   | Successful live probe; all three alert categories readable; partial=false                                      | One repository and one principal                                                          |
| First sync              | Seven governance records, materialized successfully                                                            | Current observations; not full historical inventory                                       |
| Provider reconciliation | 32 code-scanning alerts: 29 fixed, three dismissed; two fixed Dependabot alerts; zero secret-scanning alerts   | Counts and states matched independent paginated GitHub API reads before and after the run |
| Branch protection       | One required approval, administrators included, force pushes and deletions disabled                            | Default branch only                                                                       |
| Replay                  | Seven records, stable event IDs, zero duplicates                                                               | Observation times and evidence hashes may change on recollection                          |
| Account boundary        | Every collected row matched the immutable named connection's source account                                    | One positive account-binding path; cross-account denial remains separately tested offline |
| Assessment              | `SG-CHANGEAPPROVAL-001` passed; one framework requirement passed, 2,197 remained not_evaluated and 86 unmapped | Proposed mappings remained non-attestable; no mapping approval                            |
| Integrity               | Lake and historical snapshot verification passed                                                               | Hash consistency does not independently authenticate the provider                         |
| Secret handling         | No token persisted in the trial files or command outputs                                                       | Credential reference and private raw records retained outside the repository              |

This receipt qualifies only the stated read-only run of the published package.
It does not establish private repositories, GitHub App installations, organization
rulesets, live 429/credential-expiry handling, other providers, production capacity,
operating effectiveness or certification. No provider resources were created or
changed. The [earlier receipt](2026-10-26-aws-github-binding.md#github-security)
retains its original source and scope.
