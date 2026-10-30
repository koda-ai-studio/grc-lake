"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { ConnectorView } from "@/lib/api/types";
import { useAuditorMode } from "@/lib/state/auditor";

export function NamedConnectionCreate({
  connectors,
  onToast,
}: {
  connectors: ConnectorView[];
  onToast: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [account, setAccount] = useState("");
  const [provider, setProvider] = useState("aws-posture");
  const query = useQueryClient();
  const auditor = useAuditorMode();
  const create = useMutation({
    mutationFn: api.createConnection,
    onSuccess: async () => {
      await query.invalidateQueries({ queryKey: ["connectors"] });
      setOpen(false);
      setId("");
      setName("");
      setAccount("");
      onToast(
        "Connection created. Open it to configure read-only access and test the account.",
      );
    },
  });
  const providers = [
    ...new Map(
      connectors
        .filter((row) => row.is_implemented)
        .map((row) => [row.connector_id, row]),
    ).values(),
  ];
  if (auditor) return null;
  const field =
    "w-full min-w-0 rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink";
  return (
    <section
      className="rounded-lg border border-line bg-surface p-4"
      aria-label="Account connections"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold text-ink">Multiple accounts</p>
          <p className="text-sm text-muted">
            Keep each account connected with its own access, schedule, and
            collection history.
          </p>
        </div>
        <Button type="button" onClick={() => setOpen(!open)}>
          {open ? "Cancel" : "Add account connection"}
        </Button>
      </div>
      {open && (
        <form
          className="mt-4 grid min-w-0 gap-3 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({
              connection_id: id,
              connector_id: provider,
              source_account_id: account,
              name,
            });
          }}
        >
          <label className="grid gap-1 text-sm">
            Provider
            <select
              className={field}
              value={provider}
              onChange={(event) => setProvider(event.target.value)}
            >
              {providers.map((row) => (
                <option key={row.connector_id} value={row.connector_id}>
                  {row.vendor ?? row.name} · {row.connector_id}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Connection name
            <input
              className={field}
              required
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Production"
            />
          </label>
          <label className="grid gap-1 text-sm">
            Connection ID
            <input
              className={field}
              required
              pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}"
              maxLength={64}
              value={id}
              onChange={(event) => setId(event.target.value)}
              placeholder="aws-production"
            />
          </label>
          <label className="grid gap-1 text-sm">
            Source account ID
            <input
              className={field}
              required
              maxLength={256}
              value={account}
              onChange={(event) => setAccount(event.target.value)}
              placeholder="Provider account, tenant, or project identifier"
            />
          </label>
          <p className="text-xs text-muted md:col-span-2">
            The account binding stays fixed. Collection rejects evidence from
            another account. Credentials are configured separately using secret
            references.
          </p>
          {create.error && (
            <p role="alert" className="text-sm text-danger-fg md:col-span-2">
              {create.error.message}
            </p>
          )}
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create connection"}
          </Button>
        </form>
      )}
    </section>
  );
}
