"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { ConnectorDrawer } from "@/components/drawers/ConnectorDrawer";
import { ConnectorMark } from "@/components/connectors/ConnectorMark";
import { ListPagination } from "@/components/ui/list-pagination";
import { EvidencePathPanel } from "@/components/connectors/EvidencePathPanel";
import { OnboardingGuideBanner } from "@/components/onboarding/OnboardingGuideBanner";
import { connectorNotify } from "@/lib/connector-notify";
import { CONNECT_FLOW, PREVIEW_COPY, ROUTE_LABELS } from "@/lib/console-copy";
import { connectionReadiness } from "@/lib/connection-readiness";
import { OrganizationScopes } from "@/components/connectors/OrganizationScopes";
import { NamedConnectionCreate } from "@/components/connectors/NamedConnectionCreate";
import { ConnectionProgressPanel } from "@/components/connectors/ConnectionProgressPanel";
import { PreviewBadge } from "@/components/ui/preview-badge";
import { useConnectors } from "@/lib/api/hooks";
import type { ConnectorView } from "@/lib/api/types";

const isRunnableConnector = (connector: ConnectorView) =>
  Boolean(connector.is_implemented);

type ViewFilter = "all" | "connected" | "setup" | "attention";
type CategoryFilter = "all" | "cloud" | "identity" | "data" | "dev" | "ops";

const VIEW_TABS: Array<{ id: ViewFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "connected", label: "Enabled" },
  { id: "setup", label: "Needs setup" },
  { id: "attention", label: "Needs attention" },
];

const CATEGORY_OPTIONS: Array<{ id: CategoryFilter; label: string }> = [
  { id: "all", label: "All categories" },
  { id: "cloud", label: "Cloud" },
  { id: "identity", label: "Identity" },
  { id: "data", label: "Data lakes" },
  { id: "dev", label: "Dev tools" },
  { id: "ops", label: "Ops" },
];

function connectorCategory(connector: ConnectorView): CategoryFilter {
  if (connector.category === "cloud") return "cloud";
  if (connector.category === "identity") return "identity";
  if (connector.category === "developer_platform") return "dev";
  if (
    connector.category === "analytics_lake" ||
    connector.category === "warehouse" ||
    connector.category === "evidence_store" ||
    connector.category === "starter_mode"
  ) {
    return "data";
  }
  return "ops";
}

function needsAttention(connector: ConnectorView) {
  return connectionReadiness(connector).attention;
}

function ConnectorRow({
  connector,
  onSelect,
}: {
  connector: ConnectorView;
  onSelect: () => void;
}) {
  const progress = connectionReadiness(connector);
  const runnable = isRunnableConnector(connector);
  const preview = connector.release_stage === "preview";
  return (
    <div
      className={`relative grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-3 overflow-hidden rounded-lg border bg-surface p-3 text-left transition-colors focus-within:border-brand hover:border-brand hover:shadow-card ${
        runnable
          ? "border-line"
          : "border-dashed border-warning/40 bg-warning-bg "
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-label={`Open ${connector.name}`}
        className="absolute inset-0 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand"
      />
      <span className="pointer-events-none grid h-10 w-10 shrink-0 place-items-center rounded-lg">
        <ConnectorMark
          connectorId={connector.connector_id}
          name={connector.name}
          category={connector.category}
          size="md"
        />
      </span>
      <span className="pointer-events-none min-w-0 overflow-hidden">
        <span className="block truncate font-semibold text-ink">
          {connector.name}
        </span>
        {connector.source_account_id && (
          <span
            className="block truncate text-xs text-muted"
            title={connector.source_account_id}
          >
            {connector.source_account_id}
          </span>
        )}
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <Badge tone={progress.tone}>{progress.label}</Badge>
          {preview ? (
            <PreviewBadge className="pointer-events-auto relative z-10" />
          ) : null}
        </span>
        <span className="mt-1 line-clamp-2 text-xs leading-5 text-muted">
          {connector.state === "disabled" && !connector.last_probe
            ? (connector.setup_hint ?? progress.detail)
            : progress.detail}
        </span>
      </span>
      <span className="pointer-events-none col-start-2 text-xs font-semibold text-brand">
        {progress.action} →
      </span>
    </div>
  );
}

export default function ConnectorsPage() {
  const connectors = useConnectors();
  const [connectId, setConnectId] = useState<string | null>(null);
  const [linkSessionId, setLinkSessionId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 6;
  const [viewFilter, setViewFilter] = useState<ViewFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [selected, setSelected] = useState<ConnectorView | null>(null);
  const [onboarding, setOnboarding] = useState(false);

  const data = useMemo(() => connectors.data ?? [], [connectors.data]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    setConnectId(params.get("connect"));
    setLinkSessionId(params.get("link_session"));
    setOnboarding(params.get("onboarding") === "1");
  }, []);

  useEffect(() => {
    if (!connectId || data.length === 0) return;
    const match = data.find((c) => c.connector_id === connectId);
    if (match) setSelected(match);
  }, [connectId, data]);

  useEffect(() => {
    if (!onboarding || !connectId) return;
    document.getElementById("connector-drawer-anchor")?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, [onboarding, connectId, selected]);

  const filtered = useMemo(
    () =>
      data.filter((c) => {
        if (!isRunnableConnector(c)) return false;
        if (viewFilter === "connected" && c.state !== "enabled") return false;
        if (viewFilter === "setup" && c.state === "enabled") return false;
        if (viewFilter === "attention" && !needsAttention(c)) return false;
        if (categoryFilter !== "all" && connectorCategory(c) !== categoryFilter)
          return false;
        if (!query) return true;
        return JSON.stringify(c).toLowerCase().includes(query.toLowerCase());
      }),
    [categoryFilter, data, query, viewFilter],
  );

  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(filtered.length / pageSize) - 1),
  );

  const totals = {
    enabled: data.filter((c) => c.state === "enabled").length,
    unhealthy: data.filter((c) => isRunnableConnector(c) && needsAttention(c))
      .length,
  };

  const selectedLive = selected
    ? (data.find(
        (c) =>
          c.connector_id === selected.connector_id &&
          c.connection_id === selected.connection_id,
      ) ?? selected)
    : null;

  const clearDeepLinkParams = () => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (
      !url.searchParams.has("connect") &&
      !url.searchParams.has("link_session")
    ) {
      return;
    }
    url.searchParams.delete("connect");
    url.searchParams.delete("link_session");
    const next = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState({}, "", next);
    setConnectId(null);
    setLinkSessionId(null);
  };

  return (
    <div className="page-shell grid gap-2">
      {onboarding && (
        <OnboardingGuideBanner
          step={1}
          title="Connect a read-only source"
          detail="Pick a connector, test access, enable, then sync evidence — the same probe → enable → sync loop as MCP and CI."
        />
      )}
      <PageHeader
        title={ROUTE_LABELS["/connectors"]}
        description="Connect a source, test access, then sync evidence."
        actions={
          totals.unhealthy > 0 ? (
            <span className="rounded-full border border-danger/40 bg-danger-bg px-3 py-1.5 text-xs font-semibold text-danger-fg">
              {totals.unhealthy} need attention
            </span>
          ) : null
        }
      />

      {connectors.isSuccess && (
        <ConnectionProgressPanel connectors={data} onSelect={setSelected} />
      )}
      <OrganizationScopes connectors={data} />
      <NamedConnectionCreate connectors={data} onToast={connectorNotify} />
      <EvidencePathPanel connectors={connectors.data ?? []} />

      <div className="grid min-w-0 gap-2 overflow-hidden rounded-lg border border-line bg-surface p-2 shadow-card">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="relative min-w-[min(100%,260px)] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
              }}
              aria-label="Search sources"
              placeholder="Search sources..."
              className="w-full rounded-lg border border-line bg-surface py-2.5 pl-10 pr-3 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
            />
          </div>
          <div
            aria-label="Connection view"
            className="flex max-w-full gap-1 overflow-x-auto rounded-lg border border-line bg-panel p-1"
            role="tablist"
          >
            {VIEW_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={viewFilter === tab.id}
                className={`shrink-0 rounded-md px-3 py-2 text-xs font-semibold ${
                  viewFilter === tab.id
                    ? "bg-surface text-ink shadow-card ring-1 ring-line"
                    : "text-muted hover:bg-surface"
                }`}
                onClick={() => {
                  setViewFilter(tab.id);
                  setPage(0);
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <label className="sr-only" htmlFor="connector-category-filter">
            Category
          </label>
          <select
            id="connector-category-filter"
            aria-label="Category filter"
            value={categoryFilter}
            onChange={(event) => {
              setCategoryFilter(event.target.value as CategoryFilter);
              setPage(0);
            }}
            className="min-w-[150px] rounded-lg border border-line bg-panel px-3 py-2.5 text-xs font-semibold text-ink focus:outline-none focus:ring-1 focus:ring-brand"
          >
            {CATEGORY_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <p className="px-1 text-xs text-muted">
          <span className="font-semibold text-ink">{PREVIEW_COPY.label}</span>:{" "}
          {PREVIEW_COPY.definition}
        </p>
      </div>

      <QueryState queries={connectors} label="connectors">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{filtered.length} sources</CardTitle>
            <CardDescription>
              Pick a source to configure or review.
            </CardDescription>
          </CardHeader>
          <div className="grid gap-2 p-3 pt-0 md:grid-cols-2 xl:grid-cols-3">
            {filtered.length === 0 && (
              <div className="rounded-lg border border-dashed border-line p-4 text-sm text-muted">
                {totals.enabled === 0 ? (
                  <div className="grid gap-3">
                    <p>{CONNECT_FLOW.emptySources}</p>
                    <Button asChild size="sm" className="w-fit">
                      <Link href="/onboarding">Open setup guide</Link>
                    </Button>
                  </div>
                ) : (
                  "No connectors match the current filter."
                )}
              </div>
            )}
            {filtered
              .slice(currentPage * pageSize, (currentPage + 1) * pageSize)
              .map((c) => (
                <ConnectorRow
                  key={c.connection_id ?? c.connector_id}
                  connector={c}
                  onSelect={() => setSelected(c)}
                />
              ))}
          </div>
          <div className="px-4 pb-4">
            <ListPagination
              label="Sources"
              page={currentPage}
              total={filtered.length}
              pageSize={pageSize}
              onPage={setPage}
            />
          </div>
        </Card>
      </QueryState>

      <div id="connector-drawer-anchor" />
      <ConnectorDrawer
        key={
          selectedLive?.connection_id ?? selectedLive?.connector_id ?? "closed"
        }
        connector={selectedLive}
        linkSessionId={linkSessionId}
        onboarding={onboarding}
        onClose={() => {
          setSelected(null);
          clearDeepLinkParams();
        }}
        onToast={connectorNotify}
      />
    </div>
  );
}
