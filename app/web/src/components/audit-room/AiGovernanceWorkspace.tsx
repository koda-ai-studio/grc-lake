"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  BrainCircuit,
  ChevronDown,
  FileText,
  GitBranch,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { InfoHint } from "@/components/ui/info-hint";
import { FrameworkMark } from "@/components/framework/FrameworkMark";
import { QueryState } from "@/components/QueryState";
import { useAiGovernance, useAiInventory } from "@/lib/api/hooks";
import type { AiInventoryItem } from "@/lib/api/types";
import { assetLabel, formatDateTime } from "@/lib/format";
import { displayLabel } from "@/lib/display";
import { SCORE_COPY } from "@/lib/console-copy";
import { readinessCoverage } from "@/lib/readiness-coverage";
import { aiFrameworkDetail, aiFrameworkSummary } from "./AiGovernanceStrip";

function isAgent(item: AiInventoryItem): boolean {
  return item.asset_type === "ai_agent" || item.asset_type === "agent";
}

function inventoryKey(item: AiInventoryItem): string {
  return JSON.stringify([item.source_account_id ?? "", item.asset_id]);
}

function nextStep(item: AiInventoryItem): string {
  if (isAgent(item))
    return item.event_types.includes("runtime.tool_call")
      ? "Review tool activity"
      : "Collect runtime evidence";
  if (!item.model_card) return "Collect model card";
  if (!item.lineage_complete) return "Review model lineage";
  return "Review linked controls";
}

function InventoryRow({ item }: { item: AiInventoryItem }) {
  const [open, setOpen] = useState(false);
  const name = assetLabel(item);
  const detailId = `ai-detail-${encodeURIComponent(inventoryKey(item))}`;
  const agent = isAgent(item);
  const recordedLineage =
    item.lineage_complete || item.event_types.includes("model.lineage");
  const runtime = item.event_types.includes("runtime.tool_call");
  const Icon = agent ? Bot : BrainCircuit;
  return (
    <li className="border-t border-line first:border-t-0">
      <div className="grid items-center gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <div className="flex min-w-0 items-start gap-3">
          <span className="rounded-lg bg-brand/10 p-2 text-brand">
            <Icon aria-hidden="true" className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold [overflow-wrap:anywhere]">
              {name}
            </h3>
            <p className="mt-1 text-xs text-muted [overflow-wrap:anywhere]">
              {item.owner || "Owner not assigned"} ·{" "}
              {item.environment || "Environment unknown"}
            </p>
            <p className="mt-1 text-xs text-muted [overflow-wrap:anywhere]">
              Source account: {item.source_account_id || "Not recorded"}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          {agent ? (
            <Badge tone={runtime ? "default" : "attention"}>
              {runtime ? "Runtime recorded" : "Runtime not observed"}
            </Badge>
          ) : (
            <Badge tone={item.model_card ? "default" : "attention"}>
              {item.model_card
                ? "Model card recorded"
                : "Model card not observed"}
            </Badge>
          )}
          <Badge tone="default">
            {item.lineage_complete
              ? "Lineage complete"
              : recordedLineage
                ? "Lineage recorded"
                : "Lineage not observed"}
          </Badge>
        </div>
        <button
          type="button"
          aria-label={`Inspect ${name}`}
          aria-expanded={open}
          aria-controls={detailId}
          onClick={() => setOpen(!open)}
          className="inline-flex items-center justify-self-start gap-1 rounded-md px-2 py-2 text-xs font-semibold text-brand hover:bg-brand/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
        >
          Inspect{" "}
          <ChevronDown
            aria-hidden="true"
            className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
      </div>
      <p className="-mt-1 px-4 pb-3 text-xs text-muted sm:pl-[60px]">
        Next: <span className="font-medium text-ink">{nextStep(item)}</span>
      </p>
      {open && (
        <section
          id={detailId}
          aria-label={`${name} details`}
          className="mx-4 mb-4 grid gap-4 rounded-lg border border-line bg-surfaceMuted p-4"
        >
          <div>
            <h4 className="text-sm font-semibold">{nextStep(item)}</h4>
            <p className="mt-1 text-xs leading-5 text-muted">
              {agent
                ? runtime
                  ? "Review the recorded tools, permissions and outcomes before assessing agent behavior."
                  : "Runtime evidence is needed to inspect tool use and permissions. Connect the agent activity source if this agent is in scope."
                : !item.model_card
                  ? "Purpose, limitations and intended use belong in a model card. No model-card signal was collected for this asset; the document may exist elsewhere. Ask the owner for the card and collect its evidence, then review the linked controls."
                  : !item.lineage_complete
                    ? "Check the recorded inputs, transformations and model version. A lineage event alone does not establish complete traceability."
                    : "Documentation and lineage signals are present. Review the evidence and current control results before drawing an assurance conclusion."}
            </p>
          </div>
          <div className="grid gap-3 text-xs sm:grid-cols-2">
            <div>
              <p className="font-semibold">Recorded sources</p>
              <p className="mt-1 text-muted">
                {item.sources.map(displayLabel).join(", ") || "Source unknown"}
              </p>
              <p className="mt-1 text-muted">
                Observed {formatDateTime(item.last_seen_at)}
              </p>
            </div>
            <div>
              <p className="font-semibold">Linked controls</p>
              <div className="mt-1 flex flex-wrap gap-2">
                {item.control_ids.length ? (
                  item.control_ids.map((id) => (
                    <Link
                      key={id}
                      href={`/controls/?id=${encodeURIComponent(id)}`}
                      className="font-medium text-brand hover:underline"
                    >
                      {id}
                    </Link>
                  ))
                ) : (
                  <span className="text-muted">
                    No control binding recorded
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            <p className="text-xs text-muted">
              {item.lineage_complete
                ? "Lineage complete"
                : recordedLineage
                  ? "Lineage recorded; completeness not established"
                  : "Lineage not observed"}
              . Evidence presence is not a control verdict.
            </p>
            <Link
              href={`/evidence/?asset=${encodeURIComponent(item.asset_id)}${item.source_account_id !== undefined ? `&account=${encodeURIComponent(item.source_account_id)}` : ""}`}
              className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-brand hover:underline"
            >
              {agent ? "View agent evidence" : "View model evidence"}{" "}
              <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
            </Link>
          </div>
        </section>
      )}
    </li>
  );
}

export function AiGovernanceWorkspace() {
  const governance = useAiGovernance();
  const inventory = useAiInventory(50);
  const [filter, setFilter] = useState<"all" | "documentation" | "agents">(
    "all",
  );
  const items = inventory.data ?? [];
  const visible = items.filter(
    (item) =>
      filter === "all" ||
      (filter === "agents"
        ? isAgent(item)
        : !isAgent(item) && !item.model_card),
  );
  const data = governance.data;
  return (
    <QueryState queries={[governance, inventory]} label="AI governance">
      {data && (
        <div data-testid="ai-governance-strip" className="grid gap-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <Card>
              <CardContent className="flex items-start gap-3 p-4">
                <BrainCircuit
                  aria-hidden="true"
                  className="mt-1 h-5 w-5 text-brand"
                />
                <div>
                  <p className="text-xs font-medium text-muted">
                    Observed inventory
                  </p>
                  <p className="mt-1 text-2xl font-semibold">
                    {data.inventory.models}{" "}
                    <span className="text-sm font-normal text-muted">
                      models · {data.inventory.agents} agents
                    </span>
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    From connected evidence sources
                  </p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-start gap-3 p-4">
                <FileText
                  aria-hidden="true"
                  className="mt-1 h-5 w-5 text-brand"
                />
                <div>
                  <p className="text-xs font-medium text-muted">
                    Documented assets
                  </p>
                  <p className="mt-1 text-2xl font-semibold">
                    {data.inventory.with_model_card}
                    <span className="text-sm font-normal text-muted">
                      {" "}
                      / {data.inventory.total} with a model card
                    </span>
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    Purpose, intended use and limitations
                  </p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-start gap-3 p-4">
                <GitBranch
                  aria-hidden="true"
                  className="mt-1 h-5 w-5 text-brand"
                />
                <div>
                  <p className="text-xs font-medium text-muted">
                    Lineage evidence
                  </p>
                  <p className="mt-1 text-2xl font-semibold">
                    {data.events.model_lineage}
                    <span className="text-sm font-normal text-muted">
                      {" "}
                      recorded signals
                    </span>
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    Inspect each model for traceability
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(300px,1fr)]">
            <section
              aria-label="Models and agents"
              className="min-w-0 overflow-hidden rounded-xl border border-line bg-surface shadow-card"
            >
              <div className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div>
                  <h2 className="text-base font-semibold">Models and agents</h2>
                  <p className="mt-1 text-xs text-muted">
                    {items.length} shown
                    {data.inventory.total > items.length
                      ? ` of ${data.inventory.total} observed assets`
                      : ""}{" "}
                    · evidence gaps and next steps
                  </p>
                </div>
                <label className="text-xs text-muted">
                  <span className="sr-only">Filter AI inventory</span>
                  <select
                    value={filter}
                    onChange={(e) => setFilter(e.target.value as typeof filter)}
                    className="rounded-md border border-line bg-surface px-2 py-2 text-ink"
                  >
                    <option value="all">All assets</option>
                    <option value="documentation">
                      Model card not observed
                    </option>
                    <option value="agents">Agents</option>
                  </select>
                </label>
              </div>
              <div className="border-y border-line bg-surfaceMuted px-4 py-2 text-xs leading-5 text-muted">
                {items.some((item) => !isAgent(item) && !item.model_card)
                  ? "A model card documents intended use, limitations and evaluation results. “Not observed” means no model-card signal was collected for this asset; the document may exist elsewhere."
                  : "Review the recorded signals and their linked control results."}{" "}
                Missing evidence is not a failed check.
              </div>
              {visible.length ? (
                <ul>
                  {visible.map((item) => (
                    <InventoryRow key={inventoryKey(item)} item={item} />
                  ))}
                </ul>
              ) : (
                <div className="grid gap-3 p-6 text-sm text-muted">
                  <p>
                    {items.length
                      ? "No observed assets match this filter."
                      : "No AI assets observed yet. Connect an inventory source to establish ownership and scope."}
                  </p>
                  <Link
                    href="/connectors/"
                    className="font-semibold text-brand hover:underline"
                  >
                    Connect an AI evidence source →
                  </Link>
                </div>
              )}
              {data.inventory.agents === 0 && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-3 text-xs text-muted">
                  <span>
                    No agents observed. Collect runtime evidence if agents are
                    in scope.
                  </span>
                  <Link
                    href="/connectors/"
                    className="font-semibold text-brand hover:underline"
                  >
                    Manage sources →
                  </Link>
                </div>
              )}
            </section>
            <section
              aria-label="AI framework coverage"
              className="min-w-0 rounded-xl border border-line bg-surface shadow-card"
            >
              <div className="border-b border-line p-4">
                <h2 className="text-base font-semibold">Framework coverage</h2>
                <p className="mt-1 text-xs leading-5 text-muted">
                  Current evaluations against the catalog. Mappings alone do not
                  establish coverage.
                </p>
              </div>
              <div className="divide-y divide-line">
                {data.frameworks.map((framework) => {
                  const coverage = readinessCoverage(
                    framework.evaluated_control_count,
                    framework.catalog_control_count,
                  );
                  const sufficient =
                    framework.coverage_sufficient !== false &&
                    coverage.sufficient;
                  const percent =
                    coverage.total &&
                    framework.evaluated_control_count !== undefined
                      ? Math.min(
                          100,
                          Math.round(
                            (coverage.assessed / coverage.total) * 100,
                          ),
                        )
                      : null;
                  return (
                    <div
                      key={framework.framework_id}
                      className="grid gap-2 p-4"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <Link
                          href={`/controls/?framework=${encodeURIComponent(framework.framework_id)}`}
                          className="flex min-w-0 items-center gap-2 text-sm font-semibold hover:text-brand hover:underline"
                        >
                          <FrameworkMark
                            frameworkId={framework.framework_id}
                            fallbackLabel={framework.label}
                            size={28}
                          />
                          <span>{framework.label}</span>
                        </Link>
                        <InfoHint
                          label={`${framework.label} coverage`}
                          text={aiFrameworkDetail(framework)}
                        />
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className="text-muted">
                          {framework.evaluated_control_count ?? "Unknown"} /{" "}
                          {coverage.total ?? "unknown"} currently evaluated
                        </span>
                        <span className="font-semibold">
                          {percent === null
                            ? "Unknown coverage"
                            : `${percent}% coverage`}
                        </span>
                      </div>
                      <div
                        className="h-1.5 overflow-hidden rounded-full bg-surfaceMuted"
                        aria-hidden="true"
                      >
                        <div
                          className="h-full rounded-full bg-brand"
                          style={{ width: `${percent ?? 0}%` }}
                        />
                      </div>
                      <p className="text-xs leading-5 text-muted">
                        {aiFrameworkSummary(framework)}
                      </p>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <Badge
                          tone={
                            sufficient &&
                            framework.score !== null &&
                            framework.score >= 85
                              ? "ready"
                              : "default"
                          }
                        >
                          {!sufficient
                            ? "Insufficient coverage"
                            : framework.score === null
                              ? "Not evaluated"
                              : `${framework.score}% passing`}
                        </Badge>
                        <Link
                          href={`/controls/?framework=${encodeURIComponent(framework.framework_id)}`}
                          aria-label={`Review ${framework.label} controls`}
                          className="text-xs font-semibold text-brand hover:underline"
                        >
                          Review controls →
                        </Link>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="border-t border-line p-4">
                <Link
                  href="/mapping-review/?family=ai-governance"
                  className="text-xs font-semibold text-brand hover:underline"
                >
                  Review AI safeguard mappings →
                </Link>
              </div>
            </section>
          </div>
          <details className="rounded-xl border border-line bg-surface p-4">
            <summary className="cursor-pointer text-sm font-semibold">
              Scoring and coverage methodology
            </summary>
            <div className="mt-3 grid gap-3 text-xs text-muted">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-ink">
                  {SCORE_COPY.aiGovernance.label}
                </span>
                <span>{data.governance_score}/100 · AI-only sub-indicator</span>
                <InfoHint
                  label={SCORE_COPY.aiGovernance.label}
                  text={SCORE_COPY.aiGovernance.definition}
                />
              </div>
              {data.coverage_sufficient === false && (
                <p>
                  {data.state_reason ||
                    "Insufficient framework coverage: more current evaluated evidence is needed."}
                </p>
              )}
              <p>
                Asset signals describe collected evidence. Framework coverage
                counts fresh, explicit evaluations; it does not establish
                certification or live-provider qualification.
              </p>
              {data.frameworks.map((framework) => (
                <p key={framework.framework_id}>
                  {framework.label}: {framework.mapped_requirements} of{" "}
                  {framework.requirements} requirements mapped;{" "}
                  {framework.reviewed_requirements ?? "unknown"} reviewed.
                </p>
              ))}
            </div>
          </details>
        </div>
      )}
    </QueryState>
  );
}
