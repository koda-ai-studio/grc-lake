import { expect, test } from "@playwright/test";

const MARKS =
  'header svg[aria-label="GRC Lake"], aside svg[aria-label="GRC Lake"], [role="dialog"] svg[aria-label="GRC Lake"]';

test("the app shell shows the brand mark once, in the top bar", async ({
  page,
}) => {
  await page.goto("/console/dashboard/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Overview", exact: true }),
  ).toBeVisible();

  const marks = page.locator(MARKS);
  await expect(marks).toHaveCount(1);
  await expect(page.locator('header svg[aria-label="GRC Lake"]')).toHaveCount(
    1,
  );
  // The original source glyphs and lake waves remain present in the compact mark.
  const header = page.locator('header svg[aria-label="GRC Lake"]');
  expect(await header.locator("circle").count()).toBe(3);
  expect(await header.locator("path").count()).toBe(5);
  await expect(
    page.getByRole("navigation", { name: "Breadcrumb" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Overview" }).first(),
  ).toHaveAttribute("aria-current", "page");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("aside").first()).toBeHidden();
  await page.getByRole("button", { name: "Open navigation" }).click();
  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await expect(drawer).toBeVisible();
  await expect(marks).toHaveCount(1);
  await drawer.getByRole("link", { name: "Graph" }).click();
  await expect(page).toHaveURL(/\/console\/graph\/?/);
  await expect(drawer).toBeHidden();
});

test("marks at 40px and below retain the original evidence-lake identity", async ({
  page,
}) => {
  await page.goto("/console/agents/");
  const marks = page.locator('svg[aria-label="GRC Lake"]');
  await expect(marks.first()).toBeVisible({ timeout: 20_000 });
  const sizes = await marks.evaluateAll((nodes) =>
    nodes.map((node) => ({
      size: Math.round(node.getBoundingClientRect().width),
      glyphs: node.querySelectorAll("circle").length,
    })),
  );
  expect(sizes.length).toBeGreaterThan(1);
  for (const mark of sizes.filter((m) => m.size > 0 && m.size <= 40)) {
    expect(mark.glyphs).toBe(3);
  }
});
