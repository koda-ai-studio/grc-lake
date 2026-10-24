# GitHub collection qualification

This is an offline contract for the `github-security` adapter. Tests use synthetic
responses and fixtures. It is not a live GitHub App installation test, a complete
repository inventory, or qualification of a published package. The
[matrix](CONNECTOR_QUALIFICATION.md) keeps those evidence levels separate.

## Collection behavior

| Concern                         | Tested behavior                                                                                                                                                                                                                          | Evidence pointer                                                                                                                                                                                                                                  |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Probe versus collection         | Probe validates configuration without contacting GitHub; sync fetches repository signals. A green probe does not establish provider access.                                                                                              | `test_probe_only_validates_configuration_not_github_access`                                                                                                                                                                                       |
| Access inventory                | Collaborators and teams continue beyond 100 records. Empty and short pages end collection.                                                                                                                                               | `test_access_inventory_collects_beyond_first_page`, `test_rate_limit_wait_is_honored_and_request_remains_read_only`                                                                                                                               |
| Alert lists                     | Code scanning and secret scanning use the bounded page-number paginator; more than 1,000 alert records can be collected. Dependabot rejects `page` with HTTP 400, so it follows `Link` cursors restricted to the same host and endpoint. | `tests/test_repo_governance.py::test_github_security_findings_not_truncated_below_1000`, `test_dependabot_alerts_follow_link_cursors_because_github_rejects_page_numbers`, `test_dependabot_cursor_cannot_redirect_the_token_to_another_endpoint` |
| Incomplete responses            | Repeated pages, non-object items and a full final page at the 1,000-page limit raise an error instead of returning a partial inventory.                                                                                                  | `test_repeated_page_cannot_be_counted_as_new_evidence`, `test_malformed_items_cannot_be_silently_dropped`, `test_page_budget_cannot_turn_an_incomplete_list_into_success`                                                                         |
| Permissions                     | A 401/403/404 yields an unavailable signal/category with its HTTP status. Other accessible categories remain visible; this is partial observability, not proof that no alerts exist.                                                     | `tests/test_repo_governance.py::test_github_security_findings_preserves_partial_permission_results`                                                                                                                                               |
| Rate limits and service failure | Read-only requests honor a bounded `Retry-After`. Exhausted 429/5xx errors propagate and fail sync rather than becoming permission evidence.                                                                                             | `test_rate_limit_wait_is_honored_and_request_remains_read_only`, `test_exhausted_http_failure_is_not_reported_as_permission_evidence`                                                                                                             |
| Failed sync                     | A collection error records a failed run and preserves the previous raw evidence and materialized posture.                                                                                                                                | `test_incomplete_live_path_preserves_prior_materialization`                                                                                                                                                                                       |
| Replay and source identity      | Identical fixtures at the same collection time reproduce event IDs, repository binding and evidence hashes. Recollection upserts stable event IDs.                                                                                       | `test_fixture_replay_preserves_identity_and_evidence_hashes`, `tests/test_connector_runner.py::test_connector_sync_upserts_stable_event_ids`                                                                                                      |
| Normalization and redaction     | Raw events validate and materialize through the normal runner; tokens and alert details are excluded or redacted.                                                                                                                        | `tests/test_connector_runner.py::test_github_connector_sync_writes_raw_and_materializes_lake`, `tests/test_repo_governance.py::test_governance_sync_redacts_secret_like_fields`                                                                   |

Unqualified test names above are in
[`tests/test_github_collection_contract.py`](../tests/test_github_collection_contract.py).
Run the selected contracts with:

```bash
uv run --frozen python -m pytest -q -o addopts='' \
  tests/test_github_collection_contract.py \
  tests/test_repo_governance.py tests/test_connector_runner.py
```

## Permission and scope boundaries

Use the catalog's [GitHub App permission declarations](CONNECTORS.md) and a
secret reference. Every API request remains a GET through the public-egress
guard. GitHub documents pagination for
[collaborators](https://docs.github.com/en/rest/collaborators/collaborators#list-repository-collaborators)
and [repository teams](https://docs.github.com/en/rest/repos/repos#list-repository-teams),
and cursor-only pagination for
[Dependabot alerts](https://docs.github.com/en/rest/dependabot/alerts#list-dependabot-alerts-for-a-repository).
List visibility depends on the principal and endpoint: repository teams are not
an organization-wide group-membership export. GitHub 403 responses can also
indicate rate limiting; inspect provider diagnostics before changing permissions.

The adapter binds events to the configured `OWNER/REPO`; fixture checks do not
independently attest ownership or prove that an installation can access every
desired repository. Page-number traversal is not a provider snapshot: records
can change between requests. Repeated-page detection does not prove that all
possible additions, deletions or overlaps were detected. Related provider contracts
are documented below; the GitHub tests do not qualify those providers.

For a separately authorized live run, record the exact application/package and
API version, time, installation scope, permissions and independent expected
inventory. Compare probe with complete sync, reconcile counts and unavailable
categories, replay the same input, and inspect normalized repository identity
and hashes. Keep failed attempts and raw provider receipts private. Add only a
sanitized, reviewer-accepted scope summary to the evidence index; no preview
promotion or mapping approval follows automatically.

## Related collection contracts

[`tests/test_collection_completeness.py`](../tests/test_collection_completeness.py)
exercises the following synthetic HTTP/SDK boundaries alongside each adapter's
existing fixture suite:

- GitLab members, groups and protected branches follow Link pagination; full pages
  without a Link use numbered continuation. Repeated pages/cursors and exhausted
  budgets fail. Continuations cannot change origin or endpoint before a token is sent.
- S3 bucket inventory consumes every page from the SDK paginator.
- Okta rejects repeated or foreign-origin Link targets before another request.
- Kubernetes uses bounded continuation and rejects repeated tokens.
- Jira rejects repeated pages and malformed rows; ClickHouse rejects repeated
  keyset cursors. Jamf and CrowdStrike reject empty pages when reported totals
  still indicate missing records.
- BambooHR, Rippling, Workday, Intune, Google Workspace, Jamf, CrowdStrike, SIEM
  and runtime list parsers reject malformed rows rather than silently omitting them.

These are collection failure contracts, not live-provider qualification. They do
not establish snapshot consistency under concurrent provider changes or prove
that every omission is detectable. GitLab documents [pagination and response
headers](https://docs.gitlab.com/api/rest/#pagination); AWS documents the
[ListBuckets paginator](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/paginator/ListBuckets.html).
