"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "@/components/theme/ThemeProvider";
import dagre from "@dagrejs/dagre";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Background,
  BaseEdge,
  getSmoothStepPath,
  type EdgeProps,
  Handle,
  Position,
  MarkerType,
  Controls,
  ControlButton,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  getNodesBounds,
  getViewportForBounds,
  useReactFlow,
  useUpdateNodeInternals,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Boxes,
  CheckCircle2,
  CircleDashed,
  ClipboardCheck,
  Clock3,
  Code2,
  FileCode2,
  FileText,
  FolderTree,
  GitBranch,
  LockKeyhole,
  Network,
  Package,
  Server,
  Scan,
  ShieldCheck,
  ShieldQuestion,
  UserRound,
  Users,
  Workflow,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  graphEdgeInvalid,
  graphEvidenceState,
  graphHasOutcome,
  graphKindLabel,
  graphMappingReview,
  graphNodeAriaLabel,
  graphRecordLabel,
} from "@/lib/graph-evidence";
import {
  GRAPH_LAYOUT_NODE_CAP,
  GRAPH_LAYOUT_EDGE_CAP,
  GRAPH_READABLE_ZOOM,
  graphLayoutBudget,
  graphScope,
  investigationPositions,
  investigationRoute,
  graphAssuranceKind,
} from "@/lib/graph-layout";
import { formatCount } from "@/lib/format";
import { displayLabel as statusLabel } from "@/lib/display";
import { SOURCE_CONNECTOR } from "@/lib/evidence-source-links";
import { GRAPH_KIND_COLOR } from "@/lib/graph-palette";
import { ConnectorMark } from "@/components/connectors/ConnectorMark";
import { controlFamily } from "@/components/framework/ControlFamilyIcon";
import { FrameworkBadge } from "@/components/framework/FrameworkBadge";
import type {
  ComplianceGraph,
  GraphNode,
  GraphNodeKind,
} from "@/lib/api/types";
import { STALE_FRESHNESS } from "@/lib/evidence-status";

interface GraphNodeData extends Record<string, unknown> {
  label: string;
  subtitle: string;
  status?: string;
  freshness_status?: string;
  ccf_status?: string;
  severity?: string;
  kind: GraphNodeKind;
  layout: LayoutDir;
  compact?: boolean;
  provider?: string;
  bank?: "left" | "right";
  relationshipLabel?: string;
  neighborhoodRoot?: boolean;
  framework_id?: string;
  family_id?: string;
  owner?: string;
  risk_score?: number;
  /** Render emphasis driven by search / select / path-trace. */
  emphasis: "active" | "dimmed" | "highlight" | "path" | "match";
}

type FlowGraphNode = Node<GraphNodeData, "trustops-graph">;

const KIND_STYLE: Partial<
  Record<GraphNodeKind, { border: string; chip: string }>
> = Object.fromEntries(
  Object.entries(GRAPH_KIND_COLOR).map(([kind, color]) => [
    kind,
    { border: color, chip: color },
  ]),
);

const KIND_ICON: Partial<Record<GraphNodeKind, LucideIcon>> = {
  framework: BookOpen,
  canonical_entity: Boxes,
  entity_alias: ClipboardCheck,
  ccf_category: BookOpen,
  ccf_family: FolderTree,
  safeguard: ShieldCheck,
  environment: Boxes,
  account: Boxes,
  source: Activity,
  vendor: Users,
  finding: AlertTriangle,

  control: ShieldCheck,
  evidence_type: FileText,
  asset: Server,
  repository: GitBranch,
  directory: FolderTree,
  language: Code2,
  evidence_signal: Activity,
  governance_signal: ClipboardCheck,
  signal_gap: AlertTriangle,
  workflow: Workflow,
  dependency_manifest: Package,
  ownership_file: Users,
  security_file: LockKeyhole,
  file: FileCode2,
  principal: UserRound,
  team: Users,
  review_rule: ShieldQuestion,
  status_check: CheckCircle2,
  workflow_permission: LockKeyhole,
  evidence: Boxes,
};

function emphasisClass(emphasis: GraphNodeData["emphasis"]): string {
  switch (emphasis) {
    case "dimmed":
      return "opacity-50 saturate-50";
    case "highlight":
      return "opacity-100 shadow-[0_0_0_3px_rgb(var(--rgb-ink)/0.18)]";
    case "path":
      return "opacity-100 shadow-[0_0_0_3px_rgb(var(--rgb-warning)/0.55)]";
    case "match":
      return "opacity-100 shadow-[0_0_0_3px_rgb(var(--rgb-success)/0.55)]";
    default:
      return "opacity-100";
  }
}

type OutcomeTone = ReturnType<typeof graphEvidenceState>["tone"];

const STATE_COLOR: Record<OutcomeTone, string> = {
  critical: "var(--color-danger)",
  ready: "var(--color-success)",
  attention: "var(--color-warning)",
  default: "var(--color-muted)",
};

// Each outcome gets its own shape so status never depends on colour alone.
const STATE_GLYPH: Record<OutcomeTone, LucideIcon> = {
  critical: XCircle,
  ready: CheckCircle2,
  attention: Clock3,
  default: CircleDashed,
};

function StatusGlyph({
  tone,
  compact,
}: {
  tone: OutcomeTone;
  compact: boolean;
}) {
  const Icon = STATE_GLYPH[tone];
  return (
    <span
      data-testid="graph-status-glyph"
      data-tone={tone}
      aria-hidden="true"
      className={`absolute -bottom-1 -right-1 grid place-items-center rounded-full border border-line bg-surface ${compact ? "h-5 w-5" : "h-7 w-7"}`}
      style={{ color: STATE_COLOR[tone] }}
    >
      <Icon className={compact ? "h-3.5 w-3.5" : "h-5 w-5"} strokeWidth={2.5} />
    </span>
  );
}

function GraphNodeCard({ id, data, selected }: NodeProps<FlowGraphNode>) {
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, data.bank, data.neighborhoodRoot, updateNodeInternals]);
  const state = graphEvidenceState(data);
  const hasOutcome = graphHasOutcome(data.kind);
  const stateColor = STATE_COLOR[state.tone];
  const tone = hasOutcome
    ? { border: stateColor, chip: stateColor }
    : (KIND_STYLE[data.kind] ?? {
        border: "var(--color-line-strong)",
        chip: "var(--color-muted)",
      });
  const Icon =
    data.kind === "ccf_family" && data.family_id
      ? controlFamily(data.family_id).icon
      : (KIND_ICON[data.kind] ?? Network);
  const connectorId = data.provider
    ? (SOURCE_CONNECTOR[data.provider] ?? data.provider)
    : undefined;
  const repositoryConnector =
    data.kind === "repository" &&
    ["github-security", "gitlab-security"].includes(connectorId ?? "")
      ? connectorId
      : undefined;
  const displayLabel = graphRecordLabel(data);
  const isEvidence = hasOutcome;
  // Safeguards share outcome wording with evidence; name the kind so the two
  // are not mistaken for each other.
  const outcomeLabel =
    data.kind === "safeguard" && !/safeguard/i.test(state.label)
      ? `${graphKindLabel(data.kind)} · ${state.label}`
      : state.label;
  const outcomeClass =
    state.tone === "critical"
      ? "text-danger-fg"
      : state.tone === "ready"
        ? "text-success-fg"
        : state.tone === "attention"
          ? "text-warning-fg"
          : undefined;
  const glyph = hasOutcome ? (
    <StatusGlyph
      tone={state.tone}
      compact={Boolean(data.compact || data.bank)}
    />
  ) : null;
  if (data.bank) {
    const inward = data.bank === "left" ? Position.Right : Position.Left;
    const handleStyle =
      data.bank === "left" ? { right: 8, top: 44 } : { left: 8, top: 44 };
    return (
      <Tooltip.Root delayDuration={120}>
        <Tooltip.Trigger asChild>
          <div
            className={`flex h-[88px] w-[224px] items-center gap-3 rounded-xl px-2 ${data.bank === "left" ? "flex-row-reverse text-right" : "text-left"} ${emphasisClass(data.emphasis)}`}
          >
            <Handle
              type="target"
              position={inward}
              style={handleStyle}
              className="!opacity-0"
            />
            <Handle
              type="source"
              position={inward}
              style={handleStyle}
              className="!opacity-0"
            />
            <div
              data-testid="graph-node-icon"
              className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-2"
              style={{
                borderColor: selected ? "var(--color-brand)" : tone.border,
                color: tone.border,
                background: `color-mix(in srgb, ${tone.border} 15%, var(--color-surface))`,
              }}
            >
              <Icon className="h-5 w-5" />
              {glyph}
            </div>
            <div className="min-w-0 flex-1">
              <div
                data-testid="graph-node-label"
                className="line-clamp-2 break-words text-xs font-semibold leading-4 text-ink"
              >
                {displayLabel}
              </div>
              <div className="mt-1 text-[10px] leading-3 text-muted">
                {data.relationshipLabel}
              </div>
              <div
                className={`mt-1 text-[11px] leading-4 ${(isEvidence && outcomeClass) || "text-muted"}`}
              >
                {isEvidence ? outcomeLabel : data.kind.replaceAll("_", " ")}
              </div>
            </div>
          </div>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            className="z-[80] max-w-xs rounded-lg border border-line bg-surface p-3 text-xs text-ink shadow-hero"
            side="top"
          >
            {data.label}
            <Tooltip.Arrow className="fill-surface" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    );
  }
  if (data.compact) {
    return (
      <Tooltip.Root delayDuration={120}>
        <Tooltip.Trigger asChild>
          <div
            className={`flex h-[92px] w-[220px] items-center gap-3 rounded-xl border bg-surface px-3 shadow-sm transition-colors ${selected ? "border-brand ring-2 ring-brand/25" : "border-line-strong"}`}
          >
            <Handle
              type="target"
              position={Position.Left}
              className="!opacity-0"
            />
            <Handle
              type="source"
              position={Position.Right}
              className="!opacity-0"
            />
            <Handle
              id="assurance"
              type="target"
              position={Position.Top}
              className="!opacity-0"
            />
            <div
              data-testid="graph-node-icon"
              className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border"
              style={{
                color: tone.border,
                borderColor: `color-mix(in srgb, ${tone.border} 45%, transparent)`,
                background: `color-mix(in srgb, ${tone.border} 10%, var(--color-surface))`,
              }}
            >
              {data.kind === "framework" && data.framework_id ? (
                <FrameworkBadge
                  frameworkId={data.framework_id}
                  variant="mark-only"
                  size={28}
                />
              ) : repositoryConnector ||
                (data.kind === "source" && connectorId) ? (
                <>
                  <ConnectorMark
                    connectorId={repositoryConnector ?? connectorId!}
                    size="sm"
                  />
                  {repositoryConnector && (
                    <span
                      className="absolute -bottom-1 -right-1 rounded border border-line bg-surface p-0.5"
                      aria-hidden="true"
                    >
                      <GitBranch className="h-3 w-3" />
                    </span>
                  )}
                </>
              ) : (
                <Icon className="h-5 w-5" />
              )}
              {glyph}
            </div>
            <div className="min-w-0 flex-1">
              <div
                data-testid="graph-node-label"
                className="line-clamp-2 break-words text-base font-semibold leading-5 text-ink"
              >
                {displayLabel}
              </div>
              <div
                className={`mt-1 text-sm leading-4 ${(isEvidence && outcomeClass) || "text-muted"}`}
              >
                {isEvidence
                  ? outcomeLabel
                  : data.kind === "finding"
                    ? [statusLabel(data.severity), statusLabel(data.status)]
                        .filter(Boolean)
                        .join(" · ") || "Finding"
                    : data.kind.replaceAll("_", " ")}
              </div>
            </div>
          </div>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            className="z-[80] max-w-xs rounded-lg border border-line bg-surface p-3 text-xs text-ink shadow-hero"
            side="top"
          >
            <p className="font-semibold">{data.label}</p>
            {data.subtitle && (
              <p className="mt-1 text-muted">{data.subtitle}</p>
            )}
            <Tooltip.Arrow className="fill-surface" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    );
  }
  return (
    <Tooltip.Root delayDuration={120}>
      <Tooltip.Trigger asChild>
        <div
          className={`flex h-[152px] w-[176px] flex-col items-center rounded-xl px-2 py-2 text-center transition-opacity duration-150 motion-reduce:transition-none ${emphasisClass(data.emphasis)}`}
        >
          <Handle
            type="target"
            style={data.layout === "LR" ? { left: 51, top: 48 } : undefined}
            position={
              data.layout === "LR"
                ? Position.Left
                : data.layout === "BT"
                  ? Position.Bottom
                  : Position.Top
            }
            className="!opacity-0"
          />
          <Handle
            type="source"
            style={data.layout === "LR" ? { right: 51, top: 48 } : undefined}
            position={
              data.layout === "LR"
                ? Position.Right
                : data.layout === "BT"
                  ? Position.Top
                  : Position.Bottom
            }
            className="!opacity-0"
          />
          {data.neighborhoodRoot && (
            <>
              <Handle
                id="right"
                type="target"
                position={Position.Right}
                style={{ right: 51, top: 48 }}
                className="!opacity-0"
              />
              <Handle
                id="left"
                type="source"
                position={Position.Left}
                style={{ left: 51, top: 48 }}
                className="!opacity-0"
              />
            </>
          )}
          <div
            data-testid="graph-node-icon"
            className="relative flex h-20 w-20 shrink-0 items-center justify-center rounded-full border-2 shadow-sm"
            style={{
              borderColor: selected ? "var(--color-brand)" : tone.border,
              borderWidth: selected ? 3 : 2,
              background: `color-mix(in srgb, ${tone.border} 15%, var(--color-surface))`,
              color: tone.border,
            }}
          >
            {data.kind === "framework" && data.framework_id ? (
              <FrameworkBadge
                frameworkId={data.framework_id}
                fallbackLabel={data.label}
                variant="mark-only"
                size={48}
              />
            ) : repositoryConnector ||
              (data.kind === "source" && connectorId) ? (
              <>
                <ConnectorMark
                  connectorId={repositoryConnector ?? connectorId!}
                  name={data.label}
                  size="lg"
                  className="[&>span]:border-0 [&>span]:bg-transparent [&>span]:shadow-none"
                />
                {repositoryConnector && (
                  <span
                    className="absolute -bottom-1 -right-1 grid h-6 w-6 place-items-center rounded-full border border-line bg-surface"
                    aria-hidden="true"
                  >
                    <GitBranch className="h-3.5 w-3.5" />
                  </span>
                )}
              </>
            ) : (
              <Icon className="h-9 w-9" />
            )}
            {glyph}
          </div>
          <div
            data-testid="graph-node-label"
            className="mt-2 line-clamp-2 w-full shrink-0 break-words text-sm font-semibold leading-4 text-ink"
          >
            {displayLabel}
          </div>
          <div className="mt-1 shrink-0 text-[11px] leading-3 text-muted">
            {isEvidence ? (
              <span className={outcomeClass}>{outcomeLabel}</span>
            ) : data.kind === "finding" ? (
              [statusLabel(data.severity), statusLabel(data.status)]
                .filter(Boolean)
                .join(" · ") || "Finding"
            ) : (
              data.kind.replaceAll("_", " ")
            )}
          </div>
        </div>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          sideOffset={8}
          className="z-[80] max-w-[280px] rounded-lg border border-line bg-surface p-3 text-xs text-ink shadow-hero"
        >
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            {data.kind.replace("_", " ")}
          </div>
          <div className="mt-1 font-semibold">{data.label}</div>
          {data.subtitle && (
            <div className="mt-0.5 text-muted">{data.subtitle}</div>
          )}
          <div className="mt-2 grid gap-0.5 text-[11px]">
            {data.framework_id && (
              <div>
                framework: <code className="text-ink">{data.framework_id}</code>
              </div>
            )}
            {data.owner && (
              <div>
                owner: <b className="text-ink">{data.owner}</b>
              </div>
            )}
            {data.risk_score !== undefined && (
              <div>
                risk: <b className="text-ink">{data.risk_score}</b>
              </div>
            )}
          </div>
          <Tooltip.Arrow className="fill-surface" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

const nodeTypes: NodeTypes = { "trustops-graph": GraphNodeCard };

export type LayoutDir = "LR" | "TB" | "BT";

function layoutGraph(
  rfNodes: FlowGraphNode[],
  rfEdges: Edge[],
  rankdir: LayoutDir,
  rankLimit?: number,
  neighborhoodRoot?: string,
): { nodes: FlowGraphNode[]; edges: Edge[] } {
  if (neighborhoodRoot) {
    // Direction determines the lane. Sorting only orders records within a
    // lane; it must never imply a parent/child or upstream/downstream link.
    const incomingIds = new Set(
      rfEdges
        .filter((edge) => edge.target === neighborhoodRoot)
        .map((edge) => edge.source),
    );
    const leaves = rfNodes
      .filter((node) => node.id !== neighborhoodRoot)
      .sort(
        (a, b) =>
          a.data.label.localeCompare(b.data.label) || a.id.localeCompare(b.id),
      );
    const incoming = leaves.filter((node) => incomingIds.has(node.id));
    const outgoing = leaves.filter((node) => !incomingIds.has(node.id));
    const rows = Math.max(incoming.length, outgoing.length, 1);
    const banks = new Map<string, "left" | "right">();
    const positions = new Map<string, { x: number; y: number }>();
    for (const [bank, lane] of [
      ["left", incoming],
      ["right", outgoing],
    ] as const) {
      lane.forEach((node, index) => {
        banks.set(node.id, bank);
        positions.set(node.id, {
          x: bank === "left" ? 0 : 704,
          y: (index + (rows - lane.length) / 2) * 112,
        });
      });
    }
    const nodes = rfNodes.map((node) =>
      node.id === neighborhoodRoot
        ? {
            ...node,
            position: { x: 376, y: (rows - 1) * 56 - 4 },
            data: { ...node.data, neighborhoodRoot: true },
          }
        : {
            ...node,
            width: 224,
            height: 88,
            position: positions.get(node.id)!,
            data: {
              ...node.data,
              bank: banks.get(node.id),
              relationshipLabel: [
                ...new Set(
                  rfEdges
                    .filter(
                      (edge) =>
                        edge.source === node.id || edge.target === node.id,
                    )
                    .map((edge) =>
                      String(edge.data?.relationshipKind ?? "").replaceAll(
                        "_",
                        " ",
                      ),
                    ),
                ),
              ].join(" · "),
            },
          },
    );
    const edges = rfEdges.map((edge) => ({
      ...edge,
      sourceHandle:
        edge.source === neighborhoodRoot && banks.get(edge.target) === "left"
          ? "left"
          : undefined,
      targetHandle:
        edge.target === neighborhoodRoot && banks.get(edge.source) === "right"
          ? "right"
          : undefined,
    }));
    return { nodes, edges };
  }
  const compact = rfNodes[0]?.data.compact;
  if (compact && rankdir === "LR") {
    const positions = investigationPositions(
      rfNodes.map((n) => ({
        id: n.id,
        kind: n.data.kind,
        label: n.data.label,
      })),
      rfEdges,
    );
    const kinds = new Map(rfNodes.map((n) => [n.id, n.data.kind]));
    return {
      nodes: rfNodes.map((n) => ({
        ...n,
        width: 220,
        height: 92,
        position: positions.get(n.id)!,
      })),
      edges: rfEdges.map((e) => ({
        ...e,
        type: "investigation",
        targetHandle:
          graphAssuranceKind(kinds.get(e.source)!) &&
          !graphAssuranceKind(kinds.get(e.target)!)
            ? "assurance"
            : undefined,
      })),
    };
  }
  const width = compact ? 220 : NODE_W;
  const height = compact ? 92 : NODE_H;
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir,
    nodesep: compact ? 16 : 32,
    ranksep: compact ? 64 : rankdir === "LR" ? 140 : 58,
    marginx: 8,
    marginy: 8,
  });

  rfNodes.forEach((node) => g.setNode(node.id, { width, height }));
  rfEdges.forEach((edge) => g.setEdge(edge.source, edge.target));
  dagre.layout(g);

  const positions = new Map(
    rfNodes.map((node) => {
      const pos = g.node(node.id);
      return [node.id, { x: pos.x - width / 2, y: pos.y - height / 2 }];
    }),
  );
  wrapWideRanks(positions, rankdir, rankLimit, width, height, compact ? 8 : 6);
  const laidOut = rfNodes.map((node) => ({
    ...node,
    width,
    height,
    position: positions.get(node.id) ?? { x: 0, y: 0 },
  }));
  return { nodes: laidOut, edges: rfEdges };
}

function InvestigationEdge(props: EdgeProps) {
  const points = props.data?.points as { x: number; y: number }[] | undefined;
  const path = points?.length
    ? points.map((p, i) => `${i ? "L" : "M"} ${p.x} ${p.y}`).join(" ")
    : getSmoothStepPath(props)[0];
  const middle = points?.[Math.floor(points.length / 2)];
  return (
    <BaseEdge
      id={props.id}
      path={path}
      markerEnd={props.markerEnd}
      style={props.style}
      label={props.label}
      labelX={middle?.x}
      labelY={middle?.y}
      labelStyle={props.labelStyle}
      labelBgStyle={props.labelBgStyle}
    />
  );
}
const investigationEdgeTypes = { investigation: InvestigationEdge };

const NODE_W = 176;
const NODE_H = 152;

/**
 * Dagre puts every node of a rank on one line, so a framework with dozens of
 * controls becomes a strip that only fits at minimum zoom. Wrap any rank wider
 * than a sqrt-scaled limit into rows, keeping dagre's within-rank order.
 */
function wrapWideRanks(
  positions: Map<string, { x: number; y: number }>,
  rankdir: LayoutDir,
  rankLimit?: number,
  width = NODE_W,
  height = NODE_H,
  rankFloor = 6,
) {
  const horizontal = rankdir === "LR";
  const limit = Math.min(
    rankLimit ?? 16,
    Math.max(
      Math.min(rankFloor, rankLimit ?? rankFloor),
      Math.round(Math.sqrt(positions.size) * 1.2),
    ),
  );
  const ranks = new Map<number, string[]>();
  positions.forEach((pos, id) => {
    const key = Math.round(horizontal ? pos.x : pos.y);
    ranks.set(key, [...(ranks.get(key) ?? []), id]);
  });
  if (![...ranks.values()].some((ids) => ids.length > limit)) return;

  const crossStep = (horizontal ? height : width) + 10;
  const rowStep = (horizontal ? width : height) + 14;
  const rankGap = 40;
  const ordered = [...ranks.entries()].sort((a, b) => a[0] - b[0]);
  if (rankdir === "BT") ordered.reverse();
  let cursor = 0;
  for (const [, ids] of ordered) {
    ids.sort((a, b) => {
      const pa = positions.get(a)!;
      const pb = positions.get(b)!;
      return horizontal ? pa.y - pb.y : pa.x - pb.x;
    });
    for (let start = 0; start < ids.length; start += limit) {
      const row = ids.slice(start, start + limit);
      row.forEach((id, i) => {
        const cross = (i - (row.length - 1) / 2) * crossStep;
        const along = rankdir === "BT" ? -cursor : cursor;
        positions.set(
          id,
          horizontal ? { x: along, y: cross } : { x: cross, y: along },
        );
      });
      cursor += rowStep;
    }
    cursor += rankGap;
  }
}

interface Props {
  graph: ComplianceGraph | undefined;
  visibleKinds: Set<GraphNodeKind>;
  layout: LayoutDir;
  filterOwner: string;
  filterEnvironment: string;
  filterFramework: string;
  filterControl: string;
  filterWorkflow: string;
  filterStaleOnly: boolean;
  searchQuery: string;
  focusId?: string | null;
  /** Restrict the canvas to these node ids (a focused control path). */
  scopeIds?: Set<string> | null;
  /** Most nodes per row before a rank wraps; narrow canvases pass fewer. */
  rankLimit?: number;
  neighborhoodRoot?: string;
  showEdgeLabels?: boolean;
  showRelationshipLabels?: boolean;
  compactCards?: boolean;
  heightClassName?: string;
  pathFrom: string | null;
  pathTo: string | null;
  onSelectNode: (node: GraphNode | null) => void;
  onExploreNode?: (node: GraphNode) => void;
  /** Offered when the filtered graph is too large to lay out. */
  oversizeAction?: React.ReactNode;
}

interface ImperativeRef {
  toJSON: () => unknown;
  toSVG: () => string | null;
}

export function GraphCanvas(
  props: Props & { canvasRef?: React.MutableRefObject<ImperativeRef | null> },
) {
  return (
    <ReactFlowProvider>
      <Tooltip.Provider>
        <InnerGraphCanvas {...props} />
      </Tooltip.Provider>
    </ReactFlowProvider>
  );
}

function InnerGraphCanvas({
  graph,
  visibleKinds,
  layout,
  filterOwner,
  filterEnvironment,
  filterFramework,
  filterControl,
  filterWorkflow,
  filterStaleOnly,
  searchQuery,
  focusId = null,
  scopeIds = null,
  rankLimit,
  neighborhoodRoot,
  showEdgeLabels = true,
  showRelationshipLabels = false,
  compactCards = false,
  heightClassName = "h-[clamp(400px,calc(100dvh-300px),650px)] min-h-[400px]",
  pathFrom,
  pathTo,
  onSelectNode,
  onExploreNode,
  oversizeAction,
  canvasRef,
}: Props & { canvasRef?: React.MutableRefObject<ImperativeRef | null> }) {
  const { resolved: resolvedTheme } = useTheme();
  const [hydrated, setHydrated] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  useEffect(() => setHydrated(true), []);
  const { setCenter, setViewport } = useReactFlow();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const activeId = hoveredId ?? selectedId;
  const [dragged, setDragged] = useState<{
    key: string;
    positions: Record<string, { x: number; y: number }>;
  }>({ key: "", positions: {} });
  const pendingClick = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (pendingClick.current) clearTimeout(pendingClick.current);
    },
    [],
  );
  useEffect(() => {
    setSelectedId(focusId);
  }, [focusId]);

  const frameworkScopeIds = useMemo(() => {
    if (!graph || !filterFramework) return null;
    const ids = new Set<string>();
    for (const node of graph.nodes) {
      if (
        (node.kind === "framework" && node.framework_id === filterFramework) ||
        (node.kind === "control" && node.framework_id === filterFramework)
      ) {
        ids.add(node.id);
      }
    }
    return graphScope(graph.edges, ids, 2, true);
  }, [graph, filterFramework]);

  const expandScope = useCallback(
    (seed: Set<string>, hops: number) => {
      if (!graph) return seed;
      return graphScope(graph.edges, seed, hops);
    },
    [graph],
  );

  const controlScopeIds = useMemo(() => {
    if (!graph || !filterControl) return null;
    const seed = new Set<string>();
    for (const node of graph.nodes) {
      if (node.kind === "control" && node.label === filterControl)
        seed.add(node.id);
      if (node.control_ids?.includes(filterControl)) seed.add(node.id);
    }
    return expandScope(seed, 3);
  }, [graph, filterControl, expandScope]);

  const workflowScopeIds = useMemo(() => {
    if (!graph || !filterWorkflow) return null;
    const seed = new Set<string>();
    for (const node of graph.nodes) {
      const isWorkflow =
        node.kind === "workflow" ||
        (node.kind === "evidence_signal" &&
          (node.label.includes("workflow") ||
            node.event_type?.includes("ci_workflow")));
      if (isWorkflow && node.label === filterWorkflow) seed.add(node.id);
    }
    return expandScope(seed, 2);
  }, [graph, filterWorkflow, expandScope]);

  const staleScopeIds = useMemo(() => {
    if (!graph || !filterStaleOnly) return null;
    const seed = new Set<string>();
    for (const node of graph.nodes) {
      if (
        node.kind === "signal_gap" ||
        (node.freshness_status && STALE_FRESHNESS.has(node.freshness_status))
      ) {
        seed.add(node.id);
      }
    }
    return expandScope(seed, 2);
  }, [graph, filterStaleOnly, expandScope]);

  // Apply layer + facet filters in one place so the canvas + path-trace + search agree.
  const filteredNodes = useMemo(() => {
    if (!graph) return [];
    return graph.nodes.filter((n) => {
      if (!visibleKinds.has(n.kind)) return false;
      if (filterOwner && (n.owner ?? "") !== filterOwner) return false;
      if (filterEnvironment && (n.environment ?? "") !== filterEnvironment)
        return false;
      if (frameworkScopeIds && !frameworkScopeIds.has(n.id)) return false;
      if (controlScopeIds && !controlScopeIds.has(n.id)) return false;
      if (workflowScopeIds && !workflowScopeIds.has(n.id)) return false;
      if (staleScopeIds && !staleScopeIds.has(n.id)) return false;
      if (scopeIds && !scopeIds.has(n.id)) return false;
      return true;
    });
  }, [
    graph,
    visibleKinds,
    filterOwner,
    filterEnvironment,
    frameworkScopeIds,
    controlScopeIds,
    workflowScopeIds,
    staleScopeIds,
    scopeIds,
  ]);

  const allowedIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id)),
    [filteredNodes],
  );

  const filteredEdges = useMemo(
    () =>
      graph?.edges.filter(
        (edge) => allowedIds.has(edge.source) && allowedIds.has(edge.target),
      ) ?? [],
    [graph, allowedIds],
  );
  const relationshipStyles = useMemo(() => {
    const styles = new Map<string, { dash?: string; invalid?: boolean }>();
    for (const edge of filteredEdges) {
      const review = graphMappingReview(edge);
      if (graphEdgeInvalid(edge))
        styles.set("Invalid binding", { dash: "3 4", invalid: true });
      else if (review)
        styles.set(review.reviewed ? "Reviewed mapping" : review.label, {
          dash: review.reviewed ? "8 4" : "2 4",
        });
      else styles.set("Recorded link", {});
    }
    return [...styles];
  }, [filteredEdges]);

  // Compute neighbor sets for the currently selected node so the canvas can
  // bright-highlight it + its 1-hop neighbors and dim the rest.
  const adjacency = useMemo(() => {
    const out = new Map<string, Set<string>>();
    if (!graph) return out;
    for (const e of graph.edges) {
      if (!allowedIds.has(e.source) || !allowedIds.has(e.target)) continue;
      if (!out.has(e.source)) out.set(e.source, new Set());
      if (!out.has(e.target)) out.set(e.target, new Set());
      out.get(e.source)!.add(e.target);
      out.get(e.target)!.add(e.source);
    }
    return out;
  }, [graph, allowedIds]);

  const highlightSet = useMemo<Set<string> | null>(() => {
    if (!activeId || !allowedIds.has(activeId)) return null;
    const out = new Set<string>([activeId]);
    for (const n of adjacency.get(activeId) ?? []) out.add(n);
    return out;
  }, [activeId, adjacency, allowedIds]);

  // Two-click path trace via BFS over the filtered subgraph.
  const pathSet = useMemo<{
    nodes: Set<string>;
    edges: Set<string>;
  } | null>(() => {
    if (!graph || !pathFrom || !pathTo || pathFrom === pathTo) return null;
    if (!allowedIds.has(pathFrom) || !allowedIds.has(pathTo)) return null;
    const visited = new Map<string, string | null>([[pathFrom, null]]);
    const queue: string[] = [pathFrom];
    while (queue.length > 0) {
      const cur = queue.shift()!;
      if (cur === pathTo) break;
      for (const next of adjacency.get(cur) ?? []) {
        if (visited.has(next)) continue;
        visited.set(next, cur);
        queue.push(next);
      }
    }
    if (!visited.has(pathTo)) return null;
    const nodes = new Set<string>();
    let step: string | null = pathTo;
    while (step) {
      nodes.add(step);
      step = visited.get(step) ?? null;
    }
    const edges = new Set<string>();
    for (const e of graph.edges) {
      if (nodes.has(e.source) && nodes.has(e.target)) edges.add(e.id);
    }
    return { nodes, edges };
  }, [graph, pathFrom, pathTo, allowedIds, adjacency]);

  // Search highlight: case-insensitive match against label / subtitle / id.
  const matchSet = useMemo<Set<string> | null>(() => {
    if (!searchQuery.trim()) return null;
    const lower = searchQuery.trim().toLowerCase();
    const out = new Set<string>();
    for (const n of filteredNodes) {
      const hay =
        `${n.label} ${n.subtitle ?? ""} ${n.id} ${n.owner ?? ""}`.toLowerCase();
      if (hay.includes(lower)) out.add(n.id);
    }
    return out;
  }, [searchQuery, filteredNodes]);

  const budget = graphLayoutBudget(filteredNodes.length, filteredEdges.length);
  const tooLarge = !budget.draw;

  // Layout depends only on the node set and direction; hover, selection and
  // search restyle the laid-out graph without re-running dagre.
  const laidOut = useMemo(() => {
    if (!graph || tooLarge)
      return { nodes: [] as FlowGraphNode[], edges: [] as Edge[] };
    const list: FlowGraphNode[] = filteredNodes.map((n) => ({
      id: n.id,
      type: "trustops-graph",
      position: { x: 0, y: 0 },
      ariaLabel: graphNodeAriaLabel(n),
      data: {
        label: n.label,
        subtitle: n.subtitle ?? "",
        kind: n.kind,
        compact: compactCards && layout === "LR" && !neighborhoodRoot,
        layout,
        provider: n.provider,
        status: n.status,
        freshness_status: n.freshness_status,
        ccf_status: n.ccf_status,
        severity: n.severity,
        framework_id: n.framework_id,
        family_id:
          n.kind === "ccf_family" ? n.id.replace(/^family:/, "") : undefined,
        owner: n.owner,
        risk_score: n.risk_score,
        emphasis: "active",
      },
    }));
    const edges: Edge[] = filteredEdges.map((e) => {
      const invalid = graphEdgeInvalid(e);
      const kind = e.kind.replaceAll("_", " ");
      const review = graphMappingReview(e)?.label;
      return {
        id: e.id,
        data: {
          relationshipKind: e.kind,
          reviewState: e.review_state,
          mapping: Boolean(graphMappingReview(e)),
          invalid,
        },
        className: invalid ? "graph-edge-invalid" : undefined,
        source: e.source,
        target: e.target,
        label: invalid
          ? "invalid asset type"
          : showEdgeLabels
            ? (review ?? (showRelationshipLabels ? kind : undefined))
            : undefined,
        ariaLabel: invalid
          ? `${kind}: invalid asset type, does not support this asset`
          : `${kind}${review ? `: ${review}` : ""}`,
        labelStyle: {
          fill: invalid ? "var(--color-danger-fg)" : "var(--color-ink)",
          fontSize: 11,
        },
        labelBgStyle: { fill: "var(--color-surface)" },
      };
    });
    return layoutGraph(list, edges, layout, rankLimit, neighborhoodRoot);
  }, [
    compactCards,
    neighborhoodRoot,
    rankLimit,
    showEdgeLabels,
    showRelationshipLabels,
    graph,
    tooLarge,
    filteredNodes,
    filteredEdges,
    layout,
  ]);

  const { nodes: rfNodes, edges: rfEdges } = useMemo(() => {
    const nodes: FlowGraphNode[] = laidOut.nodes.map((n) => {
      let emphasis: GraphNodeData["emphasis"] = "active";
      if (matchSet) emphasis = matchSet.has(n.id) ? "match" : "dimmed";
      else if (pathSet) emphasis = pathSet.nodes.has(n.id) ? "path" : "dimmed";
      else if (highlightSet)
        emphasis = highlightSet.has(n.id) ? "highlight" : "dimmed";
      return {
        ...n,
        className: n.id === focusId ? "focused" : undefined,
        selected: n.id === selectedId,
        data: { ...n.data, emphasis },
      };
    });
    const edges: Edge[] = laidOut.edges.map((e) => {
      const invalid = Boolean(e.data?.invalid);
      const reviewState = e.data?.reviewState as string | undefined;
      const reviewed = ["maintainer_reviewed", "org_reviewed"].includes(
        reviewState ?? "",
      );
      const onPath = pathSet?.edges.has(e.id) ?? false;
      const onHighlight = highlightSet
        ? e.source === activeId || e.target === activeId
        : !compactCards && Boolean(scopeIds);
      const dimmed =
        (matchSet && !matchSet.has(e.source) && !matchSet.has(e.target)) ||
        (pathSet && !onPath) ||
        (highlightSet && !onHighlight);
      const accent = invalid
        ? "var(--color-danger)"
        : onPath
          ? "var(--color-warning)"
          : undefined;
      return {
        ...e,
        animated: onPath,
        zIndex: onHighlight || onPath ? 2 : 0,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 16,
          height: 16,
          color: accent ?? "var(--color-ink)",
        },
        style: {
          stroke:
            accent ??
            (onHighlight
              ? "var(--color-ink)"
              : compactCards
                ? "var(--color-muted)"
                : "var(--color-line-strong)"),
          strokeWidth:
            onPath || invalid || (onHighlight && activeId) ? 2.5 : 1.5,
          // Invalid bindings: short red dashes. Catalog mappings: dashed when
          // reviewed, dotted while proposed. Evidence links stay solid.
          strokeDasharray: invalid
            ? "3 4"
            : e.data?.mapping
              ? reviewed
                ? "8 4"
                : "2 4"
              : undefined,
          opacity: dimmed && !onPath && !onHighlight && !invalid ? 0.4 : 1,
        },
      };
    });
    return { nodes, edges };
  }, [
    laidOut,
    compactCards,
    matchSet,
    pathSet,
    highlightSet,
    activeId,
    selectedId,
    focusId,
    scopeIds,
  ]);

  // Keep manual placement through hover and selection, but reset it when the
  // node set or automatic layout changes (including framework/page changes).
  const placementKey = rfNodes
    .map((n) => `${n.id}:${n.position.x}:${n.position.y}`)
    .join("|");
  const placedNodes =
    dragged.key === placementKey
      ? rfNodes.map((n) =>
          dragged.positions[n.id]
            ? { ...n, position: dragged.positions[n.id] }
            : n,
        )
      : rfNodes;

  const routes = useMemo(() => {
    const nodes = laidOut.nodes.map((n) => ({
      ...n,
      position:
        dragged.key === placementKey
          ? (dragged.positions[n.id] ?? n.position)
          : n.position,
    }));
    const boxes = nodes.map((n) => ({
      ...n.position,
      width: n.width ?? NODE_W,
      height: n.height ?? NODE_H,
    }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    return new Map(
      laidOut.edges
        .filter((e) => e.type === "investigation")
        .map((edge, index) => {
          const source = byId.get(edge.source)!;
          const target = byId.get(edge.target)!;
          return [
            edge.id,
            investigationRoute(
              { x: source.position.x + 220, y: source.position.y + 46 },
              edge.targetHandle === "assurance"
                ? { x: target.position.x + 110, y: target.position.y }
                : { x: target.position.x, y: target.position.y + 46 },
              boxes,
              (index % 6) * 3,
              edge.targetHandle === "assurance" ? "top" : "left",
            ),
          ];
        }),
    );
  }, [laidOut.nodes, laidOut.edges, dragged, placementKey]);
  const routedEdges = rfEdges.map((edge) =>
    edge.type === "investigation"
      ? { ...edge, data: { ...edge.data, points: routes.get(edge.id) } }
      : edge,
  );

  const focusNode = focusId ? rfNodes.find((n) => n.id === focusId) : null;
  const focusX = focusNode ? focusNode.position.x : null;
  const focusY = focusNode ? focusNode.position.y : null;

  const mobileAnchor =
    focusNode ??
    rfNodes.find((node) => node.data.kind === "control") ??
    rfNodes[0];
  const mobileX = mobileAnchor
    ? mobileAnchor.position.x + (mobileAnchor.width ?? NODE_W) / 2
    : null;
  const mobileY = mobileAnchor
    ? mobileAnchor.position.y + (mobileAnchor.height ?? NODE_H) / 2
    : null;
  const [overflow, setOverflow] = useState(false);
  const laidOutNodes = laidOut.nodes;
  const overflowsAt = useCallback(
    (zoom: number) => {
      const wrapper = wrapperRef.current;
      if (!wrapper || laidOutNodes.length === 0) return false;
      const bounds = getNodesBounds(laidOutNodes);
      return (
        bounds.width * zoom > wrapper.clientWidth + 1 ||
        bounds.height * zoom > wrapper.clientHeight + 1
      );
    },
    [laidOutNodes],
  );
  const fitReadableView = useCallback(
    (duration = 0) => {
      const wrapper = wrapperRef.current;
      const width = wrapper?.clientWidth ?? 0;
      const height = wrapper?.clientHeight ?? 0;
      if (!width || !height || laidOutNodes.length === 0) return;
      if (
        compactCards &&
        !neighborhoodRoot &&
        width < 600 &&
        mobileX !== null &&
        mobileY !== null
      ) {
        setCenter(mobileX, mobileY, { zoom: 0.85, duration });
        setOverflow(overflowsAt(0.85));
        return;
      }
      const bounds = getNodesBounds(laidOutNodes);
      const fit = getViewportForBounds(bounds, width, height, 0.16, 1, 0.06);
      const readableZoom = compactCards ? 0.7 : GRAPH_READABLE_ZOOM;
      if (neighborhoodRoot || fit.zoom >= readableZoom) {
        setViewport(fit, { duration });
        setOverflow(false);
        return;
      }
      // Fitting everything would shrink labels below reading size. Hold a
      // readable zoom and start from the focus, or from where the layout
      // begins, and say that more of the map is outside the view.
      const zoom = readableZoom;
      const margin = 16 / zoom;
      const anchor =
        focusNode ??
        (compactCards
          ? rfNodes.find((node) => node.data.kind === "control")
          : undefined);
      let x = bounds.x + bounds.width / 2;
      let y = bounds.y + bounds.height / 2;
      if (anchor) {
        x = anchor.position.x + (anchor.width ?? NODE_W) / 2;
        y = anchor.position.y + (anchor.height ?? NODE_H) / 2;
        if (compactCards)
          y = Math.max(y, bounds.y + height / 2 / zoom - margin);
      } else if (layout === "LR") {
        x = bounds.x + width / 2 / zoom - margin;
      } else if (layout === "TB") {
        y = bounds.y + height / 2 / zoom - margin;
      } else {
        y = bounds.y + bounds.height - height / 2 / zoom + margin;
      }
      setCenter(x, y, { zoom, duration });
      setOverflow(true);
    },
    [
      compactCards,
      neighborhoodRoot,
      mobileX,
      mobileY,
      setCenter,
      setViewport,
      laidOutNodes,
      overflowsAt,
      focusNode,
      rfNodes,
      layout,
    ],
  );

  useEffect(() => {
    if (rfNodes.length === 0) return;
    const frame = window.requestAnimationFrame(() => {
      // A scoped path is small enough to fit whole at a readable zoom.
      if (focusX !== null && focusY !== null && !scopeIds) {
        setCenter(focusX + 73, focusY + 29, { zoom: 0.9, duration: 300 });
        setOverflow(overflowsAt(0.9));
      } else {
        fitReadableView(180);
      }
    });
    return () => window.cancelAnimationFrame(frame);
    // Restyling on hover must not refit; only node-set and filter changes do.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    laidOutNodes,
    setCenter,
    focusX,
    focusY,
    rfNodes.length,
    layout,
    filterOwner,
    filterEnvironment,
    filterFramework,
    searchQuery,
    scopeIds,
  ]);

  // Opening the adjacent inspector changes canvas width without changing nodes.
  const fitRef = useRef(fitReadableView);
  useEffect(() => {
    fitRef.current = fitReadableView;
  }, [fitReadableView]);
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => fitRef.current());
    });
    observer.observe(wrapper);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [scopeIds, hydrated, tooLarge]);

  // When the search has exactly one match, recentre the viewport on it so the
  // user sees the result immediately.
  useEffect(() => {
    if (!matchSet || matchSet.size !== 1) return;
    const match = laidOutNodes.find((n) => matchSet.has(n.id));
    if (!match) return;
    setCenter(match.position.x + 73, match.position.y + 29, {
      zoom: 0.9,
      duration: 300,
    });
  }, [matchSet, laidOutNodes, setCenter]);

  // Expose imperative export helpers to the parent (Export menu).
  useEffect(() => {
    if (!canvasRef) return;
    canvasRef.current = {
      toJSON: () => graph ?? null,
      toSVG: () => {
        const root = wrapperRef.current;
        if (!root) return null;
        const svg = root.querySelector(
          "svg.react-flow__edges",
        ) as SVGSVGElement | null;
        if (!svg) return null;
        const clone = svg.cloneNode(true) as SVGSVGElement;
        clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
        // A standalone SVG cannot resolve theme tokens; inline their values.
        const styles = getComputedStyle(root);
        return new XMLSerializer()
          .serializeToString(clone)
          .replace(
            /var\((--color-[a-z0-9-]+)\)/g,
            (match, name: string) =>
              styles.getPropertyValue(name).trim() || match,
          );
      },
    };
  }, [graph, canvasRef]);

  if (!hydrated) {
    return (
      <div
        className={`${heightClassName} rounded-xl border border-line bg-surface`}
      />
    );
  }

  if (tooLarge) {
    return (
      <div
        ref={wrapperRef}
        role="status"
        data-testid="graph-too-large"
        className={`${heightClassName} grid place-items-center rounded-xl border border-dashed border-line bg-surfaceMuted p-6 text-center`}
      >
        <div className="grid max-w-md justify-items-center gap-3 text-sm text-muted">
          <Network aria-hidden="true" className="h-8 w-8" />
          <p>
            <b className="text-ink">
              {formatCount(filteredNodes.length)} nodes and{" "}
              {formatCount(filteredEdges.length)} relationships exceed the
              readable layout budget.
            </b>{" "}
            Maps draw up to {formatCount(GRAPH_LAYOUT_NODE_CAP)} nodes and{" "}
            {formatCount(GRAPH_LAYOUT_EDGE_CAP)} relationships. Choose one
            framework or focus a control path, or use Evidence investigation to
            follow a specific record.
          </p>
          {oversizeAction}
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-1">
      <div
        ref={wrapperRef}
        className={`${heightClassName} overflow-hidden rounded-xl border border-line bg-surface`}
      >
        <ReactFlow
          onlyRenderVisibleElements={budget.virtualize}
          edgesFocusable={false}
          colorMode={resolvedTheme}
          nodes={placedNodes}
          onNodesChange={(changes) => {
            const moves = changes.filter(
              (change) => change.type === "position" && change.position,
            );
            if (!moves.length) return;
            setDragged((current) => {
              const positions =
                current.key === placementKey ? { ...current.positions } : {};
              for (const move of moves) {
                if (move.type !== "position" || !move.position) continue;
                const node = rfNodes.find((item) => item.id === move.id);
                if (!node) continue;
                const { x, y } = move.position;
                // Stop at another card rather than allowing labels to overlap.
                const blocked = rfNodes.some((other) => {
                  if (other.id === move.id) return false;
                  const at = positions[other.id] ?? other.position;
                  return (
                    x < at.x + (other.width ?? NODE_W) + 12 &&
                    x + (node.width ?? NODE_W) + 12 > at.x &&
                    y < at.y + (other.height ?? NODE_H) + 12 &&
                    y + (node.height ?? NODE_H) + 12 > at.y
                  );
                });
                if (!blocked) positions[move.id] = move.position;
              }
              return { key: placementKey, positions };
            });
          }}
          onNodeMouseEnter={(_, node) => setHoveredId(node.id)}
          onNodeMouseLeave={() => setHoveredId(null)}
          onNodeDragStart={() => {
            if (pendingClick.current) clearTimeout(pendingClick.current);
            setHoveredId(null);
          }}
          onNodeDragStop={(_, node) => setHoveredId(node.id)}
          onPaneClick={() => {
            setSelectedId(null);
            setHoveredId(null);
            onSelectNode(null);
          }}
          edges={routedEdges}
          edgeTypes={investigationEdgeTypes}
          nodeTypes={nodeTypes}
          nodesDraggable
          nodesConnectable={false}
          edgesReconnectable={false}
          fitView
          fitViewOptions={{ maxZoom: 1, padding: 0.06 }}
          minZoom={0.16}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
          onNodeClick={(_, node) => {
            if (pendingClick.current) clearTimeout(pendingClick.current);
            const select = () => {
              setSelectedId(node.id);
              onSelectNode(
                graph?.nodes.find((item) => item.id === node.id) ?? null,
              );
            };
            // Keep the node still until a possible double-click resolves; opening
            // the inspector immediately moves the second click off its target.
            if (onExploreNode) pendingClick.current = setTimeout(select, 250);
            else select();
          }}
          zoomOnScroll={false}
          preventScrolling={false}
          zoomOnDoubleClick={!onExploreNode}
          onNodeDoubleClick={(_, node) => {
            if (pendingClick.current) clearTimeout(pendingClick.current);
            const target = graph?.nodes.find((item) => item.id === node.id);
            if (target) onExploreNode?.(target);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            const nodeId = (event.target as HTMLElement).closest<HTMLElement>(
              ".react-flow__node",
            )?.dataset.id;
            if (!nodeId) return;
            event.preventDefault();
            const target = graph?.nodes.find((item) => item.id === nodeId);
            if (
              event.key === "Enter" &&
              event.shiftKey &&
              target &&
              onExploreNode
            ) {
              onExploreNode(target);
            } else {
              setSelectedId(nodeId);
              onSelectNode(target ?? null);
            }
          }}
        >
          <Background gap={20} color="var(--color-line)" />
          <MiniMap
            pannable
            zoomable
            className="!h-20 !w-28 !rounded-lg !border !border-line !bg-surface/90 !shadow-card max-md:!hidden"
            style={{ width: 112, height: 80 }}
            maskColor="rgb(var(--rgb-ink) / 0.06)"
          />
          <Controls position="bottom-left" showFitView={false}>
            <ControlButton
              title="Fit View"
              aria-label="Fit View"
              onClick={() => fitReadableView(180)}
            >
              <Scan />
            </ControlButton>
          </Controls>
        </ReactFlow>
      </div>
      <div
        aria-label="Relationship styles"
        className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-surfaceMuted px-3 py-2 text-xs text-muted"
      >
        {relationshipStyles.map(([label, style]) => (
          <span
            key={label}
            className={`inline-flex items-center gap-2 ${style.invalid ? "text-danger-fg" : ""}`}
          >
            <svg aria-hidden="true" width="28" height="10" viewBox="0 0 28 10">
              <path
                d="M0 5H24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeDasharray={style.dash}
              />
              <path
                d="m22 2 4 3-4 3"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
            </svg>
            {label}
          </span>
        ))}
      </div>
      {overflow && (
        <p
          data-testid="graph-overflow-hint"
          className="text-xs leading-5 text-muted"
        >
          Part of this map is outside the view. Drag the canvas to follow
          connections or use the minimap. Fit view (bottom left) restores a
          readable zoom; zoom out for an overview.
        </p>
      )}
    </div>
  );
}

export type { ImperativeRef };
