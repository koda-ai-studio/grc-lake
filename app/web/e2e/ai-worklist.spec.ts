import { expect, test } from "@playwright/test";

test("model worklist exposes evidence gaps and follows only the selected asset", async ({
  page,
}) => {
  await page.route("**/api/v1/stream", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: "" }),
  );
  await page.route("**/api/v1/platform/ai-governance/inventory**", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            asset_id: "model:review",
            source_account_id: "source-a",
            asset_name: "Review model",
            asset_type: "model",
            owner: "Risk team",
            environment: "prod",
            model_card: false,
            lineage_complete: false,
            last_seen_at: "2026-10-10T12:00:00Z",
            sources: ["model_registry"],
            control_ids: ["SOC2-CC8.1"],
            event_types: ["model.lineage"],
          },
          {
            asset_id: "model:documented",
            asset_name: "Documented model",
            asset_type: "model",
            owner: "ML team",
            environment: "test",
            model_card: true,
            lineage_complete: true,
            last_seen_at: "2026-10-10T12:00:00Z",
            sources: ["model_registry"],
            control_ids: ["SOC2-CC6.1"],
            event_types: ["model.inventory"],
          },
        ],
      },
    }),
  );
  await page.goto("/console/ai-governance/");
  const worklist = page.getByRole("region", { name: "Models and agents" });
  await expect(
    worklist.getByText("Review model", { exact: true }),
  ).toBeVisible();
  await expect(
    worklist.getByText("Documented model", { exact: true }),
  ).toBeVisible();
  await worklist.getByRole("button", { name: "Inspect Review model" }).click();
  const detail = worklist.getByRole("region", { name: "Review model details" });
  await expect(detail).toContainText("Purpose, limitations and intended use");
  await expect(
    detail.getByRole("link", { name: "SOC2-CC8.1" }),
  ).toHaveAttribute("href", /id=SOC2-CC8.1/);
  await expect(detail.getByRole("link", { name: "SOC2-CC6.1" })).toHaveCount(0);
  await expect(detail).toContainText("Lineage recorded");
  await expect(detail).not.toContainText("Lineage complete");
  await expect(detail).not.toContainText("Failed");
  await page.route("**/api/v1/evidence?*", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    const base = json.data[0];
    await route.fulfill({
      json: {
        ...json,
        meta: { ...json.meta, count: 2, total: 2, returned: 2 },
        data: [
          {
            ...base,
            event_id: "selected-model-event",
            source_account_id: "source-a",
            tenant_id: "source-a",
            asset_id: "model:review",
            asset_name: "Review model",
          },
          {
            ...base,
            event_id: "other-model-event",
            asset_id: "model:review",
            source_account_id: "source-b",
            tenant_id: "source-b",
            asset_name: "Documented model",
          },
        ],
      },
    });
  });
  await detail.getByRole("link", { name: "View model evidence" }).click();
  await expect(page).toHaveURL(/asset=model%3Areview/);
  await expect(
    page.getByRole("heading", { name: "1 matching records" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table").getByText("Documented model", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Clear asset filter" }).click();
  await expect(
    page.getByRole("heading", { name: "2 matching records" }),
  ).toBeVisible();
});

for (const width of [390, 768, 1440]) {
  test(`AI worklist remains usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/console/ai-governance/");
    const worklist = page.getByRole("region", { name: "Models and agents" });
    await expect(
      worklist.getByRole("heading", { name: "Doc summarizer model" }),
    ).toBeVisible();
    await worklist
      .getByRole("button", { name: "Inspect Doc summarizer model" })
      .click();
    await expect(
      worklist.getByRole("link", { name: "View model evidence" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await worklist.getByLabel("Filter AI inventory").selectOption("agents");
    await expect(
      worklist.getByText("No observed assets match this filter."),
    ).toBeVisible();
    await worklist.getByLabel("Filter AI inventory").selectOption("all");
    await expect(
      worklist.getByRole("heading", { name: "Doc summarizer model" }),
    ).toBeVisible();
  });
}

test("canonical AI agents show runtime actions and stay out of model-card gaps", async ({
  page,
}) => {
  await page.route("**/api/v1/stream", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: "" }),
  );
  await page.route("**/api/v1/platform/ai-governance/inventory**", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            asset_id: "agent:finance-research",
            asset_name: "Finance research agent",
            asset_type: "ai_agent",
            owner: "Risk team",
            environment: "test",
            model_card: false,
            lineage_complete: false,
            last_seen_at: "2026-10-10T12:00:00Z",
            sources: ["runtime-gateway"],
            control_ids: [],
            event_types: ["runtime.tool_call"],
          },
        ],
      },
    }),
  );
  await page.goto("/console/ai-governance/");
  const worklist = page.getByRole("region", { name: "Models and agents" });
  await expect(
    worklist.getByText("Runtime recorded", { exact: true }),
  ).toBeVisible();
  await expect(
    worklist.getByText("Review tool activity", { exact: true }),
  ).toBeVisible();
  await worklist
    .getByLabel("Filter AI inventory")
    .selectOption("documentation");
  await expect(
    worklist.getByText("No observed assets match this filter."),
  ).toBeVisible();
  await worklist.getByLabel("Filter AI inventory").selectOption("agents");
  await worklist
    .getByRole("button", { name: "Inspect Finance research agent" })
    .click();
  await expect(
    worklist.getByRole("link", { name: "View agent evidence" }),
  ).toBeVisible();
});
