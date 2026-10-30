import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`inspecting a hidden relationship restores its layer and exact account at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const nodes = [
      { id: "control:c", kind: "control", label: "SOC2-CC6.1", status: "open" },
      {
        id: "evidence:e",
        kind: "evidence_type",
        label: "Branch protection",
        status: "observed",
      },
      {
        id: "source:a",
        kind: "source",
        label: "GitHub",
        source_account_id: "account-a",
      },
      {
        id: "source:b",
        kind: "source",
        label: "GitHub",
        source_account_id: "account-b",
      },
      { id: "asset:a", kind: "repository", label: "example/model-service" },
    ];
    const edges = [
      {
        id: "requires",
        source: "control:c",
        target: "evidence:e",
        kind: "control_requires_evidence",
      },
      {
        id: "source-a",
        source: "source:a",
        target: "evidence:e",
        kind: "produces",
      },
      {
        id: "source-b",
        source: "source:b",
        target: "evidence:e",
        kind: "produces",
      },
      {
        id: "asset",
        source: "evidence:e",
        target: "asset:a",
        kind: "evidence_covers_asset",
      },
    ];
    // A loaded snapshot may retain nodes hidden by the local layer filter.
    await page.route("**/api/v1/graph/investigation?*", (route) =>
      route.fulfill({
        json: {
          data: {
            nodes,
            edges,
            counts: {},
            root: "control:c",
            roots: [nodes[0]],
            root_count: 1,
            root_offset: 0,
            version: "related-records",
            depth: 2,
            limit: 150,
            truncated: false,
            matching_nodes: nodes.length,
            boundary: "Recorded relationships",
            framework_groups: [],
          },
        },
      }),
    );
    await page.goto("/console/graph/");
    await expect(page.locator(".react-flow__node")).toHaveCount(5);
    await page
      .getByText("Search and change starting point", { exact: true })
      .click();
    await page
      .getByText("Visible relationship layers", { exact: true })
      .click();
    const sourceLayer = page.getByRole("checkbox", {
      name: "source",
      exact: true,
    });
    await sourceLayer.uncheck();
    await page.getByRole("checkbox", { name: "vendor", exact: true }).uncheck();
    await expect(
      page.locator('.react-flow__node[data-id^="source:"]'),
    ).toHaveCount(0);
    await page.locator('.react-flow__node[data-id="evidence:e"]').click();
    await page
      .getByRole("button", { name: "Focus direct relationships", exact: true })
      .click();
    await page
      .getByText("Selected relationships and mapping review state", {
        exact: true,
      })
      .click();
    await page
      .getByRole("button", { name: "Inspect GitHub in account-b", exact: true })
      .click();
    await expect(sourceLayer).toBeChecked();
    await expect(
      page.getByRole("checkbox", { name: "vendor", exact: true }),
    ).not.toBeChecked();
    const selected = page.locator('.react-flow__node[data-id="source:b"]');
    await expect(selected).toBeVisible();
    await expect(selected).toHaveClass(/selected/);
    await expect(
      page.locator('.react-flow__node[data-id="source:a"]'),
    ).toBeVisible();
    await expect(page.locator(".react-flow__node")).toHaveCount(5);
    await expect(page.locator(".react-flow__edge-path")).toHaveCount(4);
    await expect(
      page.getByRole("complementary", { name: "Selected graph node" }),
    ).toContainText("account-b");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      ),
    ).toBe(0);
  });
}
