import { expect, test } from "@playwright/test";
import {
  graphEdgeInvalid,
  graphEvidenceState,
  graphKindLabel,
  graphMappingReview,
  graphNodeAriaLabel,
  labelWithKind,
} from "../src/lib/graph-evidence";
import {
  GRAPH_LAYOUT_NODE_CAP,
  GRAPH_LAYOUT_EDGE_CAP,
  graphLayoutBudget,
  graphScope,
} from "../src/lib/graph-layout";

test("passing evidence that is stale or expired never reads as passing", () => {
  for (const freshness of ["stale", "expired"]) {
    const state = graphEvidenceState({
      kind: "evidence_type",
      status: "passed",
      freshness_status: freshness,
    });
    expect(state).toMatchObject({ label: "Stale evidence", tone: "attention" });
  }
  expect(
    graphEvidenceState({
      kind: "evidence_type",
      status: "passed",
      freshness_status: "fresh",
    }),
  ).toMatchObject({ label: "Passing evidence", tone: "ready" });
  // No recorded freshness, or a record without source evidence, is never clean.
  for (const freshness of ["missing", undefined, ""]) {
    const state = graphEvidenceState({
      kind: "evidence_type",
      status: "passed",
      freshness_status: freshness,
    });
    expect(state).toMatchObject({
      label: "Evidence freshness unknown",
      tone: "attention",
    });
  }
  // A failure stays a failure however old the record is.
  expect(
    graphEvidenceState({
      kind: "evidence_type",
      status: "open",
      freshness_status: "expired",
    }),
  ).toMatchObject({ label: "Failing evidence", tone: "critical" });
});

test("a passing control test without a passing framework result is not attested", () => {
  for (const ccf of [
    undefined,
    "",
    "open",
    "fail",
    "not_evaluated",
    "closed",
    "resolved",
  ]) {
    const state = graphEvidenceState({
      kind: "control",
      status: "pass",
      ccf_status: ccf,
    });
    expect(state.label).toBe("Control test passing · Not attested");
    expect(state.tone).not.toBe("ready");
  }
  expect(
    graphEvidenceState({ kind: "control", status: "pass", ccf_status: "pass" }),
  ).toMatchObject({ label: "Passing · Attested", tone: "ready" });
  expect(
    graphEvidenceState({ kind: "control", status: "fail", ccf_status: "pass" })
      .label,
  ).toBe("Failing control");
});

test("node accessible names state kind, label and status", () => {
  expect(
    graphNodeAriaLabel({
      kind: "control",
      label: "SOC2-CC6.1",
      status: "fail",
    }),
  ).toBe("Control: SOC2-CC6.1, Failing control");
  expect(
    graphNodeAriaLabel({
      kind: "asset",
      label: "Billing DB",
      status: undefined,
    }),
  ).toBe("Asset: Billing DB");
  expect(
    graphNodeAriaLabel({
      kind: "safeguard",
      label: "Logical access and MFA",
      status: "not_evaluated",
    }),
  ).toBe("Safeguard: Logical access and MFA, Not evaluated");
});

test("kind labels and duplicated kind suffixes read naturally", () => {
  expect(graphKindLabel("safeguard")).toBe("Safeguard");
  expect(graphKindLabel("evidence_type")).toBe("Evidence type");
  expect(labelWithKind("acme/model-service repository", "repository")).toBe(
    "acme/model-service repository",
  );
  expect(labelWithKind("SOC2-CC6.1", "control")).toBe("SOC2-CC6.1 · control");
  expect(labelWithKind("Prod", "environment")).toBe("Prod · environment");
});

test("an invalid asset-type binding is never a supporting edge", () => {
  expect(graphEdgeInvalid({ binding: "invalid_asset_type" })).toBe(true);
  expect(graphEdgeInvalid({})).toBe(false);
  expect(graphEdgeInvalid({ binding: undefined })).toBe(false);
});

test("layout is refused above the node cap and virtualised for large maps", () => {
  expect(GRAPH_LAYOUT_NODE_CAP).toBeLessThanOrEqual(500);
  expect(graphLayoutBudget(2412)).toMatchObject({ draw: false });
  expect(graphLayoutBudget(GRAPH_LAYOUT_NODE_CAP)).toMatchObject({
    draw: true,
    virtualize: true,
  });
  expect(graphLayoutBudget(14)).toMatchObject({
    draw: true,
    virtualize: false,
  });
});

test("relationship density is bounded even when the node count is small", () => {
  expect(graphLayoutBudget(50, 1225)).toMatchObject({ draw: false });
  expect(graphLayoutBudget(50, 500)).toMatchObject({
    draw: true,
    virtualize: true,
  });
  expect(graphLayoutBudget(500, GRAPH_LAYOUT_EDGE_CAP).draw).toBe(true);
  expect(graphLayoutBudget(500, GRAPH_LAYOUT_EDGE_CAP + 1).draw).toBe(false);
});

test("only explicit maintainer or organization review styles a mapping as reviewed", () => {
  for (const review_state of [
    undefined,
    "",
    "proposed",
    "approved",
    "future_state",
  ]) {
    expect(
      graphMappingReview({ kind: "maps_to", review_state })?.reviewed,
    ).toBe(false);
  }
  for (const review_state of ["maintainer_reviewed", "org_reviewed"]) {
    expect(
      graphMappingReview({ kind: "maps_to", review_state })?.reviewed,
    ).toBe(true);
  }
  expect(graphMappingReview({ kind: "evidence_covers_asset" })).toBeNull();
  for (const review_state of ["future_state", "__proto__", "constructor"]) {
    expect(graphMappingReview({ kind: "maps_to", review_state })?.label).toBe(
      "Review unrecognized",
    );
  }
  expect(
    graphMappingReview({ kind: "maps_to", review_state: "rejected" }),
  ).toEqual({ reviewed: false, label: "Rejected mapping" });
  expect(
    graphMappingReview({ kind: "maps_to", review_state: "needs_changes" }),
  ).toEqual({ reviewed: false, label: "Needs changes" });
});

test("scope hops are exact and independent of edge order", () => {
  const edges = [
    { source: "framework", target: "control" },
    { source: "control", target: "evidence" },
    { source: "evidence", target: "asset" },
    { source: "other-control", target: "evidence" },
  ];
  for (const ordered of [edges, [...edges].reverse()]) {
    expect(
      [...graphScope(ordered, new Set(["framework"]), 2, true)].sort(),
    ).toEqual(["control", "evidence", "framework"]);
    expect([...graphScope(ordered, new Set(["control"]), 1)].sort()).toEqual([
      "control",
      "evidence",
      "framework",
    ]);
  }
});

test("a bounded scope stays small in a 10,000-node cycle", () => {
  const edges = Array.from({ length: 10_000 }, (_, i) => ({
    source: String(i),
    target: String((i + 1) % 10_000),
  }));
  const seed = new Set(["0"]);
  const started = performance.now();
  expect([...graphScope(edges, seed, 3)].sort()).toEqual([
    "0",
    "1",
    "2",
    "3",
    "9997",
    "9998",
    "9999",
  ]);
  expect(performance.now() - started).toBeLessThan(1000);
  expect([...seed]).toEqual(["0"]);
  expect([...graphScope(edges, seed, 0)]).toEqual(["0"]);
});
