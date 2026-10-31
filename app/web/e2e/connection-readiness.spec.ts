import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`connection hub prioritizes failed collection at ${width}px`, async ({
    page,
  }) => {
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
            result: "error",
            evidence_count: 0,
            error: "Read denied",
          },
        },
      ];
      body.meta = { ...body.meta, count: 1, total: 1, next_cursor: null };
      await route.fulfill({ response, json: body });
    });
    await page.goto("/console/connectors/");
    await page.getByRole("tab", { name: "Status", exact: true }).click();
    const progress = page.getByRole("region", {
      name: "From connection to evidence",
    });
    await expect(progress).toContainText("GitHub Security: Latest sync failed");
    await expect(
      progress.getByText("With recent evidence").locator(".."),
    ).toContainText("0");
    await page.getByRole("tab", { name: "Sources", exact: true }).click();
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
    await page.getByRole("tab", { name: "Status", exact: true }).click();
    await progress.getByRole("button", { name: "Review failed sync" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog")).toContainText("Latest sync failed");
  });
}

test("empty workspace explains the first evidence step", async ({ page }) => {
  await page.route("**/api/v1/connectors?*", (route) =>
    route.fulfill({ json: { data: [], meta: { total: 0 } } }),
  );
  await page.goto("/console/connectors/");
  await page.getByRole("tab", { name: "Status", exact: true }).click();
  const progress = page.getByRole("region", {
    name: "From connection to evidence",
  });
  await expect(progress).toContainText("Choose your first evidence source");
  await expect(
    progress.getByRole("link", { name: "Open setup guide" }),
  ).toHaveAttribute("href", /onboarding/);
});
