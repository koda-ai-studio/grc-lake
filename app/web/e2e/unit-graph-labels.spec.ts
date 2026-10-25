import { expect, test } from "@playwright/test";
import {
  graphEdgeInvalid,
  graphEvidenceState,
  graphKindLabel,
  graphNodeAriaLabel,
  labelWithKind,
} from "../src/lib/graph-evidence";
import {
  GRAPH_LAYOUT_NODE_CAP,
  graphLayoutBudget,
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
  for (const ccf of ["open", "fail", "not_evaluated"]) {
    const state = graphEvidenceState({
      kind: "control",
      status: "pass",
      ccf_status: ccf,
    });
    expect(state.label).toBe("Control test passing · not attested");
    expect(state.tone).not.toBe("ready");
  }
  expect(
    graphEvidenceState({ kind: "control", status: "pass", ccf_status: "pass" }),
  ).toMatchObject({ label: "Passing control", tone: "ready" });
  // Older payloads without the framework result keep the posture label.
  expect(graphEvidenceState({ kind: "control", status: "pass" }).label).toBe(
    "Passing control",
  );
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
