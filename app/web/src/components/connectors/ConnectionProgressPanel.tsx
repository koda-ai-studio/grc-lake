"use client";

import Link from "next/link";
import type { ConnectorView } from "@/lib/api/types";
import { connectionReadiness } from "@/lib/connection-readiness";
import { Button } from "@/components/ui/button";

export function ConnectionProgressPanel({
  connectors,
  onSelect,
}: {
  connectors: ConnectorView[];
  onSelect: (connector: ConnectorView) => void;
}) {
  const sources = connectors.filter((source) => source.is_implemented);
  const enabled = sources.filter((source) => source.state === "enabled");
  const recent = enabled.filter(
    (source) => connectionReadiness(source).evidenceReady,
  );
  const attention = sources.filter(
    (source) => connectionReadiness(source).attention,
  );
  const next =
    attention[0] ??
    enabled.find((source) => !connectionReadiness(source).evidenceReady);
  const progress = next ? connectionReadiness(next) : null;
  return (
    <section
      aria-labelledby="connection-progress-title"
      className="rounded-lg border border-line bg-surface p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h2
            id="connection-progress-title"
            className="text-base font-semibold text-ink"
          >
            From connection to evidence
          </h2>
        </div>
        <dl className="flex flex-wrap gap-5 text-sm">
          {[
            ["Enabled", enabled.length],
            ["With recent evidence", recent.length],
            ["Need attention", attention.length],
          ].map(([label, count]) => (
            <div key={label} className="flex flex-col-reverse gap-1">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className="text-xl font-semibold tabular-nums text-ink">
                {count}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-panel p-3">
        <div className="min-w-0 flex-1 basis-64">
          <h3 className="text-sm font-semibold text-ink">
            {next
              ? `${next.name}: ${progress?.label}`
              : recent.length
                ? "Your evidence is ready to inspect"
                : "Choose your first evidence source"}
          </h3>
          <details className="mt-1 text-xs text-muted">
            <summary className="cursor-pointer">Next-step details</summary>
            <p className="mt-2 leading-5">
              {progress?.detail ??
                (recent.length
                  ? "Open control results to evaluate collected evidence and review gaps. Collection alone does not establish compliance."
                  : "Pick a source below or use the setup guide. Configuration and access checks come before collection.")}
            </p>
          </details>
        </div>
        {next && progress ? (
          <Button size="sm" onClick={() => onSelect(next)}>
            {progress.action}
          </Button>
        ) : (
          <Button asChild size="sm">
            <Link href={recent.length ? "/dashboard" : "/onboarding"}>
              {recent.length ? "Evaluate controls" : "Open setup guide"}
            </Link>
          </Button>
        )}
      </div>
      <p className="mt-3 text-xs leading-5 text-muted">
        Recorded syncs, including demo data · not coverage or provider
        qualification.
      </p>
    </section>
  );
}
