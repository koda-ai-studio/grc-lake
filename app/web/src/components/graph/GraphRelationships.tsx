import { useMemo, useState } from "react";
import type { ComplianceGraph, GraphEdge, GraphNode } from "@/lib/api/types";
import {
  graphEdgeInvalid,
  graphMappingReview,
  graphKindLabel,
} from "@/lib/graph-evidence";
import { Button } from "@/components/ui/button";

function RelationshipGroup({
  direction,
  edges,
  nodes,
  nodeId,
  onInspect,
}: {
  direction: "Incoming" | "Outgoing";
  edges: GraphEdge[];
  nodes: Map<string, GraphNode>;
  nodeId: string;
  onInspect: (node: GraphNode) => void;
}) {
  const [offset, setOffset] = useState(0);
  const start = Math.min(
    offset,
    Math.max(0, Math.ceil(edges.length / 5) - 1) * 5,
  );
  const current = nodes.get(nodeId)?.label ?? nodeId;
  return (
    <div
      role="group"
      aria-label={`${direction} relationships`}
      className="min-w-0 space-y-2"
    >
      <h3 className="font-semibold">
        {direction} · {edges.length}
      </h3>
      {edges.length === 0 && (
        <p className="text-muted">None in this loaded neighborhood.</p>
      )}
      <ul className="grid gap-2">
        {edges.slice(start, start + 5).map((edge) => {
          const otherId = direction === "Incoming" ? edge.source : edge.target;
          const other = nodes.get(otherId);
          const review = graphMappingReview(edge);
          const endpoint = other ? (
            <button
              type="button"
              aria-label={`Inspect ${other.label}${other.source_account_id ? ` in ${other.source_account_id}` : ""}`}
              onClick={() => onInspect(other)}
              className="break-words text-left font-semibold text-brand underline underline-offset-2"
            >
              {other.label}
            </button>
          ) : (
            <span className="break-all">{otherId}</span>
          );
          return (
            <li
              key={edge.id}
              className="space-y-1 rounded-lg border border-line p-2"
            >
              <p className="break-words">
                {direction === "Incoming" ? (
                  <>
                    {endpoint} → {current}
                  </>
                ) : (
                  <>
                    {current} → {endpoint}
                  </>
                )}
              </p>
              <p className="text-muted">
                {edge.kind.replaceAll("_", " ")}
                {other ? ` · ${graphKindLabel(other.kind)}` : ""}
              </p>
              {other?.source_account_id && (
                <p className="break-all text-muted">
                  Source account: {other.source_account_id}
                </p>
              )}
              {review && (
                <p
                  className={
                    review.reviewed
                      ? "text-muted"
                      : "font-medium text-warning-fg"
                  }
                >
                  {review.label} · catalog mapping
                </p>
              )}
              {graphEdgeInvalid(edge) && (
                <p className="font-semibold text-danger-fg">
                  Invalid asset type · does not support this asset
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {edges.length > 5 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted">
            {start + 1}–{Math.min(start + 5, edges.length)} of {edges.length}
          </span>
          <Button
            size="sm"
            disabled={start === 0}
            aria-label={`Previous ${direction.toLowerCase()} relationships`}
            onClick={() => setOffset(start - 5)}
          >
            Previous
          </Button>
          <Button
            size="sm"
            disabled={start + 5 >= edges.length}
            aria-label={`Next ${direction.toLowerCase()} relationships`}
            onClick={() => setOffset(start + 5)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

export function GraphRelationships({
  graph,
  nodeId,
  onInspect,
}: {
  graph: ComplianceGraph;
  nodeId: string;
  onInspect: (node: GraphNode) => void;
}) {
  const nodes = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes],
  );
  const incoming = useMemo(
    () => graph.edges.filter((edge) => edge.target === nodeId),
    [graph.edges, nodeId],
  );
  const outgoing = useMemo(
    () => graph.edges.filter((edge) => edge.source === nodeId),
    [graph.edges, nodeId],
  );
  return (
    <section
      aria-label="Selected node relationships"
      className="mt-3 space-y-3 text-xs"
    >
      <p className="text-muted">
        Recorded links in the loaded neighborhood. Arrow direction describes a
        relationship, not chronological progress or a compliance pass.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <RelationshipGroup
          key={`${nodeId}:in`}
          direction="Incoming"
          edges={incoming}
          nodes={nodes}
          nodeId={nodeId}
          onInspect={onInspect}
        />
        <RelationshipGroup
          key={`${nodeId}:out`}
          direction="Outgoing"
          edges={outgoing}
          nodes={nodes}
          nodeId={nodeId}
          onInspect={onInspect}
        />
      </div>
    </section>
  );
}
