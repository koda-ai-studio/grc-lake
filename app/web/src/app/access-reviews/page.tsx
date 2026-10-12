"use client";

import { useState } from "react";
import Link from "next/link";
import {
  DetailTabs,
  DetailTabList,
  DetailTab,
} from "@/components/ui/detail-tabs";
import { PaginatedCollection } from "@/components/ui/paginated-collection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/PageHeader";
import {
  useAuthWhoami,
  useAccessReview,
  useAccessReviewCoverage,
  useAccessReviewItems,
  useAccessReviews,
  useCreateAccessReviewMutation,
  useDecideAccessReviewItemMutation,
  useSeedAccessReviewMutation,
  useSetAccessReviewStatusMutation,
} from "@/lib/api/hooks";
import type {
  AccessReviewCampaign,
  AccessReviewDecision,
  AccessReviewStatus,
} from "@/lib/api/types";
import { ROUTE_LABELS } from "@/lib/console-copy";
import { QueryState } from "@/components/QueryState";
import { displayLabel } from "@/lib/display";
import { formatDate } from "@/lib/format";

const inputClass =
  "rounded-lg border border-line bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand";

const STATUS_TONE: Record<
  AccessReviewStatus,
  "default" | "info" | "ready" | "attention"
> = {
  draft: "default",
  active: "info",
  completed: "ready",
  cancelled: "default",
};

// draft → active → completed; a campaign advances to the next step.
const NEXT_STATUS: Record<AccessReviewStatus, AccessReviewStatus | null> = {
  draft: "active",
  active: "completed",
  completed: null,
  cancelled: null,
};

const DECISION_TONE: Record<
  AccessReviewDecision,
  "default" | "ready" | "critical" | "attention"
> = {
  pending: "default",
  certified: "ready",
  revoked: "critical",
  flagged: "attention",
};

const DECISIONS: AccessReviewDecision[] = ["certified", "revoked", "flagged"];

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleDateString();
}

function CreateCampaignForm({
  onCreated,
}: {
  onCreated: (id: string) => void;
}) {
  const create = useCreateAccessReviewMutation();
  const canManage =
    useAuthWhoami().data?.scopes.includes("control_manage") === true;
  const [name, setName] = useState("");
  const [scope, setScope] = useState("all");
  const [controlId, setControlId] = useState("");
  const [dueDate, setDueDate] = useState("");

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!canManage || !name.trim()) return;
        create.mutate(
          {
            name: name.trim(),
            scope: scope.trim() || "all",
            control_id: controlId.trim() || null,
            due_at: dueDate ? `${dueDate}T23:59:59Z` : null,
          },
          { onSuccess: (campaign) => onCreated(campaign.id) },
        );
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-muted">
        Campaign name
        <input
          className={inputClass}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Q3 access review"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Scope (connector or all)
        <input
          className={inputClass}
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          placeholder="okta-identity"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Control id (optional)
        <input
          className={inputClass}
          value={controlId}
          onChange={(e) => setControlId(e.target.value)}
          placeholder="SOC2-CC6.1"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Due date (UTC)
        <input
          type="date"
          className={inputClass}
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
        />
      </label>
      {create.error && (
        <p role="alert" className="text-sm text-danger">
          {create.error.message}
        </p>
      )}
      <Button
        type="submit"
        variant="primary"
        disabled={!canManage || create.isPending || !name.trim()}
      >
        {create.isPending ? "Creating…" : "Create campaign"}
      </Button>
    </form>
  );
}

function CampaignRow({
  campaign,
  selected,
  onSelect,
}: {
  campaign: AccessReviewCampaign;
  selected: boolean;
  onSelect: () => void;
}) {
  const setStatus = useSetAccessReviewStatusMutation();
  const canManage =
    useAuthWhoami().data?.scopes.includes("control_manage") === true;
  const next = NEXT_STATUS[campaign.status];
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3 ${
        selected ? "border-brand bg-surfaceMuted" : "border-line bg-surface"
      }`}
    >
      <button
        className="flex flex-col items-start text-left"
        onClick={onSelect}
      >
        <span className="text-sm font-medium text-ink">{campaign.name}</span>
        <span className="text-xs text-muted">
          {campaign.control_id ?? "no control"} · scope {campaign.scope} · due{" "}
          {campaign.due_at
            ? `${formatDate(campaign.due_at.slice(0, 10))} (UTC)`
            : "—"}
        </span>
      </button>
      <div className="flex items-center gap-2">
        <Badge tone={STATUS_TONE[campaign.status]}>
          {displayLabel(campaign.status)}
        </Badge>
        {next && (
          <Button
            size="sm"
            disabled={!canManage || setStatus.isPending}
            onClick={() => setStatus.mutate({ id: campaign.id, status: next })}
          >
            Mark {next}
          </Button>
        )}
      </div>
      {setStatus.error && (
        <p role="alert" className="w-full text-sm text-danger">
          {setStatus.error.message}
        </p>
      )}
    </div>
  );
}

function CampaignDetail({ campaignId }: { campaignId: string }) {
  const identity = useAuthWhoami();
  const humanReviewer = ["session:oidc", "session:saml"].includes(
    identity.data?.auth_method ?? "",
  );
  const canManage = identity.data?.scopes.includes("control_manage") === true;
  const detail = useAccessReview(campaignId);
  const items = useAccessReviewItems(campaignId);
  const seed = useSeedAccessReviewMutation();
  const decide = useDecideAccessReviewItemMutation(campaignId);
  const progress = detail.data?.progress;
  const [query, setQuery] = useState("");
  const [view, setView] = useState("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const visibleItems = (items.data ?? []).filter(
    (item) =>
      (view === "all" ||
        (view === "pending"
          ? item.decision === "pending"
          : item.decision !== "pending")) &&
      `${item.subject_name} ${item.subject_id} ${item.source} ${item.access_summary}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const canSeed =
    canManage && ["draft", "active"].includes(detail.data?.status ?? "");
  const active = detail.data?.status === "active";
  const terminal = ["completed", "cancelled"].includes(
    detail.data?.status ?? "",
  );

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <CardHeader className="p-0">
          <CardTitle>{detail.data?.name ?? "Campaign"}</CardTitle>
        </CardHeader>
        <Button
          size="sm"
          disabled={!canSeed || seed.isPending}
          onClick={() => seed.mutate(campaignId)}
        >
          {seed.isPending ? "Seeding…" : "Seed from evidence"}
        </Button>
      </div>

      {terminal ? (
        <p className="mt-3 text-sm text-muted">
          This campaign is closed; its subjects and decisions cannot be changed.
        </p>
      ) : !active && detail.data ? (
        <p className="mt-3 text-sm text-muted">
          Decisions require an active campaign.
        </p>
      ) : null}
      {!humanReviewer && (
        <p className="mt-3 text-sm text-muted">
          Sign in with OIDC or SAML to record human review decisions.
        </p>
      )}
      {[seed.error, decide.error].filter(Boolean).map((error, index) => (
        <p key={index} role="alert" className="mt-3 text-sm text-danger">
          {error?.message}
        </p>
      ))}
      {progress && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <Badge tone="default">{progress.total} subjects</Badge>
          <Badge tone="ready">{progress.certified} certified</Badge>
          <Badge tone="critical">{progress.revoked} revoked</Badge>
          <Badge tone="attention">{progress.flagged} flagged</Badge>
          <Badge tone="info">{progress.pending} pending</Badge>
        </div>
      )}

      <p className="mt-3 text-sm text-muted">
        Decisions are recorded here; provider access is not changed.
      </p>
      <DetailTabs value={view} onValueChange={setView} className="mt-4">
        <DetailTabList
          label="Review queue"
          items={[
            { value: "all", label: "All subjects" },
            { value: "pending", label: "Pending" },
            { value: "recorded", label: "Recorded decisions" },
          ]}
        />
        <DetailTab value={view}>
          <input
            aria-label="Search review subjects"
            placeholder="Find a person, source or access…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className={`${inputClass} w-full`}
          />
          <QueryState queries={[detail, items]} label="review items">
            <div className="grid gap-2">
              {visibleItems.length ? (
                <PaginatedCollection label="Subjects">
                  {visibleItems.map((item) => (
                    <section
                      key={item.id}
                      className="min-w-0 rounded-lg border border-line"
                    >
                      <button
                        type="button"
                        aria-expanded={expanded === item.id}
                        onClick={() => {
                          setExpanded(expanded === item.id ? null : item.id);
                          setNote("");
                        }}
                        className="flex w-full items-center justify-between gap-3 p-3 text-left focus-visible:ring-2 focus-visible:ring-brand"
                      >
                        <span className="min-w-0">
                          <span className="block break-words text-sm font-semibold text-ink">
                            {item.subject_name || item.subject_id}
                          </span>
                          <span className="text-xs text-muted">
                            {item.source} ·{" "}
                            {expanded === item.id
                              ? "Close review"
                              : "Review access"}
                          </span>
                        </span>
                        <Badge tone={DECISION_TONE[item.decision]}>
                          {displayLabel(item.decision)}
                        </Badge>
                      </button>
                      {expanded === item.id && (
                        <div className="grid gap-5 border-t border-line p-4 [grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr))]">
                          <div className="grid content-start gap-3 text-sm [overflow-wrap:anywhere]">
                            <h3 className="font-semibold">Identity & access</h3>
                            <dl className="grid gap-2">
                              <dt className="text-xs text-muted">Subject ID</dt>
                              <dd>{item.subject_id}</dd>
                              <dt className="text-xs text-muted">
                                Recorded access summary
                              </dt>
                              <dd>
                                {item.access_summary ||
                                  "No access detail was supplied by this source. Inspect evidence before deciding."}
                              </dd>
                            </dl>
                            <Link
                              href="/evidence"
                              className="text-sm font-medium text-brand"
                            >
                              Browse collected evidence →
                            </Link>
                          </div>
                          <div className="grid content-start gap-3 text-sm">
                            <h3 className="font-semibold">Review decision</h3>
                            {item.decision !== "pending" ? (
                              <div className="grid gap-2 text-muted">
                                <p>Recorded decisions cannot be changed.</p>
                                <p>
                                  Reviewer: {item.reviewer || "Not supplied"}
                                </p>
                                <p>
                                  Recorded:{" "}
                                  {item.decided_at
                                    ? formatDate(item.decided_at)
                                    : "Not supplied"}
                                </p>
                                <p className="whitespace-pre-wrap">
                                  {item.note || "No review note."}
                                </p>
                              </div>
                            ) : (
                              <label className="grid gap-2">
                                Decision rationale
                                <textarea
                                  aria-label="Decision rationale"
                                  value={note}
                                  onChange={(e) => setNote(e.target.value)}
                                  rows={3}
                                  className={inputClass}
                                  placeholder="Explain why access is appropriate, should be removed, or needs investigation."
                                />
                              </label>
                            )}
                            <div className="flex flex-wrap gap-2">
                              {DECISIONS.map((d) => (
                                <Button
                                  key={d}
                                  size="sm"
                                  disabled={
                                    decide.isPending ||
                                    !canManage ||
                                    !humanReviewer ||
                                    !active ||
                                    item.decision !== "pending"
                                  }
                                  title={
                                    !humanReviewer
                                      ? "Human SSO sign-in is required to record a decision"
                                      : undefined
                                  }
                                  onClick={() => {
                                    if (
                                      d !== "revoked" ||
                                      window.confirm(
                                        `Record revoked access for ${item.subject_name}? This records the review decision and does not revoke access at the provider.`,
                                      )
                                    )
                                      decide.mutate({
                                        itemId: item.id,
                                        decision: d,
                                        note,
                                      });
                                  }}
                                >
                                  {d}
                                </Button>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                    </section>
                  ))}
                </PaginatedCollection>
              ) : (
                <div className="rounded-lg border border-dashed border-line p-5 text-sm text-muted">
                  {items.data?.length
                    ? "No subjects match this view."
                    : "No subjects yet. Collect identity evidence, then use Seed from evidence to build the review queue."}
                </div>
              )}
            </div>
          </QueryState>
        </DetailTab>
      </DetailTabs>
    </Card>
  );
}

function CoveragePanel() {
  const coverage = useAccessReviewCoverage();

  return (
    <Card className="p-5">
      <CardHeader className="p-0">
        <CardTitle>Control coverage</CardTitle>
      </CardHeader>
      <QueryState queries={coverage} label="access review coverage">
        {!coverage.data?.length && (
          <p className="mt-3 text-sm text-muted">
            No completed access-review coverage yet. Complete a scoped campaign
            with recorded decisions to establish review evidence.
          </p>
        )}
        <div className="mt-3 space-y-2">
          <PaginatedCollection label="Coverage">
            {(coverage.data ?? []).map((row) => (
              <div
                key={row.control_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm"
              >
                <div>
                  <span className="font-medium text-ink">{row.control_id}</span>{" "}
                  <span className="text-xs text-muted">
                    {row.framework ?? ""} · last reviewed{" "}
                    {fmtDate(row.last_completed_at)}
                  </span>
                </div>
                <Badge tone={row.current ? "ready" : "attention"}>
                  {row.current ? "current" : "needs review"}
                </Badge>
              </div>
            ))}
          </PaginatedCollection>
        </div>
      </QueryState>
    </Card>
  );
}

export default function AccessReviewsPage() {
  const campaigns = useAccessReviews();
  const canManage =
    useAuthWhoami().data?.scopes.includes("control_manage") === true;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const selected = selectedId ?? campaigns.data?.[0]?.id;
  const campaignRows = (campaigns.data ?? []).filter((row) =>
    `${row.name} ${row.scope} ${row.status}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <div className="page-shell grid gap-5">
      <PageHeader
        title={ROUTE_LABELS["/access-reviews"]}
        description="Review who has access, record the rationale, and track outstanding decisions."
        actions={
          <Button
            variant="primary"
            disabled={!canManage}
            onClick={() => setCreating((value) => !value)}
          >
            {creating ? "Close campaign form" : "New campaign"}
          </Button>
        }
      />
      {!canManage && (
        <p className="text-sm text-muted">
          Your role can view access reviews. Managing campaigns and decisions
          requires control management permission.
        </p>
      )}
      {creating && (
        <Card className="p-5">
          <CardHeader className="p-0">
            <CardTitle>Define the review scope</CardTitle>
          </CardHeader>
          <div className="mt-4">
            <CreateCampaignForm
              onCreated={(id) => {
                setSelectedId(id);
                setCreating(false);
                setQuery("");
              }}
            />
          </div>
        </Card>
      )}
      <DetailTabs defaultValue="campaigns">
        <DetailTabList
          label="Access review workspace"
          items={[
            { value: "campaigns", label: "Campaigns" },
            { value: "coverage", label: "Control coverage" },
          ]}
        />
        <DetailTab value="campaigns">
          <QueryState queries={campaigns} label="access review campaigns">
            {!campaigns.data?.length ? (
              <Card className="p-6">
                <h2 className="text-lg font-semibold text-ink">
                  Start a user access review
                </h2>
                <p className="mt-2 text-sm text-muted">
                  Decisions are recorded here; provider access is not changed.
                </p>
                <ol className="mt-5 grid gap-4 md:grid-cols-3">
                  <li className="rounded-lg bg-surfaceMuted p-4">
                    <h3 className="font-semibold">1. Collect identities</h3>
                    <p className="mt-2 text-sm text-muted">
                      Connect an identity source and sync the access evidence
                      you intend to review.
                    </p>
                    <Link
                      href="/connectors"
                      className="mt-3 inline-block text-sm font-semibold text-brand"
                    >
                      Connect an identity source
                    </Link>
                  </li>
                  <li className="rounded-lg bg-surfaceMuted p-4">
                    <h3 className="font-semibold">2. Define a campaign</h3>
                    <p className="mt-2 text-sm text-muted">
                      Set scope and due date, seed subjects from evidence, then
                      activate the campaign.
                    </p>
                    <Button
                      size="sm"
                      className="mt-3"
                      disabled={!canManage}
                      onClick={() => setCreating(true)}
                    >
                      Create first campaign
                    </Button>
                  </li>
                  <li className="rounded-lg bg-surfaceMuted p-4">
                    <h3 className="font-semibold">3. Review and record</h3>
                    <p className="mt-2 text-sm text-muted">
                      Human SSO reviewers certify, flag or record a revocation
                      decision with supporting rationale.
                    </p>
                  </li>
                </ol>
              </Card>
            ) : (
              <div className="grid items-start gap-5 xl:grid-cols-[minmax(260px,320px)_minmax(0,1fr)]">
                <section aria-label="Campaign list" className="grid gap-3">
                  <input
                    aria-label="Search campaigns"
                    className={inputClass}
                    placeholder="Find a campaign…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  <PaginatedCollection label="Campaigns">
                    {campaignRows.map((c) => (
                      <CampaignRow
                        key={c.id}
                        campaign={c}
                        selected={c.id === selected}
                        onSelect={() => setSelectedId(c.id)}
                      />
                    ))}
                  </PaginatedCollection>
                </section>
                {selected && (
                  <CampaignDetail key={selected} campaignId={selected} />
                )}
              </div>
            )}
          </QueryState>
        </DetailTab>
        <DetailTab value="coverage">
          <CoveragePanel />
        </DetailTab>
      </DetailTabs>
    </div>
  );
}
