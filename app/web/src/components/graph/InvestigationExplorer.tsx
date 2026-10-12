"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { GraphNode, GraphNodeKind } from "@/lib/api/types";
import { GRAPH_KIND_COLOR } from "@/lib/graph-palette";
import { GraphCanvas } from "./GraphCanvas";
import { GraphNodeDrawer } from "./GraphNodeDrawer";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { QueryState } from "@/components/QueryState";

const layers = Object.keys(GRAPH_KIND_COLOR) as GraphNodeKind[];
const optional: GraphNodeKind[] = [
  "source",
  "vendor",
  "finding",
  "framework",
  "ccf_category",
  "ccf_family",
  "safeguard",
];

export function InvestigationExplorer() {
  const [rootOffset, setRootOffset] = useState(0);
  const [view, setView] = useState("controls");
  const [root, setRoot] = useState("");
  const [depth, setDepth] = useState(2);
  const [search, setSearch] = useState("");
  const [version, setVersion] = useState("");
  const [visible, setVisible] = useState(new Set(layers));
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const params = new URLSearchParams({
    view,
    root_offset: String(rootOffset),
    depth: String(depth),
    limit: "150",
    search,
    layers: [...visible].sort().join(","),
  });
  if (root) params.set("root", root);
  if (version) params.set("version", version);
  const query = useQuery({
    queryKey: ["investigation-graph", params.toString()],
    queryFn: () => api.investigationGraph(params),
  });
  const data = query.data;
  const currentRoot = root || data?.root || "";
  const selectedNode = data?.nodes.find((n) => n.id === selected?.id) ?? null;
  const reset = () => {
    setRootOffset(0);
    setRoot("");
    setVersion("");
    setSelected(null);
  };
  return (
    <div className="page-shell space-y-4">
      <PageHeader
        title="Evidence investigation"
        description="Follow recorded relationships from requirements and safeguards to evidence, environments and findings."
      />
      <div className="rounded-xl border border-line bg-surface p-3 space-y-3">
        <div
          role="group"
          aria-label="Investigation view"
          className="flex flex-wrap gap-2"
        >
          {["controls", "environment", "investigation"].map((value) => (
            <Button
              key={value}
              aria-pressed={view === value}
              variant={view === value ? "primary" : "default"}
              onClick={() => {
                setView(value);
                reset();
              }}
            >
              {value === "controls"
                ? "Controls & CCF"
                : value === "environment"
                  ? "Environment"
                  : "Findings, sources & vendors"}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid gap-1 text-xs text-muted">
            Find a starting point
            <input
              className="ui-input"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                reset();
              }}
              placeholder="Search this view…"
            />
          </label>
          <label className="grid min-w-0 flex-1 gap-1 text-xs text-muted">
            Starting point
            <select
              aria-label="Graph starting point"
              className="ui-input min-w-0"
              value={currentRoot}
              onChange={(e) => {
                setRoot(e.target.value);
                setVersion(data?.version ?? "");
                setSelected(null);
              }}
            >
              <option value="">Choose a recorded node</option>
              {currentRoot &&
                !data?.roots.some((n) => n.id === currentRoot) && (
                  <option value={currentRoot}>
                    {data?.nodes.find((n) => n.id === currentRoot)?.label ??
                      currentRoot}
                  </option>
                )}
              {data?.roots.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label} · {n.kind.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          {data && data.root_count > 50 && (
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                disabled={rootOffset === 0}
                onClick={() => setRootOffset(Math.max(0, rootOffset - 50))}
              >
                Previous starting points
              </Button>
              <Button
                size="sm"
                disabled={data.next_root_offset === null}
                onClick={() => setRootOffset(data.next_root_offset!)}
              >
                Next starting points
              </Button>
            </div>
          )}
          <label className="grid gap-1 text-xs text-muted">
            Depth
            <select
              aria-label="Graph depth"
              className="ui-input"
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
            >
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>
                  {n} {n === 1 ? "hop" : "hops"}
                </option>
              ))}
            </select>
          </label>
          <Button
            onClick={() => {
              setSelected(null);
              if (version) setVersion("");
              else void query.refetch();
            }}
          >
            Refresh evidence
          </Button>
        </div>
        <details>
          <summary className="cursor-pointer text-xs font-semibold">
            Visible relationship layers
          </summary>
          <div className="mt-2 flex flex-wrap gap-3">
            {optional.map((kind) => (
              <label key={kind} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={visible.has(kind)}
                  onChange={(e) => {
                    setVisible((current) => {
                      const next = new Set(current);
                      if (e.target.checked) next.add(kind);
                      else next.delete(kind);
                      return next;
                    });
                    setVersion("");
                  }}
                />
                {kind.replaceAll("_", " ")}
              </label>
            ))}
          </div>
        </details>
      </div>
      {query.isError && (
        <Button onClick={reset}>Reset to current evidence</Button>
      )}
      <QueryState queries={[query]} label="investigation graph">
        {data && (
          <>
            <p role="status" className="text-xs text-muted">
              {data.nodes.length} nodes · {data.edges.length} relationships ·{" "}
              {data.boundary}.{" "}
              {data.truncated
                ? `${data.matching_nodes} nodes match; showing a bounded subset. Reduce depth or expand a selected node.`
                : ""}{" "}
              {data.root_count > 50
                ? `Starting points ${data.root_offset + 1}–${Math.min(data.root_offset + 50, data.root_count)} of ${data.root_count}; search to narrow.`
                : ""}
            </p>
            {data.root_missing || data.nodes.length === 0 ? (
              <div className="rounded-xl border border-line p-6 text-sm text-muted">
                No recorded relationships for this selection. Choose another
                starting point or enable its layer. Vendor links require
                explicit source-account and asset IDs.
              </div>
            ) : (
              <div
                className={`grid items-start gap-3 ${selectedNode ? "xl:grid-cols-[minmax(0,1fr)_320px]" : ""}`}
              >
                <div className="h-[620px] min-w-0 rounded-xl border border-line bg-surface">
                  <GraphCanvas
                    graph={data}
                    visibleKinds={visible}
                    layout="LR"
                    filterOwner=""
                    filterEnvironment=""
                    filterFramework=""
                    filterControl=""
                    filterWorkflow=""
                    filterStaleOnly={false}
                    searchQuery=""
                    pathFrom={null}
                    pathTo={null}
                    rankLimit={4}
                    focusId={selectedNode?.id}
                    onSelectNode={setSelected}
                  />
                </div>
                <GraphNodeDrawer
                  node={selectedNode}
                  graphMode="investigation"
                  onClose={() => setSelected(null)}
                  onFocusPath={
                    selectedNode
                      ? () => {
                          setRoot(selectedNode.id);
                          setVersion(data.version);
                        }
                      : undefined
                  }
                />
              </div>
            )}
            {selectedNode &&
              data.edges.some(
                (e) =>
                  e.source === selectedNode.id || e.target === selectedNode.id,
              ) && (
                <details className="rounded-xl border border-line p-3">
                  <summary className="cursor-pointer text-sm font-semibold">
                    Selected relationships and mapping review state
                  </summary>
                  <ul className="mt-3 grid gap-2 text-xs">
                    {data.edges
                      .filter(
                        (e) =>
                          e.source === selectedNode.id ||
                          e.target === selectedNode.id,
                      )
                      .map((e) => (
                        <li key={e.id}>
                          {data.nodes.find((n) => n.id === e.source)?.label} →{" "}
                          {data.nodes.find((n) => n.id === e.target)?.label} ·{" "}
                          {e.kind.replaceAll("_", " ")}
                          {e.review_state
                            ? ` · ${e.review_state.replaceAll("_", " ")} (catalog mapping)`
                            : ""}
                        </li>
                      ))}
                  </ul>
                </details>
              )}
          </>
        )}
      </QueryState>
    </div>
  );
}
