"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
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
  const workspace = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [inlineExpanded, setInlineExpanded] = useState(false);
  const expandButton = useRef<HTMLButtonElement>(null);
  const [trail, setTrail] = useState<{ id: string; label: string }[]>([]);
  useEffect(() => {
    const update = () =>
      setExpanded(document.fullscreenElement === workspace.current);
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);
  useEffect(() => {
    if (!inlineExpanded) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setInlineExpanded(false);
        setExpanded(false);
        expandButton.current?.focus();
      }
      if (event.key === "Tab") {
        const focusable = Array.from(
          workspace.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], select:not(:disabled), input:not(:disabled), summary, [tabindex="0"]',
          ) ?? [],
        ).filter((element) => element.getClientRects().length > 0);
        const first = focusable[0];
        const last = focusable.at(-1);
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            !workspace.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          last?.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            !workspace.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", keyboard);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", keyboard);
    };
  }, [inlineExpanded]);
  const [rootOffset, setRootOffset] = useState(0);
  const [safeguardPage, setSafeguardPage] = useState({
    root: "",
    framework: "",
    offset: 0,
  });
  const searchParams = useSearchParams();
  const [view, setView] = useState(
    /^(control|safeguard|framework|category|family):/.test(
      searchParams.get("root") ?? "",
    ) || !searchParams.get("root")
      ? "controls"
      : "investigation",
  );
  const [root, setRoot] = useState(searchParams.get("root") ?? "");
  const [depth, setDepth] = useState(2);
  const [search, setSearch] = useState("");
  const [version, setVersion] = useState("");
  const [visible, setVisible] = useState(new Set(layers));
  const [repositoryView, setRepositoryView] = useState("evidence");
  const [evidencePage, setEvidencePage] = useState(0);
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
  if (safeguardPage.root === root) {
    params.set("framework", safeguardPage.framework);
    params.set("control_offset", String(safeguardPage.offset));
  }
  if (version) params.set("version", version);
  const query = useQuery({
    queryKey: ["investigation-graph", params.toString()],
    queryFn: () => api.investigationGraph(params),
    placeholderData: (previous) => previous,
  });
  const data = query.data;
  const currentRoot = root || data?.root || "";
  const repositoryRoot =
    data?.nodes.find((node) => node.id === currentRoot)?.kind === "repository";
  const evidenceScope = useMemo(() => {
    const hasEvaluatedRecords = data?.nodes.some(
      (node) => node.kind === "evidence_type",
    );
    const kinds = new Set([
      "evidence_type",
      "signal_gap",
      "governance_signal",
      "finding",
    ]);
    if (!hasEvaluatedRecords) kinds.add("evidence");
    const direct = new Set(
      data?.edges.flatMap((edge) =>
        edge.source === currentRoot
          ? [edge.target]
          : edge.target === currentRoot
            ? [edge.source]
            : [],
      ),
    );
    return new Set(
      data?.nodes
        .filter(
          (node) =>
            node.id === currentRoot ||
            (direct.has(node.id) && kinds.has(node.kind)),
        )
        .map((node) => node.id),
    );
  }, [data, currentRoot]);
  const evidencePages = useMemo(() => {
    const incomingIds = new Set(
      data?.edges
        .filter((edge) => edge.target === currentRoot)
        .map((edge) => edge.source),
    );
    const nodes = (data?.nodes ?? [])
      .filter((node) => node.id !== currentRoot && evidenceScope.has(node.id))
      .sort(
        (a, b) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id),
      );
    const incoming = nodes.filter((node) => incomingIds.has(node.id));
    const outgoing = nodes.filter((node) => !incomingIds.has(node.id));
    const pageCount = Math.max(
      1,
      Math.ceil(Math.max(incoming.length, outgoing.length) / 5),
    );
    const page = Math.min(evidencePage, pageCount - 1);
    // Keep a small lane visible while paging the larger lane. Every shown edge
    // retains its recorded endpoints; pagination never synthesizes a link.
    const slice = (rows: GraphNode[]) =>
      rows.length <= 5 ? rows : rows.slice(page * 5, (page + 1) * 5);
    return {
      page,
      pageCount,
      incoming: incoming.length,
      outgoing: outgoing.length,
      ids: new Set([
        currentRoot,
        ...slice(incoming).map((node) => node.id),
        ...slice(outgoing).map((node) => node.id),
      ]),
    };
  }, [data, currentRoot, evidenceScope, evidencePage]);
  const scopeIds = useMemo(
    () =>
      repositoryRoot && repositoryView === "evidence"
        ? evidencePages.ids
        : new Set(data?.nodes.map((node) => node.id)),
    [data, evidencePages, repositoryRoot, repositoryView],
  );
  const canvasGraph = useMemo(
    () =>
      repositoryRoot && repositoryView === "evidence" && data
        ? {
            ...data,
            edges: data.edges.filter(
              (edge) =>
                edge.source === currentRoot || edge.target === currentRoot,
            ),
          }
        : data,
    [data, currentRoot, repositoryRoot, repositoryView],
  );
  const shownEdges =
    canvasGraph?.edges.filter(
      (edge) => scopeIds.has(edge.source) && scopeIds.has(edge.target),
    ).length ?? 0;
  const mappingStates = [
    ...new Set(
      data?.edges.flatMap((e) => (e.review_state ? [e.review_state] : [])),
    ),
  ];
  const selectedNode = data?.nodes.find((n) => n.id === selected?.id) ?? null;
  const recordedParent = data?.edges.find(
    (e) =>
      e.target === currentRoot &&
      ["contains", "framework_has_control"].includes(e.kind),
  );
  const rollupTarget = trail.at(-1)?.id ?? recordedParent?.source;
  const exploreNode = (target: GraphNode) => {
    if (target.id !== currentRoot) {
      setTrail((current) => [
        ...current,
        {
          id: currentRoot,
          label:
            data?.nodes.find((node) => node.id === currentRoot)?.label ??
            currentRoot,
        },
      ]);
      setRoot(target.id);
      setRepositoryView("evidence");
      setEvidencePage(0);
      setSelected(null);
    }
    setVersion(data?.version ?? "");
  };
  const reset = () => {
    setTrail([]);
    setRootOffset(0);
    setRoot("");
    setRepositoryView("evidence");
    setEvidencePage(0);
    setVersion("");
    setSelected(null);
  };
  return (
    <div className="page-shell space-y-2">
      <PageHeader
        title="Evidence investigation"
        description="Inspect recorded paths and outcomes. Maps show catalog coverage and repository structure."
      />
      <details className="rounded-xl border border-line bg-surface p-3">
        <summary className="cursor-pointer text-sm font-semibold">
          Search and change starting point
        </summary>
        <div className="mt-3 space-y-3">
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
                placeholder="Type to filter starting points…"
                aria-label="Find a starting point"
              />
            </label>
            <label className="grid min-w-0 flex-1 gap-1 text-xs text-muted">
              Starting point
              <select
                aria-label="Graph starting point"
                className="ui-input min-w-0"
                value={currentRoot}
                onChange={(e) => {
                  setTrail([]);
                  setRoot(e.target.value);
                  setRepositoryView("evidence");
                  setEvidencePage(0);
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
                  aria-label="Previous starting points"
                  disabled={rootOffset === 0}
                  onClick={() => setRootOffset(Math.max(0, rootOffset - 50))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  aria-label="Next starting points"
                  disabled={data.next_root_offset === null}
                  onClick={() => setRootOffset(data.next_root_offset!)}
                >
                  Next
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
      </details>
      {query.isError && (
        <Button onClick={reset}>Reset to current evidence</Button>
      )}
      <QueryState queries={[query]} label="investigation graph">
        {data && (
          <>
            {data.root_missing || data.nodes.length === 0 ? (
              <div className="rounded-xl border border-line p-6 text-sm text-muted">
                No recorded relationships for this selection. Choose another
                starting point or enable its layer. Vendor links require
                explicit source-account and asset IDs.
              </div>
            ) : (
              <section
                ref={workspace}
                aria-label="Graph workspace"
                className={`space-y-3 ${expanded ? "h-screen overflow-auto bg-surface p-4" : ""} ${inlineExpanded ? "fixed inset-0 z-50" : ""}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={!rollupTarget}
                    onClick={() => {
                      if (!rollupTarget) return;
                      setRoot(rollupTarget);
                      setRepositoryView("evidence");
                      setEvidencePage(0);
                      setTrail(trail.slice(0, -1));
                      setSelected(null);
                      setVersion(data.version);
                    }}
                  >
                    Roll up
                  </Button>
                  <p
                    aria-label="Current graph path"
                    className="min-w-0 flex-1 truncate text-sm font-medium"
                    title={[
                      ...trail.map((n) => n.label),
                      data.nodes.find((n) => n.id === currentRoot)?.label ??
                        currentRoot,
                    ].join(" → ")}
                  >
                    {trail.length > 0
                      ? `${trail.length} level${trail.length === 1 ? "" : "s"} deeper · `
                      : ""}
                    {data.nodes.find((n) => n.id === currentRoot)?.label ??
                      "Evidence neighborhood"}
                  </p>
                  {expanded && (
                    <label className="flex items-center gap-2 text-xs text-muted">
                      Depth
                      <select
                        aria-label="Workspace graph depth"
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
                  )}
                  <Button
                    ref={expandButton}
                    size="sm"
                    onClick={async () => {
                      if (inlineExpanded) {
                        setInlineExpanded(false);
                        setExpanded(false);
                        return;
                      }
                      try {
                        if (expanded) await document.exitFullscreen();
                        else await workspace.current?.requestFullscreen();
                      } catch {
                        setInlineExpanded(true);
                        setExpanded(true);
                      }
                    }}
                  >
                    {expanded
                      ? "Exit expanded workspace"
                      : "Expand graph workspace"}
                  </Button>
                </div>
                {(data.framework_groups?.length ?? 0) > 0 && (
                  <div
                    className="flex flex-wrap items-center gap-2 text-xs"
                    aria-label="Safeguard framework groups"
                  >
                    <label className="flex items-center gap-2">
                      Framework
                      <select
                        className="ui-input"
                        aria-label="Safeguard framework"
                        value={data.selected_framework}
                        onChange={(e) => {
                          setSafeguardPage({
                            root: currentRoot,
                            framework: e.target.value,
                            offset: 0,
                          });
                          setSelected(null);
                        }}
                      >
                        {data.framework_groups.map((group) => (
                          <option
                            key={group.framework_id}
                            value={group.framework_id}
                          >
                            {group.label} ({group.control_count})
                          </option>
                        ))}
                      </select>
                    </label>
                    <span>
                      {data.framework_groups.reduce(
                        (total, group) => total + group.control_count,
                        0,
                      )}{" "}
                      mapped controls across {data.framework_groups.length}{" "}
                      frameworks · mapping does not establish a pass
                    </span>
                    <span>
                      Controls{" "}
                      {data.control_count ? data.control_offset + 1 : 0}–
                      {Math.min(data.control_offset + 5, data.control_count)} of{" "}
                      {data.control_count}
                    </span>
                    <Button
                      size="sm"
                      aria-label="Previous mapped controls"
                      disabled={!data.control_offset}
                      onClick={() => {
                        setSafeguardPage({
                          root: currentRoot,
                          framework: data.selected_framework,
                          offset: Math.max(0, data.control_offset - 5),
                        });
                        setSelected(null);
                      }}
                    >
                      Previous
                    </Button>
                    <Button
                      size="sm"
                      aria-label="Next mapped controls"
                      disabled={data.next_control_offset === null}
                      onClick={() => {
                        setSafeguardPage({
                          root: currentRoot,
                          framework: data.selected_framework,
                          offset: data.next_control_offset!,
                        });
                        setSelected(null);
                      }}
                    >
                      Next
                    </Button>
                  </div>
                )}
                {repositoryRoot && (
                  <div
                    role="group"
                    aria-label="Repository graph detail"
                    className="flex flex-wrap items-center gap-2"
                  >
                    <Button
                      size="sm"
                      variant={
                        repositoryView === "evidence" ? "primary" : "default"
                      }
                      aria-pressed={repositoryView === "evidence"}
                      onClick={() => {
                        setRepositoryView("evidence");
                        setEvidencePage(0);
                        setSelected(null);
                      }}
                    >
                      Evidence focus ({evidenceScope.size})
                    </Button>
                    <Button
                      size="sm"
                      variant={repositoryView === "all" ? "primary" : "default"}
                      aria-pressed={repositoryView === "all"}
                      onClick={() => setRepositoryView("all")}
                    >
                      All relationships ({data.nodes.length})
                    </Button>
                    <span className="text-xs text-muted">
                      Files and code structure are available in all
                      relationships.
                    </span>
                  </div>
                )}
                {repositoryRoot && repositoryView === "evidence" && (
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                    <span>
                      Incoming relationships → Repository → Outgoing
                      relationships. Arrows follow recorded links, not execution
                      order.
                    </span>
                    {evidencePages.pageCount > 1 && (
                      <>
                        <span>
                          Page {evidencePages.page + 1} of{" "}
                          {evidencePages.pageCount} · {evidencePages.incoming}{" "}
                          incoming, {evidencePages.outgoing} outgoing records
                        </span>
                        <Button
                          size="sm"
                          aria-label="Previous evidence records"
                          disabled={evidencePages.page === 0}
                          onClick={() => {
                            setEvidencePage(evidencePages.page - 1);
                            setSelected(null);
                          }}
                        >
                          Previous
                        </Button>
                        <Button
                          size="sm"
                          aria-label="Next evidence records"
                          disabled={
                            evidencePages.page + 1 >= evidencePages.pageCount
                          }
                          onClick={() => {
                            setEvidencePage(evidencePages.page + 1);
                            setSelected(null);
                          }}
                        >
                          Next
                        </Button>
                      </>
                    )}
                  </div>
                )}
                <div
                  className={`grid items-start gap-3 ${selectedNode ? "xl:grid-cols-[minmax(0,1fr)_300px]" : ""}`}
                >
                  <div className="min-w-0">
                    <GraphCanvas
                      graph={canvasGraph}
                      scopeIds={scopeIds}
                      showEdgeLabels={false}
                      neighborhoodRoot={
                        repositoryRoot && repositoryView === "evidence"
                          ? currentRoot
                          : undefined
                      }
                      heightClassName={
                        expanded
                          ? "h-[calc(100dvh-180px)] min-h-[400px]"
                          : undefined
                      }
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
                      rankLimit={
                        repositoryRoot && repositoryView === "all" ? 8 : 4
                      }
                      focusId={selectedNode?.id}
                      onSelectNode={setSelected}
                      onExploreNode={exploreNode}
                    />
                  </div>
                  <GraphNodeDrawer
                    node={selectedNode}
                    graphMode="investigation"
                    graph={data}
                    onInspectNode={(node) => {
                      if (node && !scopeIds.has(node.id))
                        setRepositoryView("all");
                      setSelected(node);
                    }}
                    onClose={() => setSelected(null)}
                    onFocusPath={
                      selectedNode ? () => exploreNode(selectedNode) : undefined
                    }
                  />
                </div>
                <details className="rounded-xl border border-line p-3">
                  <summary className="cursor-pointer text-sm font-semibold">
                    Selected relationships and mapping review state
                  </summary>
                  <ul className="mt-3 grid gap-2 text-xs">
                    {data.edges
                      .filter(
                        (e) =>
                          e.source === (selectedNode?.id ?? currentRoot) ||
                          e.target === (selectedNode?.id ?? currentRoot),
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
                <p role="status" className="text-xs text-muted">
                  {scopeIds.size === data.nodes.length
                    ? `${data.nodes.length} nodes · ${data.edges.length} relationships`
                    : `${scopeIds.size} of ${data.nodes.length} loaded nodes · ${shownEdges} of ${data.edges.length} relationships`}{" "}
                  · {data.boundary}.{" "}
                  {data.truncated
                    ? `${data.matching_nodes} nodes match; showing a bounded subset. Reduce depth or expand a selected node.`
                    : ""}{" "}
                  {data.root_count > 50
                    ? `Starting points ${data.root_offset + 1}–${Math.min(data.root_offset + 50, data.root_count)} of ${data.root_count}; search to narrow.`
                    : ""}
                </p>
                <p className="text-xs text-muted">
                  Click a node for details. Double-click or press Shift+Enter to
                  explore its connections.
                </p>
                {mappingStates.length > 0 && (
                  <p
                    aria-label="Mapping review states"
                    className="text-xs text-muted"
                  >
                    Mapping review:{" "}
                    {mappingStates
                      .map((state) => state.replaceAll("_", " "))
                      .join(" · ")}
                    . Details below.
                  </p>
                )}
              </section>
            )}
          </>
        )}
      </QueryState>
    </div>
  );
}
