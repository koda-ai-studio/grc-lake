"use client";

import { useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  ClipboardCopy,
  ExternalLink,
  Loader2,
  Share2,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  DetailTabs,
  DetailTabList,
  DetailTab,
} from "@/components/ui/detail-tabs";
import { PaginatedCollection } from "@/components/ui/paginated-collection";
import { FrameworkMark } from "@/components/framework/FrameworkMark";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/PageHeader";
import {
  useAuthWhoami,
  useCreateTrustShare,
  usePosture,
  useRevokeTrustShare,
  useTrustShares,
} from "@/lib/api/hooks";
import { useAuditorMode } from "@/lib/state/auditor";
import { notify } from "@/lib/toast";
import type { TrustShare } from "@/lib/api/types";
import { formatDateTime, formatRelative, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ROUTE_LABELS } from "@/lib/console-copy";
import { QueryState } from "@/components/QueryState";

const HOURS_OPTIONS = [1, 4, 24, 24 * 7, 24 * 30];

const ACCESS_DEFAULTS = [
  {
    label: "Admin",
    detail: "Users, keys, connectors, workflows, snapshots, and controls.",
  },
  {
    label: "Security admin",
    detail: "Operate evidence sources, workflows, snapshots, and controls.",
  },
  {
    label: "Contributor",
    detail: "Triage, evidence requests, and approved workflow runs.",
  },
  {
    label: "Read only",
    detail: "Internal posture and evidence visibility without mutation.",
  },
  {
    label: "Auditor share",
    detail: "External read-only review with owners and notes redacted.",
  },
];

type ShareAudience = "customer" | "auditor";

// `sensitivity` is the share's sensitivity ceiling; the public trust endpoint
// drops violation and stale-control counts for "public" shares.
const SHARE_AUDIENCES: Array<{
  id: ShareAudience;
  label: string;
  audience: string;
  visibility: string;
  sensitivity: string;
}> = [
  {
    id: "customer",
    label: "Customer trust",
    audience: "Prospects, customers, and partner reviewers",
    visibility:
      "Overall and per-framework readiness with scores. No violation or stale-control counts.",
    sensitivity: "public",
  },
  {
    id: "auditor",
    label: "Auditor review",
    audience: "External auditors and assessors",
    visibility:
      "Everything in customer trust, plus open-violation and stale-control counts.",
    sensitivity: "internal",
  },
];

function audienceLabel(sensitivity: string | null | undefined): string {
  return (sensitivity ?? "public") === "public"
    ? "Customer trust"
    : "Auditor review";
}

function shareUrl(token: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/console/trust/${token}`;
}

function expiryLabel(hours: number): string {
  if (hours === 1) return "1 hour";
  if (hours < 24) return `${hours} hours`;
  return `${hours / 24} day${hours === 24 ? "" : "s"}`;
}

export default function TrustCenterPage() {
  const auditor = useAuditorMode();
  const identity = useAuthWhoami();
  const canShare =
    !auditor && identity.data?.scopes.includes("snapshot") === true;
  const shares = useTrustShares();
  const createShare = useCreateTrustShare();
  const revoke = useRevokeTrustShare();
  const posture = usePosture();
  const [expiresInHours, setExpiresInHours] = useState(24);
  const [audience, setAudience] = useState<ShareAudience>("customer");
  const [createdToken, setCreatedToken] = useState<TrustShare | null>(null);

  const flash = (msg: string) => notify.success(msg);

  const issue = async () => {
    if (!canShare) return;
    try {
      const { share } = await createShare.mutateAsync({
        role: "auditor",
        scope: "posture_full",
        sensitivity_ceiling:
          SHARE_AUDIENCES.find((item) => item.id === audience)?.sensitivity ??
          "public",
        expires_in_hours: expiresInHours,
      });
      setCreatedToken(share);
      flash("Share link created. Copy it now — it is only shown once.");
    } catch (err) {
      flash(`Create share failed: ${(err as Error).message}`);
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      flash("Copied to clipboard.");
    } catch {
      flash("Clipboard not available; select the text manually.");
    }
  };

  const createdUrl = createdToken?.token ? shareUrl(createdToken.token) : "";

  return (
    <div className="page-shell grid gap-4">
      {!canShare && (
        <p className="text-sm text-muted">
          Your role can view shares. Creating or revoking a link requires
          snapshot permission.
        </p>
      )}
      <PageHeader
        title={ROUTE_LABELS["/trust-center"]}
        description="Share a scoped assessment. Control who sees it and when access expires."
        actions={
          posture.data?.assessment_hash ? (
            <Badge
              tone="info"
              className="max-w-[240px]"
              title={posture.data.assessment_hash}
            >
              <ShieldCheck aria-hidden="true" className="mr-1 h-3 w-3" />
              <span className="truncate">
                Assessment ID {posture.data.assessment_hash.slice(0, 12)}…
              </span>
            </Badge>
          ) : undefined
        }
      />

      <DetailTabs defaultValue="share">
        <DetailTabList
          label="Trust center view"
          items={[
            { value: "share", label: "Share report" },
            { value: "active", label: "Active shares" },
          ]}
        />
        <DetailTab
          value="share"
          className="items-start lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]"
        >
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>Share posture with a reviewer</CardTitle>
              <CardDescription>
                Pick who the link is for. Private evidence, owners, and notes
                are never shared.
              </CardDescription>
            </CardHeader>
            <div className="grid gap-4 p-4 pt-0">
              <div
                role="group"
                aria-label="Share audience"
                className="grid gap-2 sm:grid-cols-2"
              >
                {SHARE_AUDIENCES.map((item) => {
                  const selected = audience === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      aria-pressed={selected}
                      disabled={!canShare}
                      onClick={() => setAudience(item.id)}
                      className={cn(
                        "grid min-w-0 content-start gap-1 rounded-xl border p-4 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
                        selected
                          ? "border-brand bg-brand/5 ring-1 ring-brand"
                          : "border-line bg-surface hover:border-brand/40",
                      )}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-base font-semibold text-ink">
                          {item.label}
                        </span>
                        {selected && (
                          <CheckCircle2 className="h-4 w-4 shrink-0 text-brand" />
                        )}
                      </span>
                      <span className="text-sm leading-5 text-muted">
                        {item.audience}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-end gap-3">
                <label className="grid w-full gap-1 text-xs font-semibold uppercase tracking-wide text-muted sm:w-[180px]">
                  Expires in
                  <select
                    aria-label="Share expiry window"
                    value={expiresInHours}
                    onChange={(e) => setExpiresInHours(Number(e.target.value))}
                    className="h-10 rounded-lg border border-line bg-surface px-3 text-sm font-semibold normal-case tracking-normal text-ink focus:outline-none focus:ring-1 focus:ring-brand"
                    disabled={!canShare}
                  >
                    {HOURS_OPTIONS.map((h) => (
                      <option key={h} value={h}>
                        {expiryLabel(h)}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  variant="primary"
                  className="h-10"
                  onClick={issue}
                  disabled={createShare.isPending || !canShare}
                >
                  {createShare.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Share2 className="h-4 w-4" />
                  )}{" "}
                  Issue share
                </Button>
              </div>

              {createdToken && createdUrl && (
                <div className="grid min-w-0 gap-2 rounded-xl border border-success/40 bg-success-bg p-3 text-xs text-success-fg">
                  <div className="flex flex-wrap items-center justify-between gap-2 font-semibold">
                    <span>
                      {audienceLabel(createdToken.sensitivity_ceiling)} link —
                      shown once, copy it now
                    </span>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => copy(createdUrl)}
                      >
                        <ClipboardCopy className="h-3 w-3" /> Copy link
                      </Button>
                      <Button asChild variant="default" size="sm">
                        <a
                          href={createdUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <ExternalLink className="h-3 w-3" /> Open preview
                        </a>
                      </Button>
                    </div>
                  </div>
                  <code className="block break-all rounded bg-surface p-2 font-mono text-[11px] text-ink">
                    {createdUrl}
                  </code>
                  <div>
                    Expires {formatRelative(createdToken.expires_at)} (
                    {formatDateTime(createdToken.expires_at)})
                  </div>
                </div>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Shared scope</CardTitle>
              <CardDescription>
                {
                  SHARE_AUDIENCES.find((item) => item.id === audience)
                    ?.visibility
                }
              </CardDescription>
            </CardHeader>
            <div className="grid gap-4 px-4 pb-4">
              <div
                className="max-h-48 overflow-y-auto grid gap-3"
                aria-label="Report frameworks"
              >
                {(posture.data?.frameworks ?? []).map((row) => (
                  <div
                    key={row.framework}
                    className="flex items-center gap-3 text-sm"
                  >
                    <FrameworkMark frameworkId={row.framework} size={28} />
                    <span>{row.framework}</span>
                  </div>
                ))}
                {!posture.data?.frameworks.length && (
                  <p className="text-sm text-muted">
                    No evaluated frameworks yet.
                  </p>
                )}
              </div>
              <p className="border-t border-line pt-3 text-xs leading-5 text-muted">
                Every link is read-only and expires automatically. Private
                evidence, owners, and notes are never shared. Assessment results
                describe observed evidence, not certification.
              </p>
              <details className="text-sm">
                <summary className="cursor-pointer font-medium">
                  Internal access and roles
                </summary>
                <p className="my-3 text-xs text-muted">
                  Internal teammates sign in with their own role.{" "}
                  <Link
                    href="/auth/#users"
                    className="text-brand hover:underline"
                  >
                    Manage users
                  </Link>
                </p>
                <dl className="grid gap-3">
                  {ACCESS_DEFAULTS.map((item) => (
                    <div key={item.label}>
                      <dt className="text-xs font-semibold">{item.label}</dt>
                      <dd className="mt-1 text-xs text-muted">{item.detail}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </div>
          </Card>
        </DetailTab>
        <DetailTab value="active">
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle>
                {shares.isSuccess
                  ? plural(shares.data.length, "active share")
                  : "Active shares"}
              </CardTitle>
              <CardDescription>
                Revoking a link stops it working immediately and removes it from
                this list. The revocation stays in the audit log.
              </CardDescription>
            </CardHeader>
            <QueryState queries={shares} label="trust shares">
              <div className="grid gap-2 p-5 pt-0">
                {(shares.data ?? []).length === 0 && (
                  <EmptyState icon={Share2}>
                    No active shares. Use Share report to create a reviewer
                    link.
                  </EmptyState>
                )}
                <PaginatedCollection label="Active shares" pageSize={4}>
                  {(shares.data ?? []).map((share) => (
                    <div
                      key={share.share_id}
                      className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl border border-line bg-surface p-3 text-sm"
                    >
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold text-ink">
                            {audienceLabel(share.sensitivity_ceiling)}
                          </span>
                          <Badge tone={share.expired ? "critical" : "ready"}>
                            {share.expired ? "Expired" : "Active"}
                          </Badge>
                        </div>
                        <div className="mt-1 text-xs text-muted">
                          Created by{" "}
                          <b className="text-ink">{share.created_by}</b>{" "}
                          {formatDateTime(share.created_at)} ·{" "}
                          {share.expired ? "expired" : "expires"}{" "}
                          {formatRelative(share.expires_at)}
                        </div>
                        <details className="mt-2 text-xs text-muted [overflow-wrap:anywhere]">
                          <summary className="cursor-pointer">
                            Link details
                          </summary>
                          ID <code className="text-ink">{share.share_id}</code>{" "}
                          · token hash{" "}
                          <code className="text-ink">
                            {share.token_sha256.slice(0, 12)}…
                          </code>
                        </details>
                      </div>
                      <Button
                        variant="default"
                        size="sm"
                        disabled={!canShare || revoke.isPending}
                        onClick={async () => {
                          if (
                            !window.confirm(
                              "Revoke this share link? Anyone using it will lose access.",
                            )
                          )
                            return;
                          try {
                            await revoke.mutateAsync(share.share_id);
                            flash("Share link revoked.");
                          } catch (err) {
                            flash(`Revoke failed: ${(err as Error).message}`);
                          }
                        }}
                      >
                        <XCircle className="h-3 w-3" /> Revoke
                      </Button>
                    </div>
                  ))}
                </PaginatedCollection>
              </div>
            </QueryState>
          </Card>
        </DetailTab>
      </DetailTabs>
    </div>
  );
}
