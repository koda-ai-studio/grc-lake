"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  ClipboardCheck,
  ExternalLink,
  ListChecks,
  Plug,
  ShieldCheck,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FrameworkBadge } from "@/components/framework/FrameworkBadge";
import type {
  ComplianceGraph,
  GraphNode,
  GraphNodeKind,
} from "@/lib/api/types";
import { ConnectorMark } from "@/components/connectors/ConnectorMark";
import {
  SOURCE_CONNECTOR,
  sourceDetailHref,
} from "@/lib/evidence-source-links";
import {
  graphCheckGuidance,
  graphEvidenceState,
  graphRecordLabel,
} from "@/lib/graph-evidence";
import { displayLabel } from "@/lib/display";

const KIND_TONE: Record<
  GraphNodeKind,
  "info" | "ready" | "attention" | "critical"
> = {
  framework: "info",
  ccf_category: "info",
  ccf_family: "info",
  safeguard: "ready",
  environment: "info",
  account: "info",
  source: "info",
  vendor: "attention",
  finding: "critical",

  control: "ready",
  evidence_type: "attention",
  asset: "critical",
  repository: "info",
  directory: "ready",
  language: "ready",
  evidence_signal: "attention",
  governance_signal: "info",
  signal_gap: "critical",
  workflow: "attention",
  dependency_manifest: "attention",
  ownership_file: "ready",
  security_file: "ready",
  file: "info",
  principal: "critical",
  team: "info",
  review_rule: "ready",
  status_check: "ready",
  workflow_permission: "attention",
  evidence: "info",
};

interface Props {
  node: GraphNode | null;
  graphMode: "compliance" | "repository" | "investigation";
  onClose: () => void;
  onFocusPath?: () => void;
  graph?: ComplianceGraph;
  onInspectNode?: (node: GraphNode) => void;
}

function primaryHref(node: GraphNode): { href: string; label: string } | null {
  if (node.kind === "finding")
    return { href: "/violations", label: "Review finding and remediation" };
  if (node.kind === "vendor")
    return { href: "/vendor-risk", label: "Review vendor assessment" };
  if (node.kind === "source")
    return {
      href: sourceDetailHref(node.provider ?? node.label),
      label: "Review source connection",
    };
  if (node.kind === "control") {
    return { href: "/controls", label: "Open controls workbench" };
  }
  if (node.kind === "evidence" || node.kind === "evidence_type") {
    return { href: "/evidence", label: "Open evidence room" };
  }
  if (node.kind === "signal_gap") {
    return {
      href: node.provider ? sourceDetailHref(node.provider) : "/connectors",
      label: "Configure governance connector",
    };
  }
  if (node.kind === "governance_signal") {
    return { href: "/connectors", label: "Review connector sync" };
  }
  if (node.kind === "repository") {
    return {
      href: node.provider ? sourceDetailHref(node.provider) : "/connectors",
      label: "Review repository source",
    };
  }
  return null;
}

export function GraphNodeDrawer({
  node,
  graphMode,
  onClose,
  onFocusPath,
  graph,
  onInspectNode,
}: Props) {
  const action = node ? primaryHref(node) : null;
  const isPublicGap =
    node?.kind === "signal_gap" &&
    (node.label === "not_available_public_mode" ||
      node.subtitle?.includes("authenticated"));

  if (!node) return null;
  const isEvidence = ["evidence", "evidence_type", "signal_gap"].includes(
    node.kind,
  );
  const outcome = graphEvidenceState(node);
  const relatedIds = new Set(
    graph?.edges.flatMap((edge) =>
      edge.target === node.id && edge.kind === "evidence_covers_asset"
        ? [edge.source]
        : edge.source === node.id &&
            ["has_finding", "has_signal", "has_governance_signal"].includes(
              edge.kind,
            )
          ? [edge.target]
          : [],
    ),
  );
  const related = graph?.nodes.filter((item) => relatedIds.has(item.id)) ?? [];
  return (
    <aside
      aria-label="Selected graph node"
      className="min-w-0 self-start rounded-xl border border-line bg-surface xl:max-h-[650px] xl:overflow-auto"
    >
      <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-line bg-surface p-4">
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-semibold text-muted">Selected node</p>
          <h2 className="break-words text-base font-semibold">{node.label}</h2>
          {node.subtitle && (
            <p className="mt-1 break-words text-sm text-muted">
              {node.subtitle}
            </p>
          )}
        </div>
        <Button size="icon" aria-label="Close node details" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="grid gap-4 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={KIND_TONE[node.kind]}>{displayLabel(node.kind)}</Badge>
          {node.framework_id && (
            <FrameworkBadge frameworkId={node.framework_id} />
          )}
          {node.provider && (
            <Link
              href={sourceDetailHref(node.provider)}
              className="rounded-lg hover:bg-surface-2"
              aria-label="Review observed provider"
            >
              <ConnectorMark
                connectorId={SOURCE_CONNECTOR[node.provider] ?? node.provider}
                showVendor
                size="sm"
              />
            </Link>
          )}
        </div>

        {node.basis && <p className="text-sm text-muted">{node.basis}</p>}
        {(node.control_ids?.length ?? 0) > 0 && (
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              {node.kind === "finding"
                ? "Impacted controls"
                : "Linked controls"}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {node.control_ids!.map((controlId) => (
                <Link
                  key={controlId}
                  href="/controls"
                  className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-semibold hover:border-brand"
                >
                  <ShieldCheck className="h-3 w-3" />
                  {controlId}
                </Link>
              ))}
            </div>
          </div>
        )}

        {isEvidence && (
          <div className="rounded-lg border border-line p-3 text-sm">
            <Badge tone={outcome.tone}>{outcome.label}</Badge>
            <p className="mt-2 text-xs leading-5 text-muted">
              {outcome.action}
            </p>
          </div>
        )}
        {node.kind === "repository" && graph && (
          <section
            aria-label="Visible repository evidence"
            className="grid gap-2"
          >
            <h3 className="text-sm font-semibold">
              Visible evidence and findings
            </h3>
            <p className="text-xs text-muted">
              Recorded links in this view. An absent record does not establish a
              missing setting.
            </p>
            {related.slice(0, 8).map((item) => (
              <button
                key={item.id}
                className="grid gap-1 rounded-lg border border-line p-2 text-left hover:border-brand"
                onClick={() => onInspectNode?.(item)}
              >
                <span className="text-xs font-semibold">
                  {graphRecordLabel(item)}
                </span>
                <span className="text-xs text-muted">
                  {item.kind === "finding"
                    ? `${displayLabel(item.severity)} · ${displayLabel(item.status)}`
                    : graphEvidenceState(item).label}
                </span>
              </button>
            ))}
            {related.length === 0 && (
              <p className="text-xs text-muted">
                Explore this repository or increase depth to inspect its
                recorded connections.
              </p>
            )}
            {related.length > 8 && (
              <p className="text-xs text-muted">
                Showing 8 of {related.length} visible records. Explore the
                repository to narrow the view.
              </p>
            )}
          </section>
        )}
        {(isEvidence || node.kind === "finding") &&
          graphCheckGuidance(node) && (
            <p className="text-xs leading-5 text-muted">
              {graphCheckGuidance(node)}
            </p>
          )}
        {node.next_action && (
          <p className="text-sm">
            <b>Next action:</b> {node.next_action}
          </p>
        )}
        {onFocusPath && (
          <Button onClick={onFocusPath}>Focus this evidence path</Button>
        )}
        {isPublicGap && (
          <div className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning-bg p-3 text-sm text-warning-fg">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" />
            <p>
              This signal is not available in public audit mode. Run an
              authenticated GitHub or GitLab governance sync to populate private
              branch rules, collaborators, and security settings.
            </p>
          </div>
        )}

        {action && (
          <Button variant="primary" asChild>
            <Link href={action.href}>
              {action.label}
              <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        )}
        <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
          {(
            [
              ["Status", node.status],
              ["Severity", node.severity],
              ["Source account", node.source_account_id],
              ["Observed", node.observed_at],
            ] as const
          )
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted">{label}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ))}
          {node.owner && (
            <>
              <dt className="text-muted">Owner</dt>
              <dd className="font-semibold">{node.owner}</dd>
            </>
          )}
          {node.environment && (
            <>
              <dt className="text-muted">Environment</dt>
              <dd className="font-semibold">{node.environment}</dd>
            </>
          )}
          {node.evidence_id && (
            <>
              <dt className="text-muted">Evidence id</dt>
              <dd className="font-semibold">{node.evidence_id}</dd>
            </>
          )}
          {node.evidence_ref && (
            <>
              <dt className="text-muted">Evidence ref</dt>
              <dd className="break-all text-xs">{node.evidence_ref}</dd>
            </>
          )}
          {node.event_type && (
            <>
              <dt className="text-muted">Event type</dt>
              <dd className="font-semibold">{node.event_type}</dd>
            </>
          )}
          {node.freshness_status && (
            <>
              <dt className="text-muted">Freshness</dt>
              <dd className="font-semibold">{node.freshness_status}</dd>
            </>
          )}
          {node.severity && (
            <>
              <dt className="text-muted">Severity</dt>
              <dd className="font-semibold">{displayLabel(node.severity)}</dd>
            </>
          )}
        </dl>

        <details className="rounded-lg border border-line p-3 text-xs">
          <summary className="cursor-pointer font-semibold">
            Technical identifiers
          </summary>
          <dl className="mt-2 grid gap-1">
            <dt className="text-muted">Node id</dt>
            <dd className="break-all">{node.id}</dd>
            {node.raw_sha256 && (
              <>
                <dt className="text-muted">Evidence hash</dt>
                <dd className="break-all">{node.raw_sha256}</dd>
              </>
            )}
          </dl>
        </details>
        <div className="flex flex-wrap gap-2 border-t border-line pt-4">
          {graphMode === "repository" && (
            <>
              <Button variant="default" asChild>
                <Link href="/remediation">
                  <ListChecks className="h-4 w-4" />
                  Remediation tasks
                </Link>
              </Button>
              <Button variant="default" asChild>
                <Link href="/violations">
                  <ClipboardCheck className="h-4 w-4" />
                  Violations queue
                </Link>
              </Button>
            </>
          )}
          {node.evidence_ref?.startsWith("http") && (
            <Button variant="default" asChild>
              <a href={node.evidence_ref} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" />
                Source API
              </a>
            </Button>
          )}
          {isPublicGap && (
            <Button variant="default" asChild>
              <Link href="/connectors">
                <Plug className="h-4 w-4" />
                Connectors
              </Link>
            </Button>
          )}
        </div>
      </div>
    </aside>
  );
}
