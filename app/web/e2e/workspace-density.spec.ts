import { test, expect } from "@playwright/test";

test("sources use the full workspace and keep long provider names inside their panel", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/console/dashboard/");
  await page
    .getByRole("tab", { name: "Sources & operations", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Latest lake assessment" }),
  ).toBeHidden();
  const panel = page.getByRole("tabpanel", {
    name: "Sources & operations",
    exact: true,
  });
  expect((await panel.boundingBox())!.width).toBeGreaterThan(850);
  await expect(
    page.getByRole("navigation", { name: "Evidence sources pages" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Next evidence sources page" })
    .click();
  await expect(
    page
      .getByRole("navigation", { name: "Evidence sources pages" })
      .getByRole("status"),
  ).toHaveText("9–9 of 9");
  await page
    .getByRole("tab", { name: "Health & freshness", exact: true })
    .click();
  await expect(
    page.getByRole("tabpanel", { name: "Evidence sources", exact: true }),
  ).toBeHidden();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("vendor assessment pagination preserves evidence boundaries and resets after search", async ({
  page,
}) => {
  await page.route("**/api/v1/vendor-assessments*", (r) =>
    r.fulfill({
      json: {
        data: Array.from({ length: 11 }, (_, i) => ({
          id: `v${i}`,
          vendor_name: `Vendor ${i + 1}`,
          status: i === 0 ? "completed" : "draft",
          owner: "Review owner",
          control_id: "SOC2-CC9.2",
          completed_at: i === 0 ? "2026-10-10T12:00:00Z" : null,
          due_at: null,
        })),
      },
    }),
  );
  await page.goto("/console/dashboard/");
  await page
    .getByRole("tab", { name: "Vendor assessments", exact: true })
    .click();
  await expect(
    page.getByText(/11 named vendors · 1 completed assessments/),
  ).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(8);
  await page
    .getByRole("button", { name: "Next vendor assessments page" })
    .click();
  await expect(page.getByRole("article")).toHaveCount(3);
  await page.getByLabel("Search vendor assessments").fill("Vendor 2");
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(
    page.getByRole("heading", { name: "Vendor 2", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Previous vendor assessments page" }),
  ).toHaveCount(0);
  await expect(
    page.getByText(/do not establish a complete vendor inventory/),
  ).toBeVisible();
});

test("finding pagination moves between bounded pages", async ({ page }) => {
  await page.goto("/console/violations/");
  const paging = page.getByRole("navigation", { name: "Findings queue pages" });
  await expect(paging).toBeVisible();
  await paging
    .getByRole("button", { name: "Next findings queue page" })
    .click();
  await expect(paging.getByRole("status")).toHaveText(/9–16 of/);
  await paging
    .getByRole("button", { name: "Previous findings queue page" })
    .click();
  await expect(paging.getByRole("status")).toHaveText(/1–8 of/);
});

test("GitHub source marks follow the readable foreground in dark mode", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("trustops:theme", JSON.stringify("dark")),
  );
  await page.goto("/console/dashboard/");
  await page
    .getByRole("tab", { name: "Sources & operations", exact: true })
    .click();
  const mark = page
    .getByRole("img", { name: "GitHub connector", exact: true })
    .first()
    .locator("path");
  await expect(mark).toBeVisible();
  expect(await mark.evaluate((el) => getComputedStyle(el).fill)).toEqual(
    await page.locator("main").evaluate((el) => getComputedStyle(el).color),
  );
});
