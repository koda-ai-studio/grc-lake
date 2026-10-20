import { CheckCircle2, CircleAlert } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import type { AuditReadiness } from "@/lib/api/types";

/** Render the server's decision; do not independently recompute readiness. */
export function ReadinessDecision({
  decision,
}: {
  decision: AuditReadiness["readiness_decision"];
}) {
  if (!decision) return null;
  return (
    <section
      aria-label="Readiness decision"
      className="rounded-lg border border-line bg-surface p-4"
    >
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-ink">Why this status</h2>
        <p className="mt-1 text-xs text-muted">
          Every gate must pass. A high index cannot override a blocking gap.
        </p>
      </div>
      <ul className="grid gap-3 md:grid-cols-3">
        {decision.gates.map((gate) => {
          const Icon = gate.passed ? CheckCircle2 : CircleAlert;
          return (
            <li
              key={gate.id}
              className="min-w-0 rounded-md border border-line p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link
                  href={gate.href.replace(/^\/console/, "") || "/"}
                  className="inline-flex items-center gap-2 text-sm font-medium text-ink hover:underline"
                >
                  <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
                  {gate.label}
                </Link>
                <Badge tone={gate.passed ? "ready" : "attention"}>
                  {gate.passed ? "Met" : "Needs attention"}
                </Badge>
              </div>
              <p className="mt-2 text-xs leading-5 text-muted">{gate.detail}</p>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs leading-5 text-muted">{decision.boundary}</p>
    </section>
  );
}
