"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "@/components/theme/ThemeProvider";
import dagre from "@dagrejs/dagre";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Background,
  Handle,
  Position,
  MarkerType,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
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
  ClipboardCheck,
  Code2,
  FileCode2,
  FileText,
  FolderTree,
  GitBranch,
  LockKeyhole,
  Network,
  Package,
  Server,
  ShieldCheck,
  ShieldQuestion,
  UserRound,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { graphEvidenceState, graphRecordLabel } from "@/lib/graph-evidence";
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

interface GraphNodeData extends Record<string, unknown> {
  label: string;
  subtitle: string;
  status?: string;
  severity?: string;
  kind: GraphNodeKind;
  layout: LayoutDir;
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

function GraphNodeCard({ id, data, selected }: NodeProps<FlowGraphNode>) {
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, data.bank, data.neighborhoodRoot, updateNodeInternals]);
  const tone = KIND_STYLE[data.kind] ?? {
    border: "var(--color-line-strong)",
    chip: "var(--color-muted)",
  };
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
  const evidenceState = graphEvidenceState(data);
  const isEvidence = ["evidence", "evidence_type", "signal_gap"].includes(
    data.kind,
  );
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
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-2"
              style={{
                borderColor: selected ? "var(--color-brand)" : tone.border,
                color: tone.border,
                background: `color-mix(in srgb, ${tone.border} 15%, var(--color-surface))`,
              }}
            >
              <Icon className="h-5 w-5" />
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
              <div className="mt-1 text-[11px] leading-4 text-muted">
                {isEvidence
                  ? evidenceState.label
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
            {data.label}
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
          className={`flex h-[152px] w-[176px] flex-col items-center rounded-xl px-2 py-2 text-center transition-opacity ${emphasisClass(data.emphasis)}`}
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
          </div>
          <div
            data-testid="graph-node-label"
            className="mt-2 line-clamp-2 w-full shrink-0 break-words text-sm font-semibold leading-4 text-ink"
          >
            {displayLabel}
          </div>
          <div className="mt-1 shrink-0 text-[11px] leading-3 text-muted">
            {isEvidence ? (
              <span
                className={
                  evidenceState.tone === "critical"
                    ? "text-danger-fg"
                    : evidenceState.tone === "ready"
                      ? "text-success-fg"
                      : undefined
                }
              >
                {evidenceState.label}
              </span>
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
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir, nodesep: 30, ranksep: 58, marginx: 8, marginy: 8 });

  rfNodes.forEach((node) =>
    g.setNode(node.id, { width: NODE_W, height: NODE_H }),
  );
  rfEdges.forEach((edge) => g.setEdge(edge.source, edge.target));
  dagre.layout(g);

  const positions = new Map(
    rfNodes.map((node) => {
      const pos = g.node(node.id);
      return [node.id, { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 }];
    }),
  );
  wrapWideRanks(positions, rankdir, rankLimit);
  const laidOut = rfNodes.map((node) => ({
    ...node,
    position: positions.get(node.id) ?? { x: 0, y: 0 },
  }));
  return { nodes: laidOut, edges: rfEdges };
}

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
) {
  const horizontal = rankdir === "LR";
  const limit = Math.min(
    rankLimit ?? 16,
    Math.max(
      Math.min(6, rankLimit ?? 6),
      Math.round(Math.sqrt(positions.size) * 1.2),
    ),
  );
  const ranks = new Map<number, string[]>();
  positions.forEach((pos, id) => {
    const key = Math.round(horizontal ? pos.x : pos.y);
    ranks.set(key, [...(ranks.get(key) ?? []), id]);
  });
  if (![...ranks.values()].some((ids) => ids.length > limit)) return;

  const crossStep = (horizontal ? NODE_H : NODE_W) + 10;
  const rowStep = (horizontal ? NODE_W : NODE_H) + 14;
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
  heightClassName?: string;
  pathFrom: string | null;
  pathTo: string | null;
  onSelectNode: (node: GraphNode | null) => void;
  onExploreNode?: (node: GraphNode) => void;
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
  heightClassName = "h-[clamp(400px,calc(100dvh-300px),650px)] min-h-[400px]",
  pathFrom,
  pathTo,
  onSelectNode,
  onExploreNode,
  canvasRef,
}: Props & { canvasRef?: React.MutableRefObject<ImperativeRef | null> }) {
  const { resolved: resolvedTheme } = useTheme();
  const [hydrated, setHydrated] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  useEffect(() => setHydrated(true), []);
  const { fitView, setCenter } = useReactFlow();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pendingClick = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (pendingClick.current) clearTimeout(pendingClick.current);
    },
    [],
  );
  useEffect(() => {
    if (focusId) setSelectedId(focusId);
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
    for (let depth = 0; depth < 2; depth += 1) {
      for (const edge of graph.edges) {
        if (ids.has(edge.source)) ids.add(edge.target);
      }
    }
    return ids;
  }, [graph, filterFramework]);

  const expandScope = useCallback(
    (seed: Set<string>, hops: number) => {
      if (!graph) return seed;
      const ids = new Set(seed);
      for (let depth = 0; depth < hops; depth += 1) {
        for (const edge of graph.edges) {
          if (ids.has(edge.source)) ids.add(edge.target);
          if (ids.has(edge.target)) ids.add(edge.source);
        }
      }
      return ids;
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
    const staleStatuses = new Set(["stale", "expired", "missing"]);
    const seed = new Set<string>();
    for (const node of graph.nodes) {
      if (
        node.kind === "signal_gap" ||
        (node.freshness_status && staleStatuses.has(node.freshness_status))
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
    if (!selectedId) return null;
    const out = new Set<string>([selectedId]);
    for (const n of adjacency.get(selectedId) ?? []) out.add(n);
    return out;
  }, [selectedId, adjacency]);

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

  const { nodes: rfNodes, edges: rfEdges } = useMemo(() => {
    if (!graph) return { nodes: [] as FlowGraphNode[], edges: [] as Edge[] };
    const list: FlowGraphNode[] = filteredNodes.map((n) => {
      let emphasis: GraphNodeData["emphasis"] = "active";
      if (matchSet) emphasis = matchSet.has(n.id) ? "match" : "dimmed";
      else if (pathSet) emphasis = pathSet.nodes.has(n.id) ? "path" : "dimmed";
      else if (highlightSet && !scopeIds)
        emphasis = highlightSet.has(n.id) ? "highlight" : "dimmed";
      return {
        id: n.id,
        type: "trustops-graph",
        className: n.id === focusId ? "focused" : undefined,
        selected: n.id === selectedId,
        position: { x: 0, y: 0 },
        data: {
          label: n.label,
          subtitle: n.subtitle ?? "",
          kind: n.kind,
          layout,
          provider: n.provider,
          status: n.status,
          severity: n.severity,
          framework_id: n.framework_id,
          family_id:
            n.kind === "ccf_family" ? n.id.replace(/^family:/, "") : undefined,
          owner: n.owner,
          risk_score: n.risk_score,
          emphasis,
        },
      };
    });
    const edges: Edge[] = graph.edges
      .filter((e) => allowedIds.has(e.source) && allowedIds.has(e.target))
      .map((e) => {
        const onPath = pathSet?.edges.has(e.id) ?? false;
        const onHighlight =
          Boolean(scopeIds) ||
          (highlightSet &&
            (highlightSet.has(e.source) || highlightSet.has(e.target)));
        const dimmed =
          (matchSet && !matchSet.has(e.source) && !matchSet.has(e.target)) ||
          (pathSet && !onPath) ||
          (highlightSet && !onHighlight);
        return {
          id: e.id,
          data: { relationshipKind: e.kind },
          source: e.source,
          target: e.target,
          label: showEdgeLabels
            ? e.review_state?.replaceAll("_", " ")
            : undefined,
          ariaLabel: `${e.kind.replaceAll("_", " ")}${e.review_state ? `: ${e.review_state.replaceAll("_", " ")}` : ""}`,
          labelStyle: { fill: "var(--color-ink)", fontSize: 11 },
          labelBgStyle: { fill: "var(--color-surface)" },
          animated: onPath,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 16,
            height: 16,
            color: onPath ? "var(--color-warning)" : "var(--color-ink)",
          },
          style: {
            stroke: onPath
              ? "var(--color-warning)"
              : onHighlight
                ? "var(--color-ink)"
                : "var(--color-line-strong)",
            strokeWidth: onPath ? 2.5 : 1.5,
            strokeDasharray:
              e.review_state &&
              !["maintainer_reviewed", "org_reviewed"].includes(e.review_state)
                ? "5 4"
                : undefined,
            opacity: dimmed && !onPath && !onHighlight ? 0.4 : 1,
          },
        };
      });
    return layoutGraph(list, edges, layout, rankLimit, neighborhoodRoot);
  }, [
    neighborhoodRoot,
    rankLimit,
    showEdgeLabels,
    graph,
    filteredNodes,
    allowedIds,
    layout,
    matchSet,
    pathSet,
    highlightSet,
    selectedId,
    focusId,
    scopeIds,
  ]);

  const focusNode = focusId ? rfNodes.find((n) => n.id === focusId) : null;
  const focusX = focusNode ? focusNode.position.x : null;
  const focusY = focusNode ? focusNode.position.y : null;

  useEffect(() => {
    if (rfNodes.length === 0) return;
    const frame = window.requestAnimationFrame(() => {
      // A scoped path is small enough to fit whole at a readable zoom.
      if (focusX !== null && focusY !== null && !scopeIds) {
        setCenter(focusX + 73, focusY + 29, { zoom: 0.9, duration: 300 });
      } else {
        fitView({
          maxZoom: 1,
          padding: 0.06,
          duration: 180,
        });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [
    fitView,
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
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() =>
        fitView({ maxZoom: 1, padding: 0.06 }),
      );
    });
    observer.observe(wrapper);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [fitView, scopeIds, hydrated]);

  // When the search has exactly one match, recentre the viewport on it so the
  // user sees the result immediately.
  useEffect(() => {
    if (!matchSet || matchSet.size !== 1) return;
    const match = rfNodes.find((n) => matchSet.has(n.id));
    if (!match) return;
    setCenter(match.position.x + 73, match.position.y + 29, {
      zoom: 0.9,
      duration: 300,
    });
  }, [matchSet, rfNodes, setCenter]);

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

  return (
    <div
      ref={wrapperRef}
      className={`${heightClassName} overflow-hidden rounded-xl border border-line bg-surface`}
    >
      <ReactFlow
        colorMode={resolvedTheme}
        nodes={rfNodes}
        edges={rfEdges}
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
          className="!h-20 !w-28 !rounded-lg !border !border-line !bg-surface/90 !shadow-card"
          style={{ width: 112, height: 80 }}
          maskColor="rgb(var(--rgb-ink) / 0.06)"
        />
        <Controls position="bottom-left" />
      </ReactFlow>
    </div>
  );
}

export type { ImperativeRef };
