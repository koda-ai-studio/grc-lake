/**
 * Above this many nodes a laid-out graph stops being readable and dagre plus
 * the DOM cost freeze the page, so the canvas asks for a narrower slice.
 */
export const GRAPH_LAYOUT_NODE_CAP = 500;

/** Larger drawable graphs render only the nodes inside the viewport. */
export const GRAPH_VIRTUALIZE_ABOVE = 200;

/** Zoom below which node labels are too small to read. */
export const GRAPH_READABLE_ZOOM = 0.6;

export function graphLayoutBudget(nodeCount: number) {
  return {
    draw: nodeCount <= GRAPH_LAYOUT_NODE_CAP,
    virtualize: nodeCount > GRAPH_VIRTUALIZE_ABOVE,
  };
}
