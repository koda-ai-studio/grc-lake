"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api/client";
import type { RequirementGapPage } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { displayLabel } from "@/lib/display";

const GUIDANCE: Record<
  string,
  { title: string; action: string; href: string }
> = {
  mapping_review_pending: {
    title: "Mapping review pending",
    action:
      "A human reviewer must decide whether the proposed mapping establishes implementation equivalence.",
    href: "/mapping-review",
  },
  no_reviewed_implementation: {
    title: "No reviewed implementation mapping",
    action:
      "Review or propose an implementation mapping before treating this requirement as covered.",
    href: "/mapping-review",
  },
  context_only: {
    title: "Context mappings only",
    action:
      "Supporting context does not establish implementation coverage. Review an implementation mapping.",
    href: "/mapping-review",
  },
  review_log_unverified: {
    title: "Review log unverified",
    action:
      "Inspect mapping-review integrity and publish a new assessment after resolving the issue.",
    href: "/mapping-review",
  },
  safeguard_failed: {
    title: "A safeguard failed",
    action:
      "Investigate the failing safeguard and its evidence before reassessing.",
    href: "/evidence",
  },
  safeguard_stale: {
    title: "Refresh stale evidence",
    action: "Collect current evidence, then run a new assessment.",
    href: "/connectors",
  },
  safeguard_not_evaluated: {
    title: "Safeguard not evaluated",
    action: "Inspect evidence and applicable assets, then run an assessment.",
    href: "/evidence",
  },
  unassessed_assets: {
    title: "Observed assets lack assessment",
    action:
      "Collect and assess the missing safeguard evidence for these observed assets.",
    href: "/evidence",
  },
  invalid_evidence_bindings: {
    title: "Evidence bindings rejected",
    action:
      "Inspect evidence-to-safeguard bindings and correct them before reassessing.",
    href: "/evidence",
  },
  requirement_stale: {
    title: "Requirement result is stale",
    action:
      "Refresh evidence and reassess. This summary does not identify specific missing evidence types.",
    href: "/connectors",
  },
  assessment_detail_missing: {
    title: "Assessment detail missing",
    action:
      "Inspect the assessment and re-evaluate if needed; a passing result cannot be inferred.",
    href: "/evidence",
  },
};

function FrozenGaps({
  frameworkId,
  controlId,
}: {
  frameworkId: string;
  controlId: string;
}) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    data?: RequirementGapPage;
    error?: string;
  }>({});
  useEffect(() => {
    let active = true;
    api
      .requirementGaps(frameworkId, controlId)
      .then((data) => {
        // Reject a different requirement, missing provenance, or partial page.
        const generation = data.meta?.generation;
        if (
          !generation?.generation_id ||
          !generation.manifest_sha256 ||
          !Array.isArray(data.data) ||
          data.data.length > 1 ||
          data.meta.count !== data.data.length ||
          data.data.some(
            (row) =>
              row.control_id !== controlId || row.framework_id !== frameworkId,
          )
        ) {
          throw new Error("Invalid frozen result");
        }
        if (active) setState({ data });
      })
      .catch((error) => {
        if (active)
          setState({
            error:
              error instanceof ApiError && error.status === 409
                ? "Assessment details are unavailable or have changed. Retry the latest assessment; an operator may need to re-evaluate the lake."
                : "Assessment details could not be loaded. Check access and retry; no coverage conclusion is available.",
          });
      });
    return () => {
      active = false;
    };
  }, [attempt, controlId, frameworkId]);
  const row = state.data?.data[0];
  const retry = () => {
    setState({});
    setAttempt((value) => value + 1);
  };
  const codes = row?.gap_codes ?? [];
  const destinations = new Set(
    codes.map((code) => GUIDANCE[code]?.href ?? "/evidence"),
  );
  return (
    <section
      aria-label="Frozen requirement gaps"
      className="grid gap-3 rounded-xl border border-line bg-surfaceMuted p-3 text-sm"
    >
      <h3 className="font-semibold">Why this requirement has gaps</h3>
      {!state.data && !state.error && (
        <p role="status">Loading frozen assessment…</p>
      )}
      {state.error && <p role="alert">{state.error}</p>}
      {state.data && !row && (
        <p>
          No frozen result is available for this requirement. This is not a
          passing assessment.
        </p>
      )}
      {(state.error || (state.data && !row)) && (
        <Button onClick={retry}>Retry latest assessment</Button>
      )}
      {row && (
        <>
          <p className="font-semibold">
            Stored result: {displayLabel(row.status)}
          </p>
          <p className="text-xs text-muted">
            {row.reviewed_safeguard_count} reviewed safeguards ·{" "}
            {row.pending_mapping_count} pending mappings ·{" "}
            {row.contextual_mapping_count} context mappings
          </p>
          <ul className="grid gap-2">
            {codes.map((code) => (
              <li
                key={code}
                className="rounded-lg border border-line bg-surface p-3"
              >
                <p className="font-semibold">
                  {GUIDANCE[code]?.title ?? displayLabel(code)}
                </p>
                <p className="mt-1 text-xs text-muted">
                  {GUIDANCE[code]?.action ??
                    "Inspect the assessment details before drawing a coverage conclusion."}
                </p>
              </li>
            ))}
          </ul>
          {!codes.length && (
            <p>
              No blockers recorded in this frozen summary. This does not
              establish complete coverage or certification.
            </p>
          )}
          {row.blocking_safeguards.length > 0 && (
            <details>
              <summary className="cursor-pointer font-semibold">
                Blocking safeguards ({row.blocking_safeguards.length})
              </summary>
              <ul className="mt-2 grid gap-2 text-xs">
                {row.blocking_safeguards.map((safeguard) => (
                  <li key={safeguard.safeguard_id}>
                    <span className="break-all font-semibold">
                      {safeguard.safeguard_id}
                    </span>{" "}
                    · {displayLabel(safeguard.status)} ·{" "}
                    {safeguard.unassessed_asset_count} unassessed observed
                    assets · {safeguard.invalid_binding_count} invalid evidence
                    bindings
                  </li>
                ))}
              </ul>
            </details>
          )}
          <div className="flex flex-wrap gap-3 text-xs font-semibold text-brand">
            {destinations.has("/mapping-review") && (
              <Link
                href={`/mapping-review?framework=${encodeURIComponent(frameworkId)}`}
              >
                Review mappings
              </Link>
            )}
            {destinations.has("/evidence") && (
              <Link href="/evidence">Inspect evidence</Link>
            )}
            {destinations.has("/connectors") && (
              <Link href="/connectors">Refresh connections</Link>
            )}
          </div>
          <p className="text-xs text-muted">
            Complete asset inventory is not established. These results concern
            observed assets. Later reviews and evidence changes appear only
            after a new assessment.
          </p>
          <details className="text-xs text-muted">
            <summary className="cursor-pointer">
              Frozen assessment source
            </summary>
            <dl className="mt-2 grid gap-1 break-all">
              <dt>Generation</dt>
              <dd>{state.data!.meta.generation.generation_id}</dd>
              <dt>Manifest SHA-256</dt>
              <dd>{state.data!.meta.generation.manifest_sha256}</dd>
            </dl>
            <p className="mt-2">
              Reading this stored summary does not perform a new integrity
              verification.
            </p>
          </details>
        </>
      )}
    </section>
  );
}

export function RequirementGapPanel(props: {
  frameworkId: string;
  controlId: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="grid gap-2">
      <Button
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Hide assessment gaps" : "Explain assessment gaps"}
      </Button>
      <div id={id}>{open && <FrozenGaps {...props} />}</div>
    </div>
  );
}
