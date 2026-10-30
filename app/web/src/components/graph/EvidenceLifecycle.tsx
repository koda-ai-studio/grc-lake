import type { GraphNode } from "@/lib/api/types";
import { displayLabel } from "@/lib/display";
import { formatMinutes } from "@/lib/format";

export function EvidenceLifecycle({ node }: { node: GraphNode }) {
  const stages = [
    { label: "Observed at source", time: node.observed_at },
    { label: "Collected", time: node.collected_at },
    { label: "Freshness evaluated", time: node.freshness_evaluated_at },
  ];
  return (
    <section
      aria-label="Evidence lifecycle"
      className="rounded-lg border border-line p-3 text-sm"
    >
      <h3 className="font-semibold">Evidence lifecycle</h3>
      <ol className="mt-3 grid gap-3 border-l border-line pl-3">
        {stages.map((stage) => (
          <li key={stage.label} className="grid gap-1">
            <span className="font-medium">{stage.label}</span>
            {stage.time ? (
              <time
                dateTime={stage.time}
                className="break-all text-xs text-muted"
              >
                {stage.time}
              </time>
            ) : (
              <span className="text-xs text-muted">Not recorded</span>
            )}
          </li>
        ))}
      </ol>
      {node.freshness_evaluated_at && (
        <p className="mt-3 text-xs text-muted">
          Freshness at evaluation:{" "}
          {displayLabel(node.freshness_status ?? "unknown")}
        </p>
      )}
      {typeof node.freshness_age_minutes === "number" && (
        <p className="mt-2 text-xs text-muted">
          Age at evaluation: {formatMinutes(node.freshness_age_minutes)}
        </p>
      )}
      {node.freshness_expires_at && (
        <div className="mt-2 grid gap-1 text-xs text-muted">
          <span>Freshness deadline</span>
          <time dateTime={node.freshness_expires_at} className="break-all">
            {node.freshness_expires_at}
          </time>
        </div>
      )}
      <p className="mt-3 text-xs leading-5 text-muted">
        Review, remediation and re-verification require separate receipts. These
        timestamps do not establish framework attestation.
      </p>
    </section>
  );
}
