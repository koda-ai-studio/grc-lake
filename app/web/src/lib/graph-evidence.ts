import type { GraphEdge, GraphNode, GraphNodeKind } from "@/lib/api/types";
import { controlResultPresentation } from "@/lib/control-attestation";
import { displayLabel } from "@/lib/display";
import {
  FAILING_STATUSES,
  PASSING_STATUSES,
  STALE_FRESHNESS,
} from "@/lib/evidence-status";

type StateInput = Pick<GraphNode, "kind" | "status"> &
  Partial<
    Pick<
      GraphNode,
      | "freshness_status"
      | "ccf_status"
      | "missing_evidence_types"
      | "stale_evidence_types"
    >
  >;

function needsEvidenceAction(node: StateInput) {
  const missing = node.missing_evidence_types ?? [];
  const stale = node.stale_evidence_types ?? [];
  const steps = [
    missing.length && `Collect the missing ${missing.join(", ")} evidence.`,
    stale.length && `Refresh the ${stale.join(", ")} evidence.`,
  ].filter(Boolean);
  return [
    "The control test has no current evidence to pass or fail on.",
    ...(steps.length ? steps : ["Collect evidence for this control."]),
    "Then re-evaluate the control.",
  ].join(" ");
}

/** Describe the source outcome without turning an observation into a verdict. */
export function graphEvidenceState(node: StateInput) {
  const status = (node.status ?? "").toLowerCase();
  if (["canonical_entity", "entity_alias"].includes(node.kind))
    return {
      label:
        status === "evidence_missing"
          ? "Missing evidence"
          : status === "evidence_stale"
            ? "Stale evidence"
            : "Caller asserted",
      tone: "attention" as const,
      action:
        "Review the recorded assertion and its exact source evidence. Caller attribution does not establish authenticated approval.",
    };
  const assessment = ["control", "safeguard"].includes(node.kind);
  const subject = assessment ? node.kind : "evidence";
  if (status === "stale")
    return {
      label: assessment ? "Stale assessment" : "Stale evidence",
      tone: "attention" as const,
      action:
        "Refresh the supporting evidence and re-evaluate the applicable control.",
    };
  if (node.kind === "control" && status === "needs_evidence") {
    const shown = controlResultPresentation(status, node);
    return {
      label: shown.label,
      tone: shown.tone,
      action: needsEvidenceAction(node),
    };
  }
  if (
    node.kind === "signal_gap" ||
    ["requires_authenticated_connector", "not_available_public_mode"].includes(
      status,
    )
  )
    return {
      label: "Not observable",
      tone: "attention" as const,
      action:
        "Use authorized governance access to inspect settings that public collection cannot read.",
    };
  if (FAILING_STATUSES.has(status))
    return {
      label: `Failing ${subject}`,
      tone: "critical" as const,
      action:
        "Review the failing record, confirm the affected configuration, assign remediation, and collect fresh evidence after the change.",
    };
  if (PASSING_STATUSES.has(status) && !assessment) {
    const freshness = (node.freshness_status || "missing").toLowerCase();
    if (freshness === "missing")
      return {
        label: "Evidence freshness unknown",
        tone: "attention" as const,
        action:
          "The record passed, but its source evidence or collection time is not recorded. Collect fresh evidence before relying on it.",
      };
    if (STALE_FRESHNESS.has(freshness))
      return {
        label: "Stale evidence",
        tone: "attention" as const,
        action: `The record passed when collected, but it is ${freshness}. Collect fresh evidence before relying on it.`,
      };
  }
  if (node.kind === "control" && PASSING_STATUSES.has(status)) {
    const shown = controlResultPresentation("pass", node);
    const ccf = (node.ccf_status || "not_evaluated").toLowerCase();
    return {
      label: shown.label,
      tone: shown.tone,
      action: shown.attested
        ? "Keep the bound evidence current and re-evaluate after the underlying configuration changes."
        : `The control test passes, but the framework result is ${displayLabel(ccf).toLowerCase()}. Review the mapped safeguards and their evidence before attesting this requirement.`,
    };
  }
  if (PASSING_STATUSES.has(status))
    return {
      label: `Passing ${subject}`,
      tone: "ready" as const,
      action:
        "Keep this evidence current and re-evaluate after repository settings change. This record alone does not establish framework compliance.",
    };
  return {
    label: status === "observed" ? "Observed · not evaluated" : "Not evaluated",
    tone: "default" as const,
    action:
      "The record does not establish a passing or failing result. Review its contents and evaluate the applicable control before drawing a conclusion.",
  };
}

export function graphRecordLabel(node: Pick<GraphNode, "kind" | "label">) {
  if (node.kind === "repository")
    return node.label.replace(/^(github|gitlab):repo:/, "");
  if (!["evidence", "evidence_type"].includes(node.kind)) return node.label;
  const names: Record<string, string> = {
    "repository.authenticated_signal_gap": "Private governance",
    "repository.ci_workflow": "CI workflows",
    "repository.iac": "Infrastructure as code",
    "repository.codeowners": "Code owners",
  };
  if (names[node.label]) return names[node.label];
  const value = node.label.split(".").at(-1)!.replaceAll("_", " ");
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function graphCheckGuidance(
  node: Pick<GraphNode, "event_type" | "label">,
) {
  const signal = node.event_type ?? node.label;
  if (signal.includes("branch_protection"))
    return "Check whether required reviews, status checks, and owner approvals match the intended branch policy.";
  if (signal.includes("codeowners"))
    return "Check owner coverage for changed files and whether owner approval is required.";
  return null;
}

const KIND_NAME: Partial<Record<GraphNodeKind, string>> = {
  ccf_category: "CCF category",
  ccf_family: "CCF family",
};

/** Singular, sentence-case kind name ("evidence_type" -> "Evidence type"). */
export function graphKindLabel(kind: GraphNodeKind) {
  return KIND_NAME[kind] ?? displayLabel(kind);
}

/** "label · kind", unless the label already ends with the kind word. */
export function labelWithKind(label: string, kind: GraphNodeKind) {
  const word = kind.replaceAll("_", " ");
  const lower = label.toLowerCase();
  return lower === word || lower.endsWith(` ${word}`)
    ? label
    : `${label} · ${word}`;
}

const OUTCOME_KINDS: GraphNodeKind[] = [
  "canonical_entity",
  "entity_alias",
  "control",
  "safeguard",
  "evidence",
  "evidence_type",
  "signal_gap",
];

export function graphHasOutcome(kind: GraphNodeKind) {
  return OUTCOME_KINDS.includes(kind);
}

/** Screen-reader name for a canvas node: "<kind>: <label>, <status>". */
export function graphNodeAriaLabel(
  node: StateInput &
    Pick<GraphNode, "label"> &
    Partial<Pick<GraphNode, "severity">>,
) {
  const name = `${graphKindLabel(node.kind)}: ${graphRecordLabel(node)}`;
  if (graphHasOutcome(node.kind))
    return `${name}, ${graphEvidenceState(node).label}`;
  const detail = [displayLabel(node.severity), displayLabel(node.status)]
    .filter(Boolean)
    .join(" · ");
  return detail ? `${name}, ${detail}` : name;
}

/** An edge whose evidence does not apply to the bound asset's type. */
export function graphEdgeInvalid(edge: Pick<GraphEdge, "binding">) {
  return edge.binding === "invalid_asset_type";
}

/** Missing or unfamiliar review provenance never inherits reviewed styling. */
export function graphMappingReview(
  edge: Pick<GraphEdge, "kind" | "review_state">,
) {
  if (edge.kind !== "maps_to" && !edge.review_state) return null;
  const state = edge.review_state;
  const reviewed = state === "maintainer_reviewed" || state === "org_reviewed";
  const pending: Record<string, string> = {
    proposed: "Proposed mapping",
    needs_changes: "Needs changes",
    rejected: "Rejected mapping",
  };
  return {
    reviewed,
    label: reviewed
      ? state.replaceAll("_", " ")
      : state
        ? Object.hasOwn(pending, state)
          ? pending[state]
          : "Review unrecognized"
        : "Review not recorded",
  };
}
