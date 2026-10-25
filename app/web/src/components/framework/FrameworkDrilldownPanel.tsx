"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Plug,
  Search,
} from "lucide-react";
import Link from "next/link";
import {
  DetailTabs,
  DetailTabList,
  DetailTab,
} from "@/components/ui/detail-tabs";
import { ListPagination } from "@/components/ui/list-pagination";
import { Badge } from "@/components/ui/badge";
import { useFrameworkDetail } from "@/lib/api/hooks";
import type {
  FrameworkConnectorHint,
  FrameworkControlDetail,
  FrameworkSourceRollup,
} from "@/lib/api/types";
import { RequirementGapPanel } from "@/components/framework/RequirementGapPanel";
import { FrameworkEvidenceChain } from "@/components/framework/FrameworkEvidenceChain";
import { cn } from "@/lib/utils";
import {
  CcfAttestationNote,
  ControlResultBadge,
} from "@/components/controls/ControlResult";
import { attestedHeadline } from "@/lib/control-attestation";
import { displayLabel } from "@/lib/display";

type StatusFilter = "all" | "pass" | "fail" | "not_evaluated";

function SourcePills({ sources }: { sources: FrameworkSourceRollup[] }) {
  if (sources.length === 0) {
    return (
      <span className="text-xs text-muted">No evidence sources observed.</span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {sources.slice(0, 6).map((source) => (
        <Badge
          key={source.source}
          tone={source.expired_count ? "critical" : "info"}
        >
          {source.source} · {source.event_count}
        </Badge>
      ))}
      {sources.length > 6 && <Badge>+{sources.length - 6} more</Badge>}
    </div>
  );
}

function ConnectorHintPills({ hints }: { hints: FrameworkConnectorHint[] }) {
  if (hints.length === 0) {
    return (
      <span className="text-xs text-muted">
        No connector mapping for this control yet.
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {hints.map((hint) => (
        <Link
          key={hint.connector_id}
          href={`/connectors/?connect=${encodeURIComponent(hint.connector_id)}`}
          className="inline-flex"
        >
          <Badge tone={hint.configured ? "ready" : "attention"}>
            <Plug className="mr-1 inline h-3 w-3" />
            {hint.name}
            {hint.configured ? " · configured" : " · connect"}
          </Badge>
        </Link>
      ))}
    </div>
  );
}

function ControlRow({
  control,
  frameworkId,
  expanded,
  onToggle,
}: {
  control: FrameworkControlDetail;
  frameworkId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <section
      id={`control-${control.control_id}`}
      className={cn(
        "rounded-xl border border-line bg-surface transition-shadow",
        expanded && "shadow-card",
        control.posture.status === "fail" &&
          !expanded &&
          "border-l-4 border-l-danger",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-3 p-3 text-left"
        aria-expanded={expanded}
      >
        <div className="min-w-0">
          <code className="text-xs font-semibold text-brand">
            {control.control_id}
          </code>
          <div className="mt-1 font-semibold leading-snug text-ink">
            {control.title}
          </div>
          <div className="mt-1 text-xs text-muted">
            {control.owner} · {control.evidence.count}{" "}
            {control.evidence.count === 1 ? "fact" : "facts"} ·{" "}
            {control.evidence.sources.length} source
            {control.evidence.sources.length === 1 ? "" : "s"}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ControlResultBadge status={control.posture.status} ccf={control} />
          {expanded ? (
            <ChevronUp className="h-4 w-4 text-muted" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-line px-3 pb-3 pt-2">
          <DetailTabs defaultValue="assessment">
            <DetailTabList
              label="Requirement detail"
              items={[
                { value: "assessment", label: "Assessment" },
                { value: "evidence", label: "Evidence" },
                { value: "sources", label: "Sources" },
              ]}
            />
            <DetailTab value="assessment">
              <p className="text-sm leading-relaxed text-muted">
                {control.evidence_requirement}
              </p>
              <CcfAttestationNote ccf={control} frameworkId={frameworkId} />
              <RequirementGapPanel
                key={`${frameworkId}:${control.control_id}`}
                frameworkId={frameworkId}
                controlId={control.control_id}
              />
            </DetailTab>
            <DetailTab value="evidence">
              <FrameworkEvidenceChain
                control={control}
                frameworkId={frameworkId}
              />
              <div className="grid gap-3">
                <div className="rounded-lg bg-surfaceMuted p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                    Requirement
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    {control.evidence_requirement}
                  </p>
                  {control.posture.rule_reasons.length > 0 && (
                    <ul className="mt-2 space-y-1 text-xs text-danger-fg">
                      {control.posture.rule_reasons.map((reason) => (
                        <li key={reason}>• {reason}</li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="rounded-lg bg-surfaceMuted p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                    Evidence + test state
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge>{displayLabel(control.test.result)}</Badge>
                    <Badge
                      tone={
                        control.test.freshness_status === "expired"
                          ? "critical"
                          : "info"
                      }
                    >
                      {displayLabel(
                        control.test.freshness_status ?? "not_evaluated",
                      )}
                    </Badge>
                    <Badge>
                      {control.test.confidence_score ?? 0}% confidence
                    </Badge>
                  </div>
                  <div className="mt-2 text-xs text-muted">
                    Required:{" "}
                    {control.test.required_evidence_types.join(", ") || "—"}
                  </div>
                  <div className="mt-2">
                    <SourcePills sources={control.evidence.sources} />
                  </div>
                </div>
              </div>
            </DetailTab>
            <DetailTab value="sources">
              <div className="rounded-lg border border-line p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                  Recommended connectors
                </div>
                <p className="mt-1 text-xs text-muted">
                  {control.connector_hints[0]?.rationale ??
                    "Enable connectors that collect evidence for this control family."}
                </p>
                <div className="mt-2">
                  <ConnectorHintPills hints={control.connector_hints} />
                </div>
              </div>

              <div className="rounded-lg border border-line p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                  Source article mapping
                </div>
                {control.articles.length === 0 ? (
                  <p className="mt-1 text-xs text-muted">
                    No source article mapping.
                  </p>
                ) : (
                  <div className="mt-2 grid gap-2">
                    {control.articles.map((article) => (
                      <a
                        key={`${control.control_id}-${article.article_id}`}
                        href={article.official_source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-lg border border-line p-2 text-xs hover:border-brand"
                      >
                        <span className="font-semibold text-ink">
                          {article.article_id}
                        </span>{" "}
                        <span className="text-muted">{article.title}</span>
                        <ExternalLink className="ml-1 inline h-3 w-3 text-brand" />
                        <div className="mt-1 text-[11px] text-muted">
                          {article.review_status &&
                          article.review_status !== "reviewed" ? (
                            <>
                              <Badge tone="attention">
                                {displayLabel(article.review_status)}
                              </Badge>{" "}
                              Source reconciled by{" "}
                              {article.source_reconciled_by ??
                                article.reviewed_by ??
                                "unknown"}
                              ; awaiting human review
                            </>
                          ) : (
                            <>
                              Reviewed by {article.reviewed_by} on{" "}
                              {article.reviewed_at}
                            </>
                          )}
                        </div>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </DetailTab>
          </DetailTabs>
        </div>
      )}
    </section>
  );
}

export function FrameworkDrilldownPanel({
  frameworkId,
  expandedControlId,
  onExpandedControlChange,
}: {
  frameworkId: string;
  expandedControlId?: string | null;
  onExpandedControlChange?: (controlId: string | null) => void;
}) {
  const detail = useFrameworkDetail(frameworkId);
  const data = detail.data;
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 8;
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [localExpanded, setLocalExpanded] = useState<string | null>(null);

  const expandedId = expandedControlId ?? localExpanded;

  const filteredControls = useMemo(() => {
    if (!data) return [];
    return data.controls.filter((control) => {
      if (statusFilter !== "all" && control.posture.status !== statusFilter) {
        return false;
      }
      if (!query.trim()) return true;
      const haystack = [
        control.control_id,
        control.title,
        control.evaluation_rule,
        control.evidence_requirement,
        control.owner,
        ...control.evidence.sources.map((source) => source.source),
        ...control.connector_hints.map((hint) => hint.name),
        ...control.connector_hints.map((hint) => hint.connector_id),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query.trim().toLowerCase());
    });
  }, [data, query, statusFilter]);

  const setExpanded = (controlId: string | null) => {
    onExpandedControlChange?.(controlId);
    setLocalExpanded(controlId);
  };

  useEffect(() => {
    if (!expandedId) return;
    const index = filteredControls.findIndex(
      (control) => control.control_id === expandedId,
    );
    if (index >= 0) setPage(Math.floor(index / pageSize));
  }, [expandedId, filteredControls]);
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(filteredControls.length / pageSize) - 1),
  );

  if (detail.isLoading) {
    return (
      <div className="rounded-lg border border-dashed border-line p-3 text-xs text-muted">
        Loading framework chain…
      </div>
    );
  }

  if (detail.isError) {
    return (
      <div className="rounded-lg border border-danger/40 bg-danger-bg p-3 text-xs text-danger-fg">
        Framework detail could not be loaded.
      </div>
    );
  }

  if (!data) return null;
  const attested = data.summary.attested_pass_count ?? 0;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">
            Control-to-evidence drill-down
          </div>
          <p className="mt-1 text-xs text-muted">
            Control → rule → evidence → datasource chain for each mapped
            requirement.
          </p>
        </div>
        <div className="grid justify-items-end gap-1">
          <Badge
            tone={
              data.summary.failing_control_count
                ? "critical"
                : data.summary.control_count > 0 &&
                    attested === data.summary.control_count
                  ? "ready"
                  : "default"
            }
          >
            {attested}/{data.summary.control_count} attested
          </Badge>
          <span className="text-[11px] text-muted">
            {attestedHeadline(data.summary.passing_control_count, attested)}
          </span>
        </div>
      </div>

      <div className="grid gap-2 rounded-lg border border-line bg-surface p-2.5 md:grid-cols-[minmax(180px,1fr)_minmax(140px,180px)]">
        <div className="relative min-w-0">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
            aria-label="Search controls"
            placeholder="Search controls, rules, sources…"
            className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value as StatusFilter);
            setPage(0);
          }}
          aria-label="Control status"
          className="min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-semibold focus:outline-none focus:ring-1 focus:ring-brand"
        >
          <option value="all">All statuses</option>
          <option value="pass">Control test passing</option>
          <option value="fail">Control test failing</option>
          <option value="not_evaluated">Not evaluated</option>
        </select>
      </div>

      <div className="grid gap-2">
        {filteredControls
          .slice(currentPage * pageSize, (currentPage + 1) * pageSize)
          .map((control) => (
            <ControlRow
              key={control.control_id}
              control={control}
              frameworkId={frameworkId}
              expanded={expandedId === control.control_id}
              onToggle={() =>
                setExpanded(
                  expandedId === control.control_id ? null : control.control_id,
                )
              }
            />
          ))}
        {filteredControls.length === 0 && (
          <div className="rounded-lg border border-dashed border-line p-4 text-center text-sm text-muted">
            No controls match the current filters.
          </div>
        )}
      </div>
      <ListPagination
        label="Controls"
        page={currentPage}
        total={filteredControls.length}
        pageSize={pageSize}
        onPage={(next) => {
          setExpanded(null);
          setPage(next);
        }}
      />
    </>
  );
}
