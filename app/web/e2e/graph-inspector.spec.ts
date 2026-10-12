import { expect, test } from "@playwright/test";

test("selected evidence path keeps an adjacent inspector and restores context", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/graph/");
  await page.getByRole("button", { name: "Show whole framework" }).click();
  const nodes = page.locator(".react-flow__node");
  await expect.poll(() => nodes.count()).toBeGreaterThan(60);
  const wholeCount = await nodes.count();
  // A mapping row selects a control without requiring precise canvas gestures.
  const mapping = page
    .getByText("Mapping inspector", { exact: true })
    .locator("../..");
  await mapping.locator("button").first().click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(inspector).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await inspector
    .getByRole("button", { name: "Focus this evidence path" })
    .click();
  await expect.poll(() => nodes.count()).toBeLessThan(wholeCount);
  await expect(nodes.first()).toBeVisible();
  await expect(inspector).toBeVisible();
  const canvasBox = await page.locator(".react-flow").boundingBox();
  const inspectorBox = await inspector.boundingBox();
  expect(inspectorBox!.x).toBeGreaterThanOrEqual(
    canvasBox!.x + canvasBox!.width,
  );
  await page.getByRole("button", { name: "Show whole framework" }).click();
  await expect(nodes).toHaveCount(wholeCount);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(inspector).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(391);
  await inspector.getByRole("button", { name: "Close node details" }).click();
  await expect(inspector).toHaveCount(0);
});

test("canvas nodes open details by mouse and keyboard", async ({ page }) => {
  await page.goto("/console/graph/");
  const node = page
    .locator(".react-flow__node")
    .filter({ hasText: "SOC2-CC6.1" });
  await expect(node).toHaveCount(1);
  // A straight vertical SVG path has a zero-width bounding box even when its stroke renders.
  const edge = page.locator(".react-flow__edge-path").first();
  await expect(edge).toHaveAttribute("d", /^M/);
  await expect
    .poll(() =>
      edge.evaluate((element) => (element as SVGPathElement).getTotalLength()),
    )
    .toBeGreaterThan(0);
  await node.click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(
    inspector.getByRole("heading", { name: "SOC2-CC6.1", exact: true }),
  ).toBeVisible();
  await inspector.getByRole("button", { name: "Close node details" }).click();
  await expect(inspector).toHaveCount(0);
  await node.press("Enter");
  await expect(inspector).toBeVisible();
});
