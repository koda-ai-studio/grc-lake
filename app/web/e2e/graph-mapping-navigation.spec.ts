import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  for (const theme of ["light", "dark"]) {
    test(`safeguard mapping review states remain distinct at ${width}px ${theme}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(
        (value) =>
          localStorage.setItem("trustops:theme", JSON.stringify(value)),
        theme,
      );
      await page.route("**/api/v1/graph/investigation?*", async (route) => {
        const response = await route.fetch();
        const payload = await response.json();
        const root = payload.data.nodes.find(
          (node: { id: string }) => node.id === "safeguard:SG-IDENTITY-001",
        );
        const ids = ["SOC2-CC6.1", "SOC2-CC6.2", "SOC2-CC6.3", "SOC2-CC6.4"];
        payload.data.nodes = [
          root,
          ...ids.map((id) => ({
            id: `control:${id}`,
            kind: "control",
            label: id,
            framework_id: "soc2",
            status: "not_evaluated",
          })),
          {
            id: "control:unrelated",
            kind: "control",
            label: "Unrelated requirement",
          },
        ];
        payload.data.edges = ids.map((id, index) => ({
          id: `mapping-${index}`,
          source: `control:${id}`,
          target: root.id,
          kind: "maps_to",
          review_state: ["reviewed", "proposed", undefined, "reviewed"][index],
        }));
        await route.fulfill({ response, json: payload });
      });
      await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
      await page
        .locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]')
        .click();
      const region = page.getByRole("region", {
        name: "Mapped framework requirements",
      });
      await expect(region).toContainText("Loaded graph only");
      await expect(
        region.getByRole("button", { name: /SOC2-CC6.1/ }),
      ).toContainText("Reviewed mapping");
      await expect(
        region.getByRole("button", { name: /SOC2-CC6.2/ }),
      ).toContainText("Proposed — not attestable");
      await expect(
        region.getByRole("button", { name: /SOC2-CC6.3/ }),
      ).toContainText("Review state not recorded");
      await expect(region).not.toContainText("Unrelated requirement");
      await region.screenshot({ path: testInfo.outputPath("mappings.png") });
      await region
        .getByRole("button", { name: "Next mapped requirements page" })
        .click();
      await region.getByRole("button", { name: /SOC2-CC6.4/ }).click();
      await expect(
        page
          .getByTestId("graph-node-inspector")
          .getByRole("link", { name: "Open controls workbench" }),
      ).toHaveAttribute("href", /id=SOC2-CC6.4/);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width + 1);
    });
  }
}

test("absent loaded mappings do not claim no mapping exists", async ({
  page,
}) => {
  await page.route("**/api/v1/graph/investigation?*", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.data.edges = payload.data.edges.filter(
      (edge: { kind: string }) => edge.kind !== "maps_to",
    );
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
  await page
    .locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]')
    .click();
  await expect(
    page.getByRole("region", { name: "Mapped framework requirements" }),
  ).toContainText("No requirement mappings loaded in this view");
});
