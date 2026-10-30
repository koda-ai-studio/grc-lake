"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { CONSOLE_BASE_PATH } from "@/lib/base-path";
import type { GraphNode, GraphNodeKind } from "@/lib/api/types";
import { GRAPH_KIND_COLOR } from "@/lib/graph-palette";
import { graphScope } from "@/lib/graph-layout";
import { graphRecordLabel, labelWithKind } from "@/lib/graph-evidence";
import { GraphRelationships } from "./GraphRelationships";
import { GraphCanvas } from "./GraphCanvas";
import { GraphNodeDrawer } from "./GraphNodeDrawer";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { QueryState } from "@/components/QueryState";

const demo = process.env.NEXT_PUBLIC_DEMO_SNAPSHOT === "1";
type DemoStartingPoint = Pick<GraphNode, "id" | "label" | "kind"> & {
  version: string;
};

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

type NavigationStep = {
  id: string;
  label: string;
  depth: number;
  rootOffset: number;
  safeguardPage: { root: string; framework: string; offset: number };
  repositoryView: string;
  evidencePage: number;
  visible: Set<GraphNodeKind>;
  version: string;
};

export function InvestigationExplorer() {
  const workspace = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [inlineExpanded, setInlineExpanded] = useState(false);
  const expandButton = useRef<HTMLButtonElement>(null);
  const [trail, setTrail] = useState<NavigationStep[]>([]);
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
  const [relationshipLabels, setRelationshipLabels] = useState(false);
  const [search, setSearch] = useState("");
  const [version, setVersion] = useState("");
  const [visible, setVisible] = useState(new Set(layers));
  const [repositoryView, setRepositoryView] = useState("evidence");
  const [evidencePage, setEvidencePage] = useState(0);
  const [directFocus, setDirectFocus] = useState<{
    id: string;
    key: string;
  } | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const params = new URLSearchParams({
    view,
    root_offset: String(demo ? 0 : rootOffset),
    depth: String(depth),
    limit: "150",
    search: demo ? "" : search,
    layers: (demo ? layers : [...visible]).slice().sort().join(","),
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
  const navigation = useQuery({
    queryKey: ["demo-graph-navigation"],
    enabled: demo,
    staleTime: Infinity,
    queryFn: async () => {
      const response = await fetch(
        `${CONSOLE_BASE_PATH}/demo-api/graph-navigation.json`,
      );
      if (!response.ok)
        throw new Error("Recorded starting points could not be loaded");
      return response.json() as Promise<Record<string, DemoStartingPoint[]>>;
    },
  });
  const data = query.data;
  const recordedRoots = (navigation.data?.[view] ?? []).filter(
    (node) =>
      node.version === data?.version &&
      `${node.label} ${node.id}`
        .toLocaleLowerCase()
        .includes(search.trim().toLocaleLowerCase()),
  );
  const rootCount = demo ? recordedRoots.length : (data?.root_count ?? 0);
  const rootPageOffset = demo
    ? Math.min(rootOffset, Math.max(0, Math.ceil(rootCount / 50) - 1) * 50)
    : (data?.root_offset ?? rootOffset);
  const roots = demo
    ? recordedRoots.slice(rootPageOffset, rootPageOffset + 50)
    : (data?.roots ?? []);
  const nextRootOffset = demo
    ? rootPageOffset + 50 < rootCount
      ? rootPageOffset + 50
      : null
    : (data?.next_root_offset ?? null);
  const currentRoot = data?.root ?? root;
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
  const focusKey = `${params.toString()}:${data?.version ?? ""}`;
  const directId =
    directFocus?.key === focusKey &&
    data?.nodes.some((n) => n.id === directFocus.id)
      ? directFocus.id
      : null;
  const scopeIds = useMemo(() => {
    const scope =
      directId && data
        ? graphScope(data.edges, new Set([directId]), 1)
        : repositoryRoot && repositoryView === "evidence"
          ? evidencePages.ids
          : new Set(data?.nodes.map((node) => node.id));
    return new Set(
      data?.nodes
        .filter((node) => scope.has(node.id) && visible.has(node.kind))
        .map((node) => node.id),
    );
  }, [data, directId, evidencePages, repositoryRoot, repositoryView, visible]);
  const canvasGraph = useMemo(
    () =>
      directId && data
        ? {
            ...data,
            edges: data.edges.filter(
              (e) => e.source === directId || e.target === directId,
            ),
          }
        : repositoryRoot && repositoryView === "evidence" && data
          ? {
              ...data,
              edges: data.edges.filter(
                (edge) =>
                  edge.source === currentRoot || edge.target === currentRoot,
              ),
            }
          : data,
    [data, directId, currentRoot, repositoryRoot, repositoryView],
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
    if (query.isFetching) return;
    setDirectFocus(null);
    if (target.id !== currentRoot) {
      setTrail((current) => [
        ...current,
        {
          id: currentRoot,
          label:
            data?.nodes.find((node) => node.id === currentRoot)?.label ??
            currentRoot,
          depth,
          rootOffset: rootPageOffset,
          safeguardPage,
          repositoryView,
          evidencePage,
          visible: new Set(visible),
          version: data?.version ?? "",
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
    setDirectFocus(null);
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
                  if (demo) setRootOffset(0);
                  else reset();
                }}
                placeholder="Type to filter starting points…"
                aria-label="Find a starting point"
              />
            </label>
            <label className="grid w-full min-w-0 gap-1 text-xs text-muted sm:w-auto sm:flex-1">
              Starting point
              <select
                aria-label="Graph starting point"
                className="ui-input min-w-0"
                value={currentRoot}
                onChange={(e) => {
                  setTrail([]);
                  setRoot(e.target.value);
                  setSafeguardPage({ root: "", framework: "", offset: 0 });
                  setRepositoryView("evidence");
                  setEvidencePage(0);
                  setVersion(data?.version ?? "");
                  setSelected(null);
                }}
              >
                <option value="">Choose a recorded node</option>
                {currentRoot && !roots.some((n) => n.id === currentRoot) && (
                  <option value={currentRoot}>
                    {data?.nodes.find((n) => n.id === currentRoot)?.label ??
                      currentRoot}
                  </option>
                )}
                {roots.map((n) => (
                  <option key={n.id} value={n.id}>
                    {labelWithKind(n.label, n.kind)}
                  </option>
                ))}
              </select>
            </label>
            {data && rootCount > 50 && (
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  aria-label="Previous starting points"
                  disabled={rootPageOffset === 0}
                  onClick={() =>
                    setRootOffset(Math.max(0, rootPageOffset - 50))
                  }
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  aria-label="Next starting points"
                  disabled={nextRootOffset === null}
                  onClick={() => setRootOffset(nextRootOffset!)}
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
          {demo && (
            <p className="text-xs text-muted">
              Searches recorded starting points. Layer filters apply to the
              loaded neighborhood.
              {recordedRoots.length === 0 &&
                " No recorded starting points match this search."}
            </p>
          )}
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
                      if (!demo) setVersion("");
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
        <Button
          onClick={() => {
            reset();
            setView("controls");
            setDepth(2);
            setSearch("");
            setVisible(new Set(layers));
            setSafeguardPage({ root: "", framework: "", offset: 0 });
          }}
        >
          Reset to current evidence
        </Button>
      )}
      <QueryState
        queries={demo ? [query, navigation] : [query]}
        label="investigation graph"
      >
        {data && (
          <>
            {data.root_missing ? (
              <div
                role="status"
                className="grid justify-items-start gap-3 rounded-xl border border-line p-6 text-sm text-muted"
              >
                <p>
                  <b className="text-ink">Starting point not found.</b>{" "}
                  <code className="break-all">{currentRoot}</code> is not in the
                  current evidence. It may have been renamed or removed.
                </p>
                <Button size="sm" onClick={reset}>
                  Reset starting point
                </Button>
              </div>
            ) : data.nodes.length === 0 ? (
              <div className="rounded-xl border border-line p-6 text-sm text-muted">
                No recorded relationships for this selection. Choose another
                starting point or enable its layer. Vendor links require
                explicit source-account and asset IDs.
              </div>
            ) : (
              <section
                ref={workspace}
                aria-label="Graph workspace"
                aria-busy={query.isFetching}
                className={`space-y-3 ${expanded ? "h-screen overflow-auto bg-surface p-4" : ""} ${inlineExpanded ? "fixed inset-0 z-50" : ""}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={!rollupTarget || query.isFetching}
                    onClick={() => {
                      if (!rollupTarget || query.isFetching) return;
                      const previous = trail.at(-1);
                      setRoot(rollupTarget);
                      setRepositoryView(previous?.repositoryView ?? "evidence");
                      setEvidencePage(previous?.evidencePage ?? 0);
                      if (previous) {
                        setDepth(previous.depth);
                        setRootOffset(previous.rootOffset);
                        setSafeguardPage(previous.safeguardPage);
                        setVisible(new Set(previous.visible));
                      }
                      setTrail(trail.slice(0, -1));
                      setSelected(null);
                      setVersion(previous?.version ?? data.version);
                    }}
                  >
                    Roll up
                  </Button>
                  <p
                    aria-label="Current graph path"
                    className="order-first min-w-0 basis-full break-words text-sm font-medium sm:order-none sm:flex-1 sm:basis-auto"
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
                  aria-label="Graph relationship guide"
                  data-testid="graph-column-legend"
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line p-3 text-xs"
                >
                  <dl className="grid gap-1">
                    <div>
                      <dt className="inline font-semibold">
                        Assurance hierarchy:{" "}
                      </dt>
                      <dd className="inline text-muted">
                        Framework → Control → Safeguard · mappings require
                        review
                      </dd>
                    </div>
                    <div>
                      <dt className="inline font-semibold">CCF structure: </dt>
                      <dd className="inline text-muted">
                        Category → Family → Safeguard
                      </dd>
                    </div>
                    <div>
                      <dt className="inline font-semibold">
                        Evidence lineage:{" "}
                      </dt>
                      <dd className="inline text-muted">
                        Source → Observation → Asset · recorded bindings connect
                        the two
                      </dd>
                    </div>
                  </dl>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={relationshipLabels}
                      onChange={(event) =>
                        setRelationshipLabels(event.target.checked)
                      }
                    />
                    Show relationship labels
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {selectedNode && !directId && (
                    <Button
                      size="sm"
                      onClick={() =>
                        setDirectFocus({ id: selectedNode.id, key: focusKey })
                      }
                    >
                      Focus direct relationships
                    </Button>
                  )}
                  {directId && (
                    <>
                      <span className="text-sm font-semibold">
                        Direct relationships only
                      </span>
                      <span
                        aria-label="Direct relationship counts"
                        className="text-xs text-muted"
                      >
                        {scopeIds.size} nodes · {shownEdges} relationships shown
                        ({data.nodes.length} nodes · {data.edges.length}{" "}
                        relationships loaded)
                      </span>
                      <span className="text-xs text-muted">
                        Incoming and outgoing recorded links to{" "}
                        {graphRecordLabel(
                          data.nodes.find((n) => n.id === directId)!,
                        )}
                        .
                      </span>
                      <Button
                        size="sm"
                        onClick={() => {
                          setDirectFocus(null);
                          setRepositoryView("all");
                        }}
                      >
                        Show full neighborhood
                      </Button>
                    </>
                  )}
                </div>
                <div
                  className={`grid items-start gap-3 ${selectedNode ? "xl:grid-cols-[minmax(0,1fr)_360px]" : ""}`}
                >
                  <div className="min-w-0">
                    <GraphCanvas
                      graph={canvasGraph}
                      scopeIds={scopeIds}
                      showEdgeLabels={relationshipLabels}
                      showRelationshipLabels={relationshipLabels}
                      compactCards
                      neighborhoodRoot={
                        !directId &&
                        repositoryRoot &&
                        repositoryView === "evidence"
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
                      rankLimit={8}
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
                      // A record listed on a node but outside this slice
                      // becomes the starting point, then stays selected.
                      if (node && !data?.nodes.some((n) => n.id === node.id))
                        exploreNode(node);
                      else if (node && !scopeIds.has(node.id)) {
                        setDirectFocus(null);
                        setRepositoryView("all");
                      }
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
                  <GraphRelationships
                    graph={data}
                    nodeId={selectedNode?.id ?? currentRoot}
                    onInspect={(node) => {
                      if (!scopeIds.has(node.id)) {
                        setDirectFocus(null);
                        setRepositoryView("all");
                      }
                      setSelected(node);
                    }}
                  />
                </details>
                <p role="status" className="text-xs text-muted">
                  {scopeIds.size === data.nodes.length &&
                  shownEdges === data.edges.length
                    ? `${data.nodes.length} nodes · ${data.edges.length} relationships`
                    : `${scopeIds.size} of ${data.nodes.length} loaded nodes · ${shownEdges} of ${data.edges.length} relationships`}{" "}
                  · {data.boundary}.{" "}
                  {data.truncated
                    ? `${data.matching_nodes} nodes match; showing a bounded subset. Reduce depth or expand a selected node.`
                    : ""}{" "}
                  {demo ? "Recorded demo starting points. " : ""}
                  {rootCount > 50
                    ? `Starting points ${rootPageOffset + 1}–${Math.min(rootPageOffset + 50, rootCount)} of ${rootCount}; search to narrow.`
                    : ""}
                </p>
                <p className="text-xs text-muted">
                  Hover to follow links. Drag to arrange. Click for details.
                  Double-click or press Shift+Enter to explore its connections.
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
                    . Expand the relationship list above for details.
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
