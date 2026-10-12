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

test("overview summarizes vendor decisions without duplicating the register", async ({
  page,
}) => {
  await page.route("**/api/v1/vendor-assessments*", (r) =>
    r.fulfill({
      json: {
        data: [
          {
            id: "v1",
            vendor_name: "Complete",
            status: "completed",
            due_at: "2020-01-01",
            risk_level: "high",
          },
          {
            id: "v2",
            vendor_name: "Overdue",
            status: "in_review",
            due_at: "2020-01-01",
            risk_level: "high",
          },
          {
            id: "v3",
            vendor_name: "New",
            status: "draft",
            due_at: null,
            risk_level: null,
          },
          {
            id: "v4",
            vendor_name: "Rejected",
            status: "rejected",
            due_at: "2020-01-01",
            risk_level: "critical",
          },
        ],
      },
    }),
  );
  await page.goto("/console/dashboard/");
  await expect(
    page.getByRole("tab", { name: "Vendor assessments", exact: true }),
  ).toHaveCount(0);
  const summary = page.getByRole("region", {
    name: "Vendor review priorities",
  });
  await expect(summary).toContainText(
    "2 awaiting review · 1 overdue · 1 high risk",
  );
  await expect(summary).toContainText("Counts cover recorded assessments only");
  await expect(summary.getByRole("link")).toHaveAttribute(
    "href",
    "/console/vendor-risk/",
  );
  await summary.getByRole("link").click();
  await expect(
    page.getByRole("heading", { name: "Vendor risk", exact: true }),
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
