import { expect, test } from "@playwright/test";
import { graphEvidenceState } from "../src/lib/graph-evidence";

test("control and safeguard outcomes distinguish fail, pass, stale and unknown", () => {
  expect(graphEvidenceState({ kind: "control", status: "fail" })).toMatchObject(
    { label: "Failing control", tone: "critical" },
  );
  expect(graphEvidenceState({ kind: "control", status: "pass" })).toMatchObject(
    { label: "Passing control", tone: "ready" },
  );
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
