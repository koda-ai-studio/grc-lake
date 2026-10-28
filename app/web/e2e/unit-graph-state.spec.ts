import { expect, test } from "@playwright/test";
import { graphEvidenceState } from "../src/lib/graph-evidence";
import { controlResultPresentation } from "../src/lib/control-attestation";

test("control and safeguard outcomes distinguish fail, pass, stale and unknown", () => {
  expect(graphEvidenceState({ kind: "control", status: "fail" })).toMatchObject(
    { label: "Failing control", tone: "critical" },
  );
  expect(
    graphEvidenceState({ kind: "control", status: "pass", ccf_status: "pass" }),
  ).toMatchObject({ label: "Passing · Attested", tone: "ready" });
  expect(
    graphEvidenceState({ kind: "safeguard", status: "not_evaluated" }),
  ).toMatchObject({ label: "Not evaluated", tone: "default" });
  expect(
    graphEvidenceState({ kind: "control", status: "stale" }),
  ).toMatchObject({ label: "Stale assessment", tone: "attention" });
  expect(graphEvidenceState({ kind: "control" }).tone).toBe("default");
  expect(
    graphEvidenceState({ kind: "evidence_type", status: "open" }).label,
  ).toBe("Failing evidence");
});

test("identity assertions never receive passing or failing verdict labels", () => {
  expect(
    graphEvidenceState({ kind: "canonical_entity", status: "caller_asserted" })
      .label,
  ).toBe("Caller asserted");
  expect(
    graphEvidenceState({ kind: "entity_alias", status: "evidence_missing" })
      .label,
  ).toBe("Missing evidence");
  expect(
    graphEvidenceState({ kind: "entity_alias", status: "evidence_stale" })
      .label,
  ).toBe("Stale evidence");
});

test("a control test that needs evidence never reads as stale or clean", () => {
  const missing = graphEvidenceState({
    kind: "control",
    status: "needs_evidence",
    ccf_status: "pass",
    missing_evidence_types: ["audit.chain", "detection.alert"],
  });
  expect(missing).toMatchObject({ label: "Needs evidence", tone: "attention" });
  expect(missing.action).toContain("audit.chain, detection.alert");
  expect(missing.action).not.toMatch(/refresh/i);
  const stale = graphEvidenceState({
    kind: "control",
    status: "needs_evidence",
    stale_evidence_types: ["runtime.inference"],
  });
  expect(stale.label).toBe("Needs evidence");
  expect(stale.action).toContain("Refresh the runtime.inference evidence");
  expect(
    graphEvidenceState({ kind: "control", status: "needs_evidence" }).action,
  ).toMatch(/collect evidence/i);
});

test("control labels come from the same source as the Controls page", () => {
  for (const [status, ccf_status] of [
    ["pass", "pass"],
    ["pass", "open"],
    ["needs_evidence", "not_evaluated"],
  ]) {
    expect(
      graphEvidenceState({ kind: "control", status, ccf_status }),
    ).toMatchObject({
      label: controlResultPresentation(status, { ccf_status }).label,
      tone: controlResultPresentation(status, { ccf_status }).tone,
    });
  }
});
