import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  for (const theme of ["light", "dark"]) {
    test(`safeguard follows exact recorded bindings at ${width}px ${theme}`, async ({
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
        payload.data.nodes = [
          root,
          ...["a", "b"].map((account) => ({
            id: `evidence:${account}`,
            kind: "evidence",
            label: "MFA observation",
            event_id: `event-${account}`,
            source_account_id: `account-${account}`,
            status: "observed",
          })),
          {
            id: "evidence:unrelated",
            kind: "evidence",
            label: "Unrelated observation",
          },
        ];
        payload.data.edges = ["a", "b"].map((account) => ({
          id: `binding-${account}`,
          source: root.id,
          target: `evidence:${account}`,
          kind: "has_evidence",
          ...(account === "b" ? { binding: "invalid_asset_type" } : {}),
        }));
        await route.fulfill({ response, json: payload });
      });
      await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
      await page
        .locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]')
        .click();
      const region = page.getByRole("region", {
        name: "Safeguard evidence bindings",
      });
      await expect(region).toContainText("Loaded graph only");
      await expect(region).toContainText("Invalid binding");
      await expect(region).not.toContainText("Unrelated observation");
      await expect(region.getByRole("button")).toHaveCount(2);
      await region.screenshot({ path: testInfo.outputPath("bindings.png") });
      await region.getByRole("button", { name: /account-b/ }).click();
      const inspector = page.getByTestId("graph-node-inspector");
      await expect(inspector).toContainText("Source account: account-b");
      await expect(
        inspector.getByRole("link", { name: "Open evidence room" }),
      ).toHaveAttribute("href", /id=event-b/);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width + 1);
    });
  }
}

test("an empty graph slice does not assert missing evidence", async ({
  page,
}) => {
  await page.route("**/api/v1/graph/investigation?*", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.data.edges = payload.data.edges.filter(
      (edge: { kind: string }) => edge.kind !== "has_evidence",
    );
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
  await page
    .locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]')
    .click();
  await expect(
    page.getByRole("region", { name: "Safeguard evidence bindings" }),
  ).toContainText("No evidence bindings loaded in this view");
});
