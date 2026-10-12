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
import type { GraphNode, GraphNodeKind } from "@/lib/api/types";
import { sourceDetailHref } from "@/lib/evidence-source-links";
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
      href: "/connectors/?connect=github-security",
      label: "Configure governance connector",
    };
  }
  if (node.kind === "governance_signal") {
    return { href: "/connectors", label: "Review connector sync" };
  }
  if (node.kind === "repository") {
    return {
      href: "/connectors/?connect=github-security",
      label: "Link repository source",
    };
  }
  return null;
}

export function GraphNodeDrawer({
  node,
  graphMode,
  onClose,
  onFocusPath,
}: Props) {
  const action = node ? primaryHref(node) : null;
  const isPublicGap =
    node?.kind === "signal_gap" &&
    (node.label === "not_available_public_mode" ||
      node.subtitle?.includes("authenticated"));

  if (!node) return null;
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
      {node && (
        <div className="grid gap-4 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={KIND_TONE[node.kind]}>{displayLabel(node.kind)}</Badge>
            {node.framework_id && (
              <FrameworkBadge frameworkId={node.framework_id} />
            )}
            {node.provider && <Badge>{node.provider}</Badge>}
          </div>

          {node.basis && <p className="text-sm text-muted">{node.basis}</p>}
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
                authenticated GitHub or GitLab governance sync to populate
                private branch rules, collaborators, and security settings.
              </p>
            </div>
          )}

          <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
            {(
              [
                ["Status", node.status],
                ["Severity", node.severity],
                ["Source account", node.source_account_id],
                ["Observed", node.observed_at],
                ["Evidence hash", node.raw_sha256],
              ] as const
            )
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-muted">{label}</dt>
                  <dd className="break-all">{value}</dd>
                </div>
              ))}
            <dt className="text-muted">Node id</dt>
            <dd>
              <code className="break-all text-xs">{node.id}</code>
            </dd>
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

          {(node.control_ids?.length ?? 0) > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                Linked controls
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

          <div className="flex flex-wrap gap-2 border-t border-line pt-4">
            {action && (
              <Button variant="primary" asChild>
                <Link href={action.href}>
                  {action.label}
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            )}
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
      )}
    </aside>
  );
}
