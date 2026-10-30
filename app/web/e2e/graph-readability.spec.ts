import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function fittedZoom(page: import("@playwright/test").Page) {
  const viewport = page.locator(".react-flow__viewport");
  await expect(viewport).toBeVisible();
  await page.waitForTimeout(600);
  return viewport.evaluate(
    (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
  );
}

test("wide framework graphs retain visible icons without overlapping nodes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/graph/");
  await page
    .getByRole("button", { name: "Framework and repository maps" })
    .click();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  // The page opens on one control path; widen to the framework slice.
  await page.getByRole("button", { name: "Show whole framework" }).click();
  await expect
    .poll(() => page.locator(".react-flow__node").count())
    .toBeGreaterThan(60);
  await fittedZoom(page);
  // Exact records add nodes to the full map. Check the rendered icon size,
  // not a zoom threshold calibrated to the previous smaller cards.
  const icon = await page.getByTestId("graph-node-icon").first().boundingBox();
  expect(icon!.height).toBeGreaterThanOrEqual(22);
  const boxes = await page
    .locator(".react-flow__node")
    .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON()));
  const overlapping = boxes.filter((a, i) =>
    boxes.some(
      (b, j) =>
        j > i &&
        a.x < b.x + b.width &&
        b.x < a.x + a.width &&
        a.y < b.y + b.height &&
        b.y < a.y + a.height,
    ),
  );
  expect(overlapping).toHaveLength(0);
});

test("choosing All frameworks keeps the wide map", async ({ page }) => {
  await page.goto("/console/graph/");
  await page
    .getByRole("button", { name: "Framework and repository maps" })
    .click();
  const framework = page.getByRole("combobox", {
    name: "Filter graph by framework",
  });
  await expect(framework).toBeVisible({ timeout: 45_000 });
  await expect(framework).not.toHaveValue("");
  await framework.selectOption("");
  await page.waitForTimeout(500);
  await expect(framework).toHaveValue("");
});

for (const theme of ["light", "dark"]) {
  test(`investigation keeps context readable in ${theme} mode`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.addInitScript(
      (value) => localStorage.setItem("trustops:theme", JSON.stringify(value)),
      theme,
    );
    await page.goto("/console/graph/");
    await expect(
      page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]'),
    ).toContainText("Failing control");
    await expect
      .poll(() =>
        page.locator("html").evaluate((el) => el.classList.contains("dark")),
      )
      .toBe(theme === "dark");
    await page
      .locator('.react-flow__node[data-id="control:SOC2-CC6.1"]')
      .click();
    await expect(
      page.getByRole("complementary", { name: "Selected graph node" }),
    ).toBeVisible();
    await page
      .getByRole("heading", { name: "Evidence investigation", exact: true })
      .hover();
    await page.getByRole("button", { name: "Zoom In", exact: true }).click();
    const zoom = await fittedZoom(page);
    const labels = await page
      .getByTestId("graph-node-label")
      .evaluateAll((els) =>
        els.map((el) => ({
          size: parseFloat(getComputedStyle(el).fontSize),
          opacity: (() => {
            let value = 1;
            let at: Element | null = el;
            while (at && !at.classList.contains("react-flow__node")) {
              value *= Number(getComputedStyle(at).opacity);
              at = at.parentElement;
            }
            return value;
          })(),
        })),
      );
    expect(labels.length).toBeGreaterThan(5);
    for (const label of labels) {
      expect(label.size * zoom).toBeGreaterThanOrEqual(11);
      expect(label.opacity).toBe(1);
    }
    const boxes = await page
      .locator(".react-flow__node")
      .evaluateAll((els) =>
        els.map((el) => el.getBoundingClientRect().toJSON()),
      );
    expect(
      boxes.some((a, i) =>
        boxes.some(
          (b, j) =>
            j > i &&
            a.x < b.right &&
            b.x < a.right &&
            a.y < b.bottom &&
            b.y < a.bottom,
        ),
      ),
    ).toBe(false);
    const { violations } = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
      .disableRules(["svg-img-alt"])
      .analyze();
    expect(violations).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileZoom = await fittedZoom(page);
    const label = page.locator(
      '.react-flow__node[data-id="control:SOC2-CC6.1"] [data-testid="graph-node-label"]',
    );
    const fontSize = await label.evaluate((el) =>
      parseFloat(getComputedStyle(el).fontSize),
    );
    expect(fontSize * mobileZoom).toBeGreaterThanOrEqual(12);
    const card = (await label.boundingBox())!;
    const canvas = (await page.locator(".react-flow").boundingBox())!;
    expect(card.x).toBeGreaterThanOrEqual(canvas.x);
    expect(card.x + card.width).toBeLessThanOrEqual(canvas.x + canvas.width);
  });
}
