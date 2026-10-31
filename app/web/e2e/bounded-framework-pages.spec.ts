import { test, expect } from "@playwright/test";

test("framework catalog pages reset on search and preserve totals", async ({
  page,
}) => {
  await page.goto("/console/frameworks/");
  const catalog = page.getByRole("region", {
    name: "Framework catalog",
    exact: true,
  });
  const pages = catalog.getByRole("navigation", {
    name: "Framework catalog pages",
  });
  await expect(pages).toContainText("1–6 of 24");
  await expect(catalog.getByRole("button", { name: /^Inspect / })).toHaveCount(
    6,
  );
  await expect(
    pages.getByRole("button", { name: "Previous framework catalog page" }),
  ).toBeDisabled();
  await pages
    .getByRole("button", { name: "Next framework catalog page" })
    .click();
  await expect(pages).toContainText("7–12 of 24");
  await pages
    .getByRole("button", { name: "Next framework catalog page" })
    .click();
  await pages
    .getByRole("button", { name: "Next framework catalog page" })
    .click();
  await expect(pages).toContainText("19–24 of 24");
  await expect(
    pages.getByRole("button", { name: "Next framework catalog page" }),
  ).toBeDisabled();
  await catalog
    .getByRole("searchbox", { name: "Search frameworks" })
    .fill("NIST AI");
  await expect(pages).toContainText("1–1 of 1");
  await expect(catalog).toContainText("NIST AI Risk Management");
  await catalog.getByRole("searchbox").fill("no matching framework");
  await expect(pages).toContainText("0–0 of 0");
  await expect(catalog).toContainText("No frameworks match");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("safeguard results paginate and search the entire assessment", async ({
  page,
}) => {
  await page.goto("/console/frameworks/");
  await page
    .getByRole("button", { name: "Safeguard assessment · observed assets" })
    .click();
  const table = page.getByRole("table", {
    name: "Safeguard results in the published assessment",
  });
  const pages = page.getByRole("navigation", {
    name: "Safeguard results pages",
  });
  await expect(pages).toContainText("1–10 of 1200");
  await expect(table.getByRole("row")).toHaveCount(11);
  const first = await table.getByRole("row").nth(1).innerText();
  await pages
    .getByRole("button", { name: "Next safeguard results page" })
    .click();
  await expect(pages).toContainText("11–20 of 1200");
  await expect(table.getByRole("row").nth(1)).not.toHaveText(first);
  await page
    .getByRole("searchbox", { name: "Search safeguard results" })
    .fill("SG-IDENTITY-001");
  await expect(pages).toContainText("1–1 of 1");
  await expect(table.getByRole("row")).toHaveCount(2);
  await expect(table).toContainText("SG-IDENTITY-001");
});

test("secondary framework sections stay collapsed and page when opened", async ({
  page,
}) => {
  await page.goto("/console/frameworks/");
  const roster = page.getByRole("button", {
    name: "Framework roster",
    exact: true,
  });
  await expect(roster).toHaveAttribute("aria-expanded", "false");
  await roster.click();
  const pages = page.getByRole("navigation", {
    name: "Tracked frameworks pages",
  });
  await expect(pages).toContainText("1–6 of 22");
  await pages
    .getByRole("button", { name: "Next tracked frameworks page" })
    .click();
  await expect(pages).toContainText("7–12 of 22");
  await page.getByRole("button", { name: "Show readiness details" }).click();
  const readiness = page.getByRole("navigation", {
    name: "Readiness gates pages",
  });
  await expect(readiness).toContainText("1–6 of 22");
  await readiness
    .getByRole("button", { name: "Next readiness gates page" })
    .click();
  await expect(readiness).toContainText("7–12 of 22");
});

test("mobile catalog shows two cards per page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/console/frameworks/");
  const catalog = page.getByRole("region", {
    name: "Framework catalog",
    exact: true,
  });
  await expect(catalog.getByRole("button", { name: /^Inspect / })).toHaveCount(
    2,
  );
  const pages = catalog.getByRole("navigation", {
    name: "Framework catalog pages",
  });
  await expect(pages).toContainText("1–2 of 24");
  await pages
    .getByRole("button", { name: "Next framework catalog page" })
    .click();
  await expect(pages).toContainText("3–4 of 24");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
