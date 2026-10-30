import type { GraphEdge } from "@/lib/api/types";

/** A shortest recorded connection; arrow direction stays on the original edges. */
export function graphConnection(
  edges: Pick<GraphEdge, "id" | "source" | "target">[],
  visible: Set<string>,
  from: string | null,
  to: string | null,
) {
  const empty = { nodes: new Set<string>(), edges: new Set<string>() };
  if (!from || !to) return { ...empty, status: "idle" as const };
  if (!visible.has(from) || !visible.has(to))
    return { ...empty, status: "hidden" as const };
  if (from === to)
    return { ...empty, nodes: new Set([from]), status: "same" as const };
  const adjacent = new Map<string, { node: string; edge: string }[]>();
  for (const edge of [...edges].sort((a, b) => a.id.localeCompare(b.id))) {
    if (!visible.has(edge.source) || !visible.has(edge.target)) continue;
    for (const [node, neighbor] of [
      [edge.source, edge.target],
      [edge.target, edge.source],
    ]) {
      if (!adjacent.has(node)) adjacent.set(node, []);
      adjacent.get(node)!.push({ node: neighbor, edge: edge.id });
    }
  }
  const visited = new Map<string, { node: string; edge: string } | null>([
    [from, null],
  ]);
  const queue = [from];
  for (let cursor = 0; cursor < queue.length && !visited.has(to); cursor++) {
    const current = queue[cursor];
    for (const next of adjacent.get(current) ?? []) {
      if (visited.has(next.node)) continue;
      visited.set(next.node, { node: current, edge: next.edge });
      queue.push(next.node);
    }
  }
  if (!visited.has(to)) return { ...empty, status: "disconnected" as const };
  const nodes = new Set([to]);
  const connections = new Set<string>();
  let step = to;
  while (step !== from) {
    const previous = visited.get(step)!;
    connections.add(previous!.edge);
    step = previous!.node;
    nodes.add(step);
  }
  return { nodes, edges: connections, status: "found" as const };
}

/**
 * Above this many nodes a laid-out graph stops being readable and dagre plus
 * the DOM cost freeze the page, so the canvas asks for a narrower slice.
 */
export const GRAPH_LAYOUT_NODE_CAP = 500;

/** Dense graphs can exhaust layout work well below the node limit. */
export const GRAPH_LAYOUT_EDGE_CAP = 1000;

/** Larger drawable graphs render only the nodes inside the viewport. */
export const GRAPH_VIRTUALIZE_ABOVE = 200;

/** Zoom below which node labels are too small to read. */
export const GRAPH_READABLE_ZOOM = 0.6;

export function graphLayoutBudget(nodeCount: number, edgeCount = 0) {
  return {
    draw:
      nodeCount <= GRAPH_LAYOUT_NODE_CAP && edgeCount <= GRAPH_LAYOUT_EDGE_CAP,
    virtualize: nodeCount > GRAPH_VIRTUALIZE_ABOVE || edgeCount > 400,
  };
}
/** A hop advances one frontier; edge ordering cannot widen the scope. */
export function graphScope(
  edges: Pick<GraphEdge, "source" | "target">[],
  seed: Set<string>,
  hops: number,
  directed = false,
) {
  const ids = new Set(seed);
  const adjacent = new Map<string, Set<string>>();
  const add = (from: string, to: string) => {
    if (!adjacent.has(from)) adjacent.set(from, new Set());
    adjacent.get(from)!.add(to);
  };
  for (const edge of edges) {
    add(edge.source, edge.target);
    if (!directed) add(edge.target, edge.source);
  }
  let frontier = [...seed];
  for (let depth = 0; depth < hops; depth += 1) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const neighbor of adjacent.get(id) ?? []) {
        if (ids.has(neighbor)) continue;
        ids.add(neighbor);
        next.push(neighbor);
      }
    }
    frontier = next;
    if (!frontier.length) break;
  }
  return ids;
}

type LayoutRecord = { id: string; kind: string; label: string };
type Point = { x: number; y: number };
export type RoutingBox = Point & { width: number; height: number };

const ASSURANCE_COLUMNS: Record<string, number> = {
  framework: 0,
  ccf_category: 0,
  control: 1,
  ccf_family: 1,
  safeguard: 2,
};

export function graphAssuranceKind(kind: string) {
  return Object.hasOwn(ASSURANCE_COLUMNS, kind);
}

/** Separate assurance from lineage; only recorded neighbors influence row order. */
export function investigationPositions(
  nodes: LayoutRecord[],
  edges: Pick<GraphEdge, "source" | "target">[],
) {
  const lineage: Record<string, number> = {
    source: 0,
    vendor: 0,
    account: 0,
    environment: 0,
    evidence_type: 1,
    evidence: 1,
    signal_gap: 1,
    governance_signal: 1,
    asset: 2,
    repository: 2,
    canonical_entity: 2,
  };
  const positions = new Map<string, Point>();
  const sorted = [...nodes].sort(
    (a, b) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id),
  );
  const neighbors = new Map<string, string[]>();
  for (const edge of edges) {
    neighbors.set(edge.target, [
      ...(neighbors.get(edge.target) ?? []),
      edge.source,
    ]);
  }
  let top = 0;
  for (const hierarchy of [true, false]) {
    const section = sorted.filter(
      (n) => graphAssuranceKind(n.kind) === hierarchy,
    );
    let lastRow = -1;
    for (let column = 0; column < 4; column++) {
      const occupied = new Set<number>();
      const lane = section.filter(
        (n) =>
          (hierarchy ? ASSURANCE_COLUMNS[n.kind] : (lineage[n.kind] ?? 3)) ===
          column,
      );
      const preferred = (node: LayoutRecord) => {
        const rows = (neighbors.get(node.id) ?? []).flatMap((id) => {
          const p = positions.get(id);
          return p && p.y >= top ? [(p.y - top) / 136] : [];
        });
        return rows.length
          ? Math.round(rows.reduce((a, b) => a + b, 0) / rows.length)
          : 0;
      };
      lane.sort(
        (a, b) =>
          preferred(a) - preferred(b) ||
          a.label.localeCompare(b.label) ||
          a.id.localeCompare(b.id),
      );
      for (const node of lane) {
        let row = preferred(node);
        while (occupied.has(row)) row++;
        occupied.add(row);
        lastRow = Math.max(lastRow, row);
        positions.set(node.id, { x: column * 340, y: top + row * 136 });
      }
    }
    if (section.length) top += (lastRow + 1) * 136 + 72;
  }
  return positions;
}

/** Route via the open gutters between cards, including reverse and cross-lane links. */
export function investigationRoute(
  source: Point,
  target: Point,
  boxes: RoutingBox[],
  offset = 0,
  targetSide: "left" | "top" = "left",
): Point[] {
  const clear = (a: Point, b: Point) =>
    !boxes.some((box) =>
      a.x === b.x
        ? a.x > box.x &&
          a.x < box.x + box.width &&
          Math.max(a.y, b.y) > box.y &&
          Math.min(a.y, b.y) < box.y + box.height
        : a.y > box.y &&
          a.y < box.y + box.height &&
          Math.max(a.x, b.x) > box.x &&
          Math.min(a.x, b.x) < box.x + box.width,
    );
  const right = source.x + 20 + offset;
  if (targetSide === "top") {
    const approach = target.y - 18;
    const route = [
      source,
      { x: right, y: source.y },
      { x: right, y: approach },
      { x: target.x, y: approach },
      target,
    ];
    return route.slice(1).every((p, i) => clear(route[i], p)) ? route : [];
  }
  const left = target.x - 20 - offset;
  const rows = [
    ...new Set([
      source.y,
      target.y,
      ...boxes.flatMap((b) => [b.y - 18, b.y + b.height + 18]),
    ]),
  ];
  const candidates = rows.map((y) => [
    source,
    { x: right, y: source.y },
    { x: right, y },
    { x: left, y },
    { x: left, y: target.y },
    target,
  ]);
  if (source.x < target.x)
    candidates.unshift([
      source,
      { x: right, y: source.y },
      { x: right, y: target.y },
      target,
    ]);
  const length = (points: Point[]) =>
    points
      .slice(1)
      .reduce(
        (sum, p, i) =>
          sum + Math.abs(p.x - points[i].x) + Math.abs(p.y - points[i].y),
        0,
      );
  candidates.sort((a, b) => length(a) - length(b));
  return (
    candidates.find((points) =>
      points.slice(1).every((p, i) => clear(points[i], p)),
    ) ?? []
  );
}
