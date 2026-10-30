# Organization account scopes

An organization scope is a saved selection of named account connections inside one
GRC Lake tenant. It can contain any number of accounts across providers. A source
account, a saved connection and the authenticated platform tenant are separate
identities. An account may appear in multiple assessment scopes without sharing
credentials with another account.

## Start in the console

1. Open **Connections → Add account connection**. Supply the exact AWS account,
   Azure subscription or GCP project ID, then configure secret references or
   delegated read-only access. Test access before enabling each connection.
2. Choose **New organization scope**, name it and select the connections to assess.
   Unselected accounts remain connected and retain their evidence.
3. Choose **Collect selected accounts**. Every selected connection is attempted
   sequentially; a failure in one account does not skip the rest. An unavailable or
   partial account prevents complete selected-account collection coverage.
4. Choose **Evaluate saved evidence**. This captures each selected connection's
   committed input and produces a separate CCF assessment. Inspect its selected
   revision, coverage, unavailable accounts, and technical safeguard outcomes.
5. Use **Edit selection** to add or remove accounts. Saving creates a new revision.
   Prior evaluations keep their original selection and evidence. A queued operation
   for an older revision fails instead of collecting the newly selected accounts.

Selection is explicit. Discovery, successful access, collection coverage, technical
control outcomes, reviewed framework mappings and human attestation remain separate.
Complete collection of the selected connections does not establish that the selection
contains every account or asset in the real organization. CCF population completeness
remains `not_established`; this workflow does not promote mappings or attestations.

## CLI and automation

First configure the named connections described in [Connectors](CONNECTORS.md#named-account-connections).
Use repeatable `--connection-id` flags; there is no two-account model.

```bash
grc-lake organizations save --lake ./lake --organization-id production \
  --name Production --connection-id aws-production --connection-id azure-production \
  --connection-id gcp-production
grc-lake organizations ingest --lake ./lake --organization-id production
grc-lake organizations evaluate --lake ./lake --organization-id production
grc-lake organizations runs --lake ./lake --organization-id production
```

To change an existing selection, repeat `save` with the current
`--expected-revision`. Ingest returns a nonzero exit status when any selected account
is unavailable. Evaluation reports its local computation result separately from
selected-account coverage; a successful evaluation may correctly report partial
coverage and `not_evaluated` gaps.

HTTP clients use:

| Request                                                                 | Purpose                                                               |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `GET /api/v1/organizations`                                             | List saved selections                                                 |
| `POST /api/v1/organizations`                                            | Save `organization_id`, `name`, `connection_ids`, `expected_revision` |
| `POST /api/v1/organizations/{id}/ingest`                                | Collect the selected connections                                      |
| `POST /api/v1/organizations/{id}/evaluate`                              | Assess the captured inputs                                            |
| `GET /api/v1/organizations/{id}/runs`                                   | Read operation history                                                |
| `GET /api/v1/organizations/{id}/evaluations/{evaluation_id}/assessment` | Verify the input receipt and read its CCF summary                     |

Mutations require `connector_manage`; reads require `read`. For ingest, evaluation
and discovery, send `Prefer: respond-async`, an `Idempotency-Key` and the current
`expected_revision`. Poll the returned operation URL. A queued job is not a success.
The console uses this existing background-operation mechanism automatically.

MCP tools expose the same authority: `list_organizations`, `save_organization`,
`run_organization` and `organization_results`. Remote MCP uses the authenticated API
and requires `expected_revision` when starting an operation. Local MCP and CLI use
the operator's lake. Neither surface grants access to a different platform tenant.

## AWS organization discovery (Preview)

The console can list AWS organization accounts using an explicitly selected, enabled
management-account or delegated-administrator connection. That role additionally
needs read-only `organizations:ListAccounts`. It does not need provider write access.
Existing single-account roles do not automatically gain this permission.

```bash
grc-lake organizations discover --lake ./lake --organization-id production \
  --connection-id aws-management
```

The implementation follows [AWS ListAccounts](https://docs.aws.amazon.com/organizations/latest/APIReference/API_ListAccounts.html):
20 accounts per page, following `NextToken` even on empty pages, and reading `State`
rather than the retired `Status` field. The default budget is 100 pages. Denials,
malformed pages, repeated tokens or exhausted budgets report incomplete discovery.
Names, account IDs and state are returned; account emails are omitted.

Discovery never enables members or changes the selected population. Use **Add
connection** for a discovered active account, configure and test that account's
read-only access, then explicitly add it to a scope. Discovery does not prove that
member roles are deployed or assumable. Azure/GCP organization discovery and automatic
member-role provisioning are not implemented by this workflow; named connections for
those providers can still be selected manually. Validation uses synthetic provider
fixtures, not live organization qualification.

## Self-hosted persistence and verification

Keep the full tenant lake on persistent storage, including `connections/` and
`organizations/`. Do not mount only `gold/`: account configuration, cursors, raw input
and scope history live outside it. Credentials remain references to the operator's
secret system; organization receipts contain configuration digests, not credential
copies. Existing distributed workspace publication includes these directories and
continues enforcing its configured file/byte budgets.

Each evaluation lives under
`organizations/<id>/evaluations/<evaluation_id>/`. Its `scope.json` pins the scope
revision, canonical raw-input hashes, configuration hashes and sync-record digests.
The scope-receipt digest is embedded in the evaluated raw evidence, which is retained
in the normal immutable generation. The assessment endpoint verifies generation
integrity and the receipt digest before returning the CCF summary. Changing a receipt
cannot silently relabel an earlier assessment.

Collection is sequential, with existing per-provider request and response bounds.
Scoped evaluation uses the existing local capacity gates and does not inherit the
tenant-wide warehouse destination. Inputs that require warehouse evaluation are
held with `warehouse_required`; a separate scoped warehouse destination is not yet
implemented. Account-count support is
not a production-scale benchmark. Size storage and backup retention for the number
of connections and retained evaluations; deleting one connection's history is not a
way to remove an account from an audit scope—save a new selection instead.
