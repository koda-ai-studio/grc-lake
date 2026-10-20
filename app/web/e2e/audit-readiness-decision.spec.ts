import { expect, test } from "@playwright/test";

test("audit decision displays the live API gates without recalculating them", async ({
  page,
  request,
}) => {
  const response = await request.get("/api/v1/platform/audit-readiness");
  expect(response.ok()).toBeTruthy();
  const { data } = await response.json();
  await page.goto("/console/audit-room/");
  const decision = page.getByRole("region", { name: "Readiness decision" });
  await expect(decision).toBeVisible();
  for (const gate of data.readiness_decision.gates) {
    const item = decision.getByRole("listitem").filter({ hasText: gate.label });
    await expect(item).toContainText(gate.detail);
    await expect(item).toContainText(gate.passed ? "Met" : "Needs attention");
  }
  await expect(decision).toContainText(data.readiness_decision.boundary);
  const scope = page.getByRole("region", { name: "Evaluated framework scope" });
  await scope.focus();
  await expect(scope).toBeFocused();
});

for (const theme of ["light", "dark"]) {
  test(`high index keeps unresolved scope visible on desktop and mobile (${theme})`, async ({
    page,
    request,
  }) => {
    const { data } = await (
      await request.get("/api/v1/platform/audit-readiness")
    ).json();
    // Browser presentation fixture. Python regressions exercise the real 93/100
    // decision with incomplete, unknown, failed and unassessed frameworks.
    data.state = "on_track";
    data.audit_score = 93;
    data.posture.frameworks_ready = 2;
    data.posture.frameworks_total = 3;
    data.readiness_decision.gates = [
      {
        id: "score",
        label: "Readiness index",
        passed: true,
        detail: "93/100; minimum 85",
        href: "/console/audit-room",
      },
      {
        id: "frameworks",
        label: "Evaluated frameworks",
        passed: false,
        detail: "2 of 3 meet score and coverage thresholds",
        href: "/console/frameworks",
      },
      {
        id: "blocking_gaps",
        label: "Outstanding gaps",
        passed: false,
        detail: "1 unresolved; none permitted",
        href: "/console/audit-room",
      },
    ];
    data.frameworks = [
      {
        framework: "SOC 2",
        score: 100,
        assessed_controls: 61,
        total_controls: 61,
        coverage_pct: 100,
        ready: true,
        blocking_reasons: [],
      },
      {
        framework: "ISO 27001:2022",
        score: 100,
        assessed_controls: 93,
        total_controls: 93,
        coverage_pct: 100,
        ready: true,
        blocking_reasons: [],
      },
      {
        framework: "NIST AI RMF",
        score: 100,
        assessed_controls: 1,
        total_controls: 72,
        coverage_pct: 1.4,
        ready: false,
        blocking_reasons: ["insufficient_coverage"],
      },
    ];
    data.gaps = [
      {
        id: "framework_readiness",
        label: "1 evaluated framework(s) below readiness thresholds",
        href: "/console/frameworks",
      },
    ];
    await page.addInitScript(
      (value) => localStorage.setItem("trustops:theme", JSON.stringify(value)),
      theme,
    );
    await page.route("**/api/v1/platform/audit-readiness", (route) =>
      route.fulfill({ json: { data, meta: {}, errors: [] } }),
    );
    // Prevent live events from replacing the intentional presentation fixture.
    await page.route("**/api/v1/stream*", (route) => route.abort());
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/console/audit-room/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const decision = page.getByRole("region", { name: "Readiness decision" });
    await expect(decision).toContainText("93/100; minimum 85");
    await expect(
      decision.getByText("Needs attention", { exact: true }),
    ).toHaveCount(2);
    await expect(page.getByText("Audit ready", { exact: true })).toHaveCount(0);
    await expect(
      page.getByText("Below assessment coverage threshold", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(/Framework thresholds: score 100\/100/),
    ).toBeVisible();
    await expect(
      decision.getByRole("link", { name: "Evaluated frameworks" }),
    ).toHaveAttribute("href", "/console/frameworks/");
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await expect
        .poll(() =>
          page.evaluate(
            () => document.documentElement.scrollWidth - innerWidth,
          ),
        )
        .toBeLessThanOrEqual(1);
      await expect(decision.getByRole("listitem")).toHaveCount(3);
      await expect
        .poll(() =>
          page
            .locator("main")
            .evaluate((element) => element.scrollWidth - element.clientWidth),
        )
        .toBeLessThanOrEqual(1);
      const bounds = await decision.boundingBox();
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    }
  });
}
