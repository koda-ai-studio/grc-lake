import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  for (const theme of ["light", "dark"]) {
    test(`safeguard coverage at ${width}px in ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(
        (value) =>
          localStorage.setItem("trustops:theme", JSON.stringify(value)),
        theme,
      );
      await page.route("**/api/v1/graph/investigation?*", async (route) => {
        const response = await route.fetch();
        const payload = await response.json();
        const node = payload.data.nodes.find(
          (item: { id: string }) => item.id === "safeguard:SG-IDENTITY-001",
        );
        Object.assign(node, {
          required_evidence_types: ["identity.mfa"],
          applicable_asset_count: 3,
          assessed_asset_count: 1,
          unassessed_asset_count: 2,
          invalid_binding_count: 1,
        });
        await route.fulfill({ response, json: payload });
      });
      await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
      await page
        .locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]')
        .click();
      const coverage = page.getByRole("region", {
        name: "Safeguard evidence coverage",
      });
      await expect(coverage).toContainText("identity.mfa");
      await expect(coverage.getByTestId("applicable_asset_count")).toHaveText(
        "3",
      );
      await expect(coverage.getByTestId("unassessed_asset_count")).toHaveText(
        "2",
      );
      await expect(coverage).toContainText("Assessed does not mean passing");
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width + 1);
      await coverage.screenshot({
        path: `../../build/safeguard-coverage-${width}-${theme}.png`,
      });
    });
  }
}

test("missing assessment and contract stay explicit", async ({ page }) => {
  await page.route("**/api/v1/graph/investigation?*", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    const node = payload.data.nodes.find(
      (item: { id: string }) => item.id === "safeguard:SG-IDENTITY-001",
    );
    for (const field of [
      "required_evidence_types",
      "applicable_asset_count",
      "assessed_asset_count",
      "unassessed_asset_count",
      "invalid_binding_count",
    ])
      delete node[field];
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
  await page
    .locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]')
    .click();
  const coverage = page.getByRole("region", {
    name: "Safeguard evidence coverage",
  });
  await expect(coverage.getByTestId("assessed_asset_count")).toHaveText(
    "Not recorded",
  );
  await expect(coverage).toContainText("No required evidence types declared");
});
