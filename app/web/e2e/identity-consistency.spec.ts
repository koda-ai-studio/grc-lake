import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"] as const) {
  for (const width of [390, 1440]) {
    test(`framework identities stay consistent in ${theme} at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((mode) => {
        localStorage.setItem("trustops:theme", JSON.stringify(mode));
      }, theme);
      await page.goto("/console/frameworks/");
      const reference = page
        .locator('img[src$="/frameworks/badges/nist-ai-rmf.svg"]')
        .first();
      await expect(reference).toBeVisible();
      const source = await reference.getAttribute("src");
      for (const route of ["ai-governance", "mapping-review"]) {
        await page.goto(`/console/${route}/`);
        if (route === "mapping-review")
          await page.getByRole("button", { name: /^Show all \d+/ }).click();
        const mark = page.locator(`img[src="${source}"]`).first();
        await expect(mark).toBeVisible({ timeout: 4000 });
        await expect(mark.locator("..")).toHaveAttribute(
          "aria-label",
          /NIST AI Risk Management Framework/,
        );
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth),
        ).toBeLessThanOrEqual(width);
      }
    });
  }
}

test("a control family keeps its recognition icon between overview and graph", async ({
  page,
}) => {
  await page.goto("/console/dashboard/");
  await page
    .getByRole("tab", { name: "Control families", exact: true })
    .click();
  const reference = page
    .locator('[data-family="identity"] summary svg')
    .first();
  await expect(reference).toBeVisible();
  const paths = await reference
    .locator("path")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("d")));
  await page.goto("/console/graph/");
  await page.getByLabel("Find a starting point").fill("identity");
  const root = page.getByLabel("Graph starting point", { exact: true });
  await expect(root.locator('option[value="family:identity"]')).toHaveCount(1);
  await root.selectOption("family:identity");
  const icon = page.locator(
    '.react-flow__node[data-id="family:identity"] [data-testid="graph-node-icon"] svg',
  );
  await expect(icon).toBeVisible();
  await expect
    .poll(
      () =>
        icon
          .locator("path")
          .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("d"))),
      { timeout: 4000 },
    )
    .toEqual(paths);
});
