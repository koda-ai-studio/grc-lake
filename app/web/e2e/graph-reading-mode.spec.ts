import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  for (const theme of ["light", "dark"]) {
    test(`explicit reading mode preserves flow at ${width}px in ${theme}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(
        (value) =>
          localStorage.setItem("trustops:theme", JSON.stringify(value)),
        theme,
      );
      await page.goto("/console/graph/");
      const nodes = page.locator(".react-flow__node");
      await expect(nodes).toHaveCount(20);
      const mode = page.getByRole("group", { name: "Graph reading mode" });
      await mode
        .getByRole("button", { name: "Readable view", exact: true })
        .click();
      await expect(
        mode.getByRole("button", { name: "Readable view", exact: true }),
      ).toHaveAttribute("aria-pressed", "true");
      const root = page.locator(
        '.react-flow__node[data-id="control:SOC2-CC6.1"]',
      );
      await expect
        .poll(async () => {
          const label = await root
            .getByTestId("graph-node-label")
            .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
          const zoom = await page
            .locator(".react-flow__viewport")
            .evaluate(
              (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
            );
          return label * zoom;
        })
        .toBeGreaterThanOrEqual(13);
      const canvas = (await page.locator(".react-flow").boundingBox())!;
      const card = (await root.boundingBox())!;
      expect(card.x).toBeGreaterThanOrEqual(canvas.x);
      expect(card.x + card.width).toBeLessThanOrEqual(canvas.x + canvas.width);
      await expect(nodes).toHaveCount(20);
      await expect(page.locator(".react-flow__edge-path")).toHaveCount(20);
      await expect(page.getByTestId("graph-overflow-hint")).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath("readable.png"),
        fullPage: true,
      });
      await mode
        .getByRole("button", { name: "Whole graph", exact: true })
        .click();
      await expect(
        mode.getByRole("button", { name: "Whole graph", exact: true }),
      ).toHaveAttribute("aria-pressed", "true");
      await expect
        .poll(() =>
          page.locator(".react-flow").evaluate((el) => {
            const bounds = el.getBoundingClientRect();
            return [...el.querySelectorAll(".react-flow__node")].every(
              (node) => {
                const rect = node.getBoundingClientRect();
                return (
                  rect.left >= bounds.left &&
                  rect.right <= bounds.right &&
                  rect.top >= bounds.top &&
                  rect.bottom <= bounds.bottom
                );
              },
            );
          }),
        )
        .toBe(true);
      await page.screenshot({
        path: testInfo.outputPath("whole.png"),
        fullPage: true,
      });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width + 1);
    });
  }
}

test("repository reading mode retains readable neighboring labels", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.goto("/console/graph/");
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "acme/model-service" })
    .dblclick();
  await expect(page.getByLabel("Current graph path")).toContainText(
    "1 level deeper",
  );
  await page
    .getByRole("group", { name: "Graph reading mode" })
    .getByRole("button", { name: "Readable view", exact: true })
    .click();
  await expect
    .poll(() =>
      page
        .locator(".react-flow__viewport")
        .evaluate(
          (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
        ),
    )
    .toBeGreaterThanOrEqual(1);
  const labels = await page
    .getByTestId("graph-node-label")
    .evaluateAll((els) =>
      els.map((el) => parseFloat(getComputedStyle(el).fontSize)),
    );
  expect(Math.min(...labels)).toBeGreaterThanOrEqual(13);
  await page.screenshot({
    path: testInfo.outputPath("repository-readable.png"),
    fullPage: true,
  });
  await page
    .getByRole("group", { name: "Graph reading mode" })
    .getByRole("button", { name: "Whole graph", exact: true })
    .click();
  await expect(page.getByTestId("graph-overflow-hint")).toBeHidden();
});
