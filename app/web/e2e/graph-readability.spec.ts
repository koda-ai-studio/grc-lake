import { expect, test } from "@playwright/test";

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
