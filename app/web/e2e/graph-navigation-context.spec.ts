import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`roll up restores the parent's hop depth at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(
      (theme) => localStorage.setItem("trustops:theme", JSON.stringify(theme)),
      width === 390 ? "dark" : "light",
    );
    await page.route("**/api/v1/graph/investigation?*", async (route) => {
      const url = new URL(route.request().url());
      const root = url.searchParams.get("root") || "control:root";
      const nodes = [
        {
          id: "control:root",
          kind: "control",
          label: "Parent control",
          status: "not_evaluated",
        },
        {
          id: "evidence_type:child",
          kind: "evidence_type",
          label: "Child evidence",
        },
      ];
      await route.fulfill({
        json: {
          data: {
            nodes,
            edges: [
              {
                id: "edge",
                source: nodes[0].id,
                target: nodes[1].id,
                kind: "control_requires_evidence",
              },
            ],
            counts: { control: 1, evidence_type: 1 },
            root,
            version: "pinned-version",
            roots: [nodes[0]],
            root_count: 1,
            root_offset: 0,
            next_root_offset: null,
            depth: Number(url.searchParams.get("depth")),
            limit: 150,
            truncated: false,
            matching_nodes: 2,
            boundary: "Recorded relationships",
            framework_groups: [],
          },
        },
      });
    });
    await page.goto("/console/graph/");
    await page
      .getByText("Search and change starting point", { exact: true })
      .click();
    await page.getByLabel("Graph depth", { exact: true }).selectOption("1");
    await expect(page.getByLabel("Graph depth", { exact: true })).toHaveValue(
      "1",
    );
    await page
      .locator('.react-flow__node[data-id="evidence_type:child"]')
      .click();
    await page
      .getByRole("button", { name: "Focus this evidence path" })
      .click();
    await expect(page.getByLabel("Current graph path")).toContainText(
      "Child evidence",
    );
    await page.getByLabel("Graph depth", { exact: true }).selectOption("3");
    await expect(page.getByLabel("Graph depth", { exact: true })).toHaveValue(
      "3",
    );
    await page.getByRole("button", { name: "Roll up", exact: true }).click();
    await expect(page.getByLabel("Current graph path")).toContainText(
      "Parent control",
    );
    await expect(page.getByLabel("Graph depth", { exact: true })).toHaveValue(
      "1",
    );
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width + 1);
    if (width === 390) {
      const start = await page.getByLabel("Graph starting point").boundingBox();
      expect(start!.width).toBeGreaterThanOrEqual(180);
    }
    await page.screenshot({
      path: testInfo.outputPath("restored-graph.png"),
      fullPage: true,
    });
  });
}
