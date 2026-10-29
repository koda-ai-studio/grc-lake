import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`connection hub flags partial collection at ${width}px`, async ({
    page,
  }, testInfo) => {
    let partialRun: Record<string, unknown> = {};
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/v1/connectors?*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const base = body.data.find(
        (row: { connector_id: string }) =>
          row.connector_id === "github-security",
      );
      const success = {
        connector_id: "github-security",
        kind: "sync",
        result: "ok",
        actor: "test",
        evidence_count: 4,
        occurred_at: new Date().toISOString(),
        error: null,
        duration_ms: 10,
      };
      body.data = [
        {
          ...base,
          state: "enabled",
          freshness_state: "fresh",
          last_probe: null,
          last_successful_sync: success,
          last_sync: {
            ...success,
            metadata: {
              partial: true,
              coverage_gaps: [
                {
                  source: "github",
                  operation: "read_branches",
                  reason: "permission_denied",
                  message: "Branch protection could not be read.",
                },
              ],
            },
          },
        },
      ];
      partialRun = body.data[0].last_sync;
      body.meta = { ...body.meta, count: 1, total: 1, next_cursor: null };
      await route.fulfill({ response, json: body });
    });
    await page.route("**/api/v1/connectors/github-security/runs*", (route) =>
      route.fulfill({
        json: { data: [partialRun], meta: { connector_id: "github-security" } },
      }),
    );
    await page.goto("/console/connectors/");
    const progress = page.getByRole("region", {
      name: "From connection to evidence",
    });
    await expect(progress).toContainText(
      "GitHub Security: Partial evidence collected",
    );
    await expect(
      progress.getByText("With recent evidence").locator(".."),
    ).toContainText("0");
    await page.getByRole("tab", { name: "Needs attention" }).click();
    await expect(
      page.getByRole("button", { name: "Open GitHub Security" }),
    ).toBeVisible();
    await expect(page.getByRole("main")).not.toContainText("healthy");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await progress
      .getByRole("button", { name: "Review collection gaps" })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog")).toContainText(
      "Partial evidence collected",
    );
    await page
      .getByRole("dialog")
      .locator("summary")
      .filter({ hasText: "Run history" })
      .click();
    await expect(page.getByRole("dialog")).toContainText(
      "Branch protection could not be read.",
    );
    await page.screenshot({
      path: testInfo.outputPath("partial-collection.png"),
      fullPage: true,
      animations: "disabled",
    });
  });
}
