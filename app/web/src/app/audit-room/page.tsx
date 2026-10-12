"use client";

import { formatDateTime } from "@/lib/format";
import Link from "next/link";
import {
  ArrowRight,
  CircleAlert,
  ClipboardCheck,
  FileCheck2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DetailTabs,
  DetailTabList,
  DetailTab,
} from "@/components/ui/detail-tabs";
import { PaginatedCollection } from "@/components/ui/paginated-collection";
import { EvidenceFreshnessSlaPanel } from "@/components/evidence/EvidenceFreshnessSlaPanel";
import { AuditSnapshotTimeline } from "@/components/audit-room/AuditSnapshotTimeline";
import { IngestionLoopStrip } from "@/components/audit-room/IngestionLoopStrip";
import { FrameworkMark } from "@/components/framework/FrameworkMark";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { KpiTile } from "@/components/ui/KpiTile";
import { useAuditReadiness } from "@/lib/api/hooks";
import { ROUTE_LABELS, SCORE_COPY } from "@/lib/console-copy";
import { displayLabel } from "@/lib/display";

const AUDIT_ROOM_TABS = [
  { value: "priorities", label: "Priorities" },
  { value: "coverage", label: "Coverage & scores" },
  { value: "freshness", label: "Freshness" },
  { value: "snapshots", label: "Snapshots" },
  { value: "runs", label: "Runs" },
];

const GAP_CONTEXT: Record<string, { impact: string; action: string }> = {
  failing_controls: {
    impact:
      "Observed tests failed. Review the affected controls and their evidence.",
    action: "Review controls",
  },
  stale_evidence: {
    impact: "Outdated or missing evidence cannot support a current assessment.",
    action: "Review evidence",
  },
  evidence_requests: {
    impact: "Requested proof is still outstanding from owners.",
    action: "Follow up with owners",
  },
  access_review: {
    impact: "No campaign is currently reviewing user access.",
    action: "Plan access review",
  },
  personnel_access_review: {
    impact: "Personnel access still needs a review campaign.",
    action: "Plan access review",
  },
  personnel_pending: {
    impact: "Human access decisions remain outstanding.",
    action: "Review access",
  },
  personnel_idp: {
    impact: "Personnel evidence lacks a connected identity source.",
    action: "Connect identity source",
  },
  connectors: {
    impact: "No evidence source is available to support the assessment.",
    action: "Connect a source",
  },
  auditor_share: {
    impact: "An external reviewer does not yet have a scoped review link.",
    action: "Prepare reviewer access",
  },
  vendor_diligence: {
    impact: "Vendor diligence has not been recorded in this workspace.",
    action: "Review vendors",
  },
  vendor_overdue: {
    impact: "Recorded vendor assessments have passed their due dates.",
    action: "Review overdue vendors",
  },
  vendor_incomplete: {
    impact: "Recorded vendor assessments are incomplete.",
    action: "Complete vendor reviews",
  },
  policy_attestation: {
    impact: "Published policies lack recorded employee acknowledgment.",
    action: "Review acknowledgments",
  },
};

function consoleHref(href: string) {
  return href.startsWith("/console") ? href.replace(/^\/console/, "") : href;
}

export default function AuditRoomPage() {
  const audit = useAuditReadiness();
  const data = audit.data;
  return (
    <div className="page-shell grid gap-5">
      <PageHeader
        title={ROUTE_LABELS["/audit-room"]}
        description="Resolve evidence gaps, review observed scope, and prepare a frozen audit export."
      />
      <QueryState queries={audit} label="audit readiness">
        {data && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
              <div className="flex items-center gap-2">
                <Badge
                  tone={data.state === "audit_ready" ? "ready" : "attention"}
                >
                  {data.state === "needs_work"
                    ? "Needs attention"
                    : data.state === "audit_ready"
                      ? "Audit ready"
                      : displayLabel(data.state)}
                </Badge>
                <span>Observed evidence only · not certification</span>
              </div>
              <span>Evaluated {formatDateTime(data.evaluated_at)}</span>
            </div>
            <DetailTabs defaultValue="priorities">
              <DetailTabList label="Audit room view" items={AUDIT_ROOM_TABS} />
              <DetailTab value="priorities">
                <div
                  className="grid gap-3 sm:grid-cols-3"
                  aria-label="Audit priorities"
                >
                  {[
                    {
                      label: "Failing control tests",
                      value: data.control_tests.failing,
                      href: "/controls",
                      detail: "Review failures and remediation",
                    },
                    {
                      label: "Evidence to refresh",
                      value: data.evidence_freshness?.stale_count ?? "—",
                      href: "/evidence",
                      detail: "Restore current supporting proof",
                    },
                    {
                      label: "Open evidence requests",
                      value: data.evidence_requests.open,
                      href: "/remediation",
                      detail: "Follow up with evidence owners",
                    },
                  ].map((item) => (
                    <Link
                      key={item.label}
                      href={item.href}
                      className="rounded-lg border border-line p-4 hover:bg-surfaceMuted focus-visible:ring-2 focus-visible:ring-brand"
                    >
                      <span className="text-sm text-muted">{item.label}</span>
                      <div className="my-1 text-2xl font-semibold text-ink">
                        {item.value}
                      </div>
                      <span className="text-xs text-muted">{item.detail}</span>
                    </Link>
                  ))}
                </div>
                <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
                  <Card>
                    <CardHeader>
                      <CardTitle>Blocking gaps</CardTitle>
                      <CardDescription>
                        Observed issues and the next action for each.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="grid gap-3">
                      {data.gaps.length ? (
                        <PaginatedCollection label="Audit gaps" pageSize={3}>
                          {data.gaps.map((gap) => {
                            const context = GAP_CONTEXT[gap.id];
                            return (
                              <Link
                                key={gap.id}
                                href={consoleHref(gap.href)}
                                className="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 rounded-lg border border-line p-3 hover:bg-surfaceMuted focus-visible:ring-2 focus-visible:ring-brand"
                              >
                                <CircleAlert
                                  aria-hidden="true"
                                  className="mt-0.5 h-4 w-4 text-serious-fg"
                                />
                                <div className="min-w-0">
                                  <div className="text-sm font-semibold text-ink">
                                    {gap.label}
                                  </div>
                                  <p className="mt-1 text-xs leading-5 text-muted">
                                    {context?.impact ??
                                      "Review the supporting evidence and resolve the recorded gap."}
                                  </p>
                                  <span className="mt-1 block text-xs font-medium text-brand">
                                    {context?.action ?? "Review gap"}
                                  </span>
                                </div>
                                <ArrowRight
                                  aria-hidden="true"
                                  className="mt-0.5 h-4 w-4 text-muted"
                                />
                              </Link>
                            );
                          })}
                        </PaginatedCollection>
                      ) : (
                        <p className="text-sm text-muted">
                          No blocking gaps from the latest assessment. This does
                          not establish complete coverage or certification.
                        </p>
                      )}
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader>
                      <CardTitle>Review scope</CardTitle>
                      <CardDescription>
                        {data.posture.frameworks_total} frameworks in this
                        evaluation.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="grid gap-4">
                      <div
                        className="grid gap-3 max-h-64 overflow-y-auto"
                        aria-label="Evaluated framework scope"
                      >
                        {data.frameworks?.map((row) => (
                          <div
                            key={row.framework}
                            className="flex items-center gap-3"
                          >
                            <FrameworkMark
                              frameworkId={row.framework}
                              fallbackLabel={row.framework}
                              size={32}
                            />
                            <div className="min-w-0 text-sm">
                              <div className="font-medium text-ink">
                                {row.framework}
                              </div>
                              <div className="text-xs text-muted">
                                {row.assessed_controls} of{" "}
                                {row.total_controls ?? "unknown"} controls
                                assessed
                              </div>
                            </div>
                          </div>
                        ))}
                        {!data.frameworks?.length && (
                          <p className="text-sm text-muted">
                            No frameworks evaluated yet.
                          </p>
                        )}
                      </div>
                      <p className="text-xs text-muted">
                        Counts describe the evidence in this workspace;
                        unobserved assets and vendors may be missing.
                      </p>
                      <div className="border-t border-line pt-4">
                        <div className="flex items-center gap-2 text-sm font-semibold">
                          <FileCheck2
                            aria-hidden="true"
                            className="h-4 w-4 text-brand"
                          />{" "}
                          Reviewer handoff
                        </div>
                        <p className="mt-2 text-xs leading-5 text-muted">
                          Review gaps, capture a snapshot, then share the scoped
                          assessment with your reviewer.
                        </p>
                        <Button asChild size="sm" className="mt-3">
                          <Link href="/trust-center">
                            Prepare reviewer access{" "}
                            <ArrowRight
                              aria-hidden="true"
                              className="h-4 w-4"
                            />
                          </Link>
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </DetailTab>
              <DetailTab value="coverage">
                <Card>
                  <CardHeader>
                    <CardTitle>Readiness summary</CardTitle>
                    <CardDescription>
                      Calculation details for the observed assessment.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-5">
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <KpiTile
                        label={SCORE_COPY.auditReadiness.label}
                        value={`${data.audit_score}/100`}
                        detail={`${SCORE_COPY.assessment.label} ${data.posture.score}/100`}
                      />
                      <KpiTile
                        label="Control tests passing"
                        value={`${data.control_tests.passing}/${data.control_tests.total}`}
                        detail={`${data.control_tests.failing} failing`}
                      />
                      <KpiTile
                        label={SCORE_COPY.frameworksReady.label}
                        value={`${data.posture.frameworks_ready} of ${data.posture.frameworks_total}`}
                        detail="Within the evaluated scope"
                      />
                      <KpiTile
                        label="Evidence fresh rate"
                        value={
                          data.evidence_freshness
                            ? `${data.evidence_freshness.fresh_rate_pct}%`
                            : "—"
                        }
                        detail="Observed evidence within its refresh target"
                      />
                    </div>
                    <details className="rounded-lg border border-line p-3">
                      <summary className="cursor-pointer text-sm font-medium">
                        How these scores are calculated
                      </summary>
                      <dl className="mt-3 grid gap-3 text-xs leading-5 text-muted">
                        {[
                          SCORE_COPY.auditReadiness,
                          SCORE_COPY.assessment,
                          SCORE_COPY.frameworksReady,
                        ].map((entry) => (
                          <div key={entry.label}>
                            <dt className="font-semibold text-ink">
                              {entry.label}:
                            </dt>
                            <dd>{entry.definition}</dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                    <div className="flex flex-wrap gap-3 text-sm">
                      <Link className="text-brand" href="/frameworks">
                        Review framework coverage
                      </Link>
                      <Link
                        className="inline-flex items-center gap-1 text-brand"
                        href="/access-reviews"
                      >
                        <ClipboardCheck
                          aria-hidden="true"
                          className="h-4 w-4"
                        />
                        Access reviews
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              </DetailTab>
              <DetailTab value="freshness">
                <EvidenceFreshnessSlaPanel />
              </DetailTab>
              <DetailTab value="snapshots">
                <AuditSnapshotTimeline />
              </DetailTab>
              <DetailTab value="runs">
                <IngestionLoopStrip />
              </DetailTab>
            </DetailTabs>
          </>
        )}
      </QueryState>
    </div>
  );
}
