import type { GraphEdge } from "@/lib/api/types";

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
