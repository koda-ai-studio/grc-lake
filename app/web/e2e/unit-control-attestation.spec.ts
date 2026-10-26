import { expect, test } from "@playwright/test";
import {
  attestedHeadline,
  attestedPassCount,
  controlResultPresentation,
  mappingCountsLabel,
} from "../src/lib/control-attestation";

// A control test result is shown next to the framework (CCF) result; only a
// CCF pass through reviewed mappings is presented as an attested pass.

test.describe("control result presentation", () => {
  test("a passing control test with only proposed mappings is not attested", () => {
    const shown = controlResultPresentation("pass", {
      ccf_status: "not_evaluated",
      reviewed_safeguard_count: 0,
      proposed_safeguard_count: 1,
    });
    expect(shown.label).toBe("Control test passing · Not attested");
    expect(shown.tone).toBe("attention");
    expect(shown.attested).toBe(false);
  });

  test("missing CCF fields never read as attested", () => {
    const shown = controlResultPresentation("pass", {});
    expect(shown.attested).toBe(false);
    expect(shown.tone).not.toBe("ready");
  });

  test("only a CCF pass is presented as attested passing", () => {
    const shown = controlResultPresentation("pass", {
      ccf_status: "pass",
      reviewed_safeguard_count: 2,
      proposed_safeguard_count: 0,
    });
    expect(shown.label).toBe("Passing · Attested");
    expect(shown.tone).toBe("ready");
    expect(shown.attested).toBe(true);
  });

  test("failing and other control test results keep their own tone", () => {
    expect(controlResultPresentation("fail", { ccf_status: "pass" })).toEqual({
      label: "Fail",
      tone: "critical",
      attested: false,
    });
    expect(controlResultPresentation("stale", {}).tone).toBe("attention");
  });

  test("mapping counts read as reviewed and proposed", () => {
    expect(
      mappingCountsLabel({
        reviewed_safeguard_count: 0,
        proposed_safeguard_count: 1,
      }),
    ).toBe("0 reviewed · 1 proposed mapping");
    expect(
      mappingCountsLabel({
        reviewed_safeguard_count: 2,
        proposed_safeguard_count: 3,
      }),
    ).toBe("2 reviewed · 3 proposed mappings");
  });

  test("framework headline leads with attested passes", () => {
    expect(attestedHeadline(8, 0)).toBe("8 control tests passing · 0 attested");
    expect(attestedHeadline(1, 1)).toBe("1 control test passing · 1 attested");
  });
});

test("attested pass count needs both a passing test and a CCF pass", () => {
  expect(
    attestedPassCount([
      { result: "pass", ccf_status: "pass" },
      { result: "pass", ccf_status: "not_evaluated" },
      { result: "fail", ccf_status: "pass" },
      { result: "pass" },
    ]),
  ).toBe(1);
});
