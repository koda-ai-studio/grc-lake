# Explore an AI environment from discovery to evidence

Start with what is present: models, agents, owners, source accounts and their
recorded observations. Then inspect configuration and control evidence. An asset
without a passing control is still an asset worth investigating.

## Run the synthetic AI lab

From a source checkout containing this change (the `--company` demo option is
unreleased):

```bash
uv run --extra server grc-lake demo --company ai_lab
```

This opens **AI governance** on loopback with a temporary lake. No credentials or
provider access are needed. Ctrl+C stops the server and deletes the lake. Use
`--no-browser` to print the URL, or `--port 8791` if the default port is occupied.
The existing `grc-lake demo` still opens the general company dashboard.

The AI lab contains synthetic records for one model, two inference agents,
a repository, a container, an MCP server, a cloud role, identity access and an
audit trail. The AI worklist shows the model and two agents; supporting assets
remain available through evidence and the graph. This is a recorded example,
not live discovery or a complete infrastructure inventory.

## Follow one record

1. In **Models and agents**, open the reranker model or an inference agent. Check
   its exact identifier, owner, source account and last observation. Generic
   `agent` records enter this worklist only when backed by recorded inference or
   tool-call events; a monitoring-agent heartbeat alone is not AI inventory.
2. Inspect the recorded evidence and use **Graph** to follow the source,
   observation and affected asset. An edge means a recorded relationship; it does
   not prove network reachability. Use the existing Fit View and zoom controls
   to move between the full structure and readable labels.
3. Compare a technical control result with its CCF/framework result. Proposed
   mappings are not attestations, and a recorded blocked action is not proof that
   every action is protected. Missing model cards, unknown configuration and
   collection gaps remain visible work to investigate.

The demo deliberately preserves those distinctions. It does not turn inventory,
a synthetic example, or an unreviewed mapping into a compliance pass.

## Move to a bounded real evaluation

Use the [pilot guide](PILOT.md) and an [authenticated deployment](DEPLOYMENT.md)
for real evidence. Keep the temporary unauthenticated demo separate from that
installation. Choose one source account or cluster and check one known asset's
configuration against the provider before relying on the result.

For Kubernetes, inspect the connector's [read-only scope and collected fields](CONNECTORS.md#kubernetes-cluster-configuration-baseline-preview)
and [qualification evidence](CONNECTOR_QUALIFICATION.md). Review successful reads,
permission gaps and unsupported scopes separately. Workload device requests and
node-reported capacity do not establish hardware utilization or fleet-wide
GPU/TPU, VM or bare-metal coverage.

Repeat collection after an independently confirmed change, then retain and verify
an [auditor workpaper](AUDITOR_WALKTHROUGH.md). If the workflow fails, report the
reproduction steps and version using the [contribution guide](../CONTRIBUTING.md);
keep credentials, account identifiers and real evidence out of public reports.
