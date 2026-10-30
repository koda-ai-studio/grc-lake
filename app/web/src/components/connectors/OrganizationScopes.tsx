"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useAuditorMode } from "@/lib/state/auditor";
import type {
  ConnectorView,
  OrganizationScope,
  OrganizationRun,
} from "@/lib/api/types";

export function OrganizationScopes({
  connectors,
}: {
  connectors: ConnectorView[];
}) {
  const auditor = useAuditorMode();
  const query = useQueryClient();
  const scopes = useQuery({
    queryKey: ["organizations"],
    queryFn: api.organizations,
  });
  const [editing, setEditing] = useState<OrganizationScope | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<OrganizationRun | null>(null);
  const [active, setActive] = useState<OrganizationScope | null>(null);
  const [discoveryConnection, setDiscoveryConnection] = useState("");
  const connections = connectors.filter((row) => row.connection_id);
  const runs = useQuery({
    queryKey: ["organization-runs", active?.organization_id],
    queryFn: () => api.organizationRuns(active!.organization_id),
    enabled: !!active,
  });
  const assessment = useQuery({
    queryKey: [
      "organization-assessment",
      active?.organization_id,
      result?.evaluation_id,
    ],
    queryFn: () =>
      api.organizationAssessment(
        active!.organization_id,
        result!.evaluation_id!,
      ),
    enabled: !!active && !!result?.evaluation_id,
  });
  const save = useMutation({
    mutationFn: api.saveOrganization,
    onSuccess: async (value) => {
      setEditing(null);
      setActive(value);
      setResult(null);
      await query.invalidateQueries({ queryKey: ["organizations"] });
    },
  });
  const run = useMutation({
    mutationFn: (action: "ingest" | "evaluate" | "discover") =>
      api.runOrganization(
        active!.organization_id,
        action,
        active!.revision,
        discoveryConnection,
      ),
    onSuccess: async (value) => {
      setResult(value);
      await query.invalidateQueries({ queryKey: ["organization-runs"] });
      await query.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
  const add = useMutation({
    mutationFn: (account: { source_account_id: string; name: string }) =>
      api.createConnection({
        connection_id: `aws-${account.source_account_id}`,
        connector_id: "aws-posture",
        source_account_id: account.source_account_id,
        name: account.name,
      }),
    onSuccess: () => query.invalidateQueries({ queryKey: ["connectors"] }),
  });
  const edit = (scope: OrganizationScope) => {
    setEditing(scope);
    setSelected(scope.connection_ids);
  };
  const field =
    "min-w-0 rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink";
  return (
    <section
      className="min-w-0 rounded-lg border border-line bg-surface p-4"
      aria-label="Organization scopes"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-ink">Organization scopes</h2>
          <p className="text-sm text-muted">
            Choose the accounts for each assessment. Collection coverage applies
            only to that saved selection.
          </p>
        </div>
        {!auditor && (
          <Button
            onClick={() =>
              edit({
                organization_id: "",
                name: "",
                connection_ids: [],
                revision: 0,
              })
            }
          >
            New organization scope
          </Button>
        )}
      </div>
      {scopes.error && <p role="alert">{scopes.error.message}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {scopes.data?.map((scope) => (
          <Button
            key={scope.organization_id}
            onClick={() => {
              setActive(scope);
              setResult(null);
            }}
          >
            {scope.name} · {scope.connection_ids.length} accounts
          </Button>
        ))}
      </div>
      {editing && !auditor && (
        <form
          className="mt-4 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate({
              organization_id: editing.organization_id,
              name: editing.name,
              connection_ids: selected,
              expected_revision: editing.revision,
            });
          }}
        >
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm">
              Organization ID
              <input
                className={field}
                required
                pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
                disabled={editing.revision > 0}
                value={editing.organization_id}
                onChange={(e) =>
                  setEditing({ ...editing, organization_id: e.target.value })
                }
              />
            </label>
            <label className="grid gap-1 text-sm">
              Organization name
              <input
                className={field}
                required
                maxLength={120}
                value={editing.name}
                onChange={(e) =>
                  setEditing({ ...editing, name: e.target.value })
                }
              />
            </label>
          </div>
          <fieldset className="grid max-h-60 gap-2 overflow-auto rounded-md border border-line p-3">
            <legend className="text-sm">Selected account connections</legend>
            {connections.length === 0 && (
              <p className="text-sm text-muted">
                Add account connections below first.
              </p>
            )}
            {connections.map((row) => (
              <label
                key={row.connection_id}
                className="flex items-center gap-2 break-all text-sm"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(row.connection_id!)}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? [...selected, row.connection_id!]
                        : selected.filter((id) => id !== row.connection_id),
                    )
                  }
                />
                {row.name} · {row.source_account_id}
              </label>
            ))}
          </fieldset>
          <div className="flex gap-2">
            <Button type="submit" disabled={!selected.length || save.isPending}>
              Save scope
            </Button>
            <Button type="button" onClick={() => setEditing(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {active && (
        <div className="mt-4 grid gap-3 border-t border-line pt-4">
          <p className="font-semibold">
            {active.name} · revision {active.revision}
          </p>
          <p className="break-words text-xs text-muted">
            Selected connections: {active.connection_ids.join(", ")}
          </p>
          {!auditor && (
            <>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => edit(active)}>Edit selection</Button>
                <Button
                  disabled={run.isPending}
                  onClick={() => run.mutate("ingest")}
                >
                  Collect selected accounts
                </Button>
                <Button
                  disabled={run.isPending}
                  onClick={() => run.mutate("evaluate")}
                >
                  Evaluate saved evidence
                </Button>
              </div>
              <details className="text-sm">
                <summary className="cursor-pointer">
                  Discover AWS organization accounts
                </summary>
                <p className="my-2 text-muted">
                  Requires an enabled management or delegated administrator
                  connection with organizations:ListAccounts. Discovery does not
                  prove access or add accounts to this scope.
                </p>
                <div className="flex flex-wrap gap-2">
                  <select
                    aria-label="AWS discovery connection"
                    className={field}
                    value={discoveryConnection}
                    onChange={(e) => setDiscoveryConnection(e.target.value)}
                  >
                    <option value="">Select AWS connection</option>
                    {connections
                      .filter((row) => row.connector_id === "aws-posture")
                      .map((row) => (
                        <option
                          key={row.connection_id}
                          value={row.connection_id}
                        >
                          {row.name}
                        </option>
                      ))}
                  </select>
                  <Button
                    disabled={!discoveryConnection || run.isPending}
                    onClick={() => run.mutate("discover")}
                  >
                    Discover accounts
                  </Button>
                </div>
              </details>
            </>
          )}
          {run.isPending && (
            <p role="status" className="text-sm">
              Operation running…
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {runs.data?.slice(0, 10).map((entry, index) => (
              <Button key={index} onClick={() => setResult(entry)}>
                {entry.kind} ·{" "}
                {entry.result ?? (entry.complete ? "complete" : "incomplete")} ·
                r{entry.scope.revision}
              </Button>
            ))}
          </div>
          {result && (
            <div className="grid gap-2 rounded-md bg-subtle p-3 text-sm">
              <p className="font-semibold">
                {result.kind} ·{" "}
                {result.result ?? (result.complete ? "complete" : "incomplete")}{" "}
                · scope revision {result.scope.revision}
              </p>
              {result.coverage && (
                <p>
                  Selected-account collection coverage: {result.coverage}.{" "}
                  {result.unavailable_connections?.length
                    ? `Unavailable: ${result.unavailable_connections.join(", ")}`
                    : ""}
                </p>
              )}
              {result.error && <p role="alert">{result.error}</p>}
              {result.connections?.map((row) => (
                <p key={row.connection_id}>
                  {row.connection_id}: {row.result} ·{" "}
                  {row.available ? "collected" : "needs evidence"}
                </p>
              ))}
              {result.accounts?.map((account) => (
                <div
                  key={account.source_account_id}
                  className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2"
                >
                  <span>
                    {account.name} · {account.source_account_id} ·{" "}
                    {account.state} · Access not tested
                  </span>
                  {!auditor &&
                    !connections.some(
                      (row) =>
                        row.connector_id === "aws-posture" &&
                        row.source_account_id === account.source_account_id,
                    ) && (
                      <Button
                        disabled={add.isPending || account.state !== "ACTIVE"}
                        onClick={() => add.mutate(account)}
                      >
                        Add connection
                      </Button>
                    )}
                </div>
              ))}
              {assessment.data && (
                <p>
                  CCF safeguards: {assessment.data.safeguards.length}. Technical
                  passes:{" "}
                  {
                    assessment.data.safeguards.filter(
                      (s) => s.status === "pass",
                    ).length
                  }
                  . Missing evidence, mapping review and human attestation
                  remain separate requirements.
                </p>
              )}
              {result.evaluation_id && (
                <p className="break-all text-xs text-muted">
                  Saved evaluation: {result.evaluation_id}
                </p>
              )}
            </div>
          )}
        </div>
      )}
      {[save.error, run.error, add.error, assessment.error, runs.error]
        .filter(Boolean)
        .map((error, index) => (
          <p role="alert" key={index} className="mt-2 text-sm text-danger-fg">
            {error!.message}
          </p>
        ))}
    </section>
  );
}
