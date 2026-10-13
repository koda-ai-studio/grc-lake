import type { GraphNode } from "@/lib/api/types";

/** Describe the source outcome without turning an observation into a verdict. */
export function graphEvidenceState(node: Pick<GraphNode, "kind" | "status">) {
  const status = (node.status ?? "").toLowerCase();
  const assessment = ["control", "safeguard"].includes(node.kind);
  const subject = assessment ? node.kind : "evidence";
  if (status === "stale")
    return {
      label: assessment ? "Stale assessment" : "Stale evidence",
      tone: "attention" as const,
      action:
        "Refresh the supporting evidence and re-evaluate the applicable control.",
    };
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
  if (
    [
      "open",
      "failed",
      "fail",
      "failing",
      "blocked",
      "noncompliant",
      "non-compliant",
    ].includes(status)
  )
    return {
      label: `Failing ${subject}`,
      tone: "critical" as const,
      action:
        "Review the failing record, confirm the affected configuration, assign remediation, and collect fresh evidence after the change.",
    };
  if (
    [
      "pass",
      "passed",
      "resolved",
      "closed",
      "compliant",
      "ok",
      "ready",
    ].includes(status)
  )
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
