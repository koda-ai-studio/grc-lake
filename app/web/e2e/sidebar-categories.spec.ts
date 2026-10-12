import { expect, test } from "@playwright/test";

test("sidebar collapse is prominent and category icons stay useful in compact mode", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/console/dashboard/");
  const sidebar = page.getByRole("complementary", { name: "Console sidebar" });
  const toggle = sidebar.getByRole("button", { name: "Collapse sidebar" });
  const bounds = await sidebar.boundingBox();
  expect((await toggle.boundingBox())!.y).toBeLessThan(bounds!.y + 56);
  const nav = sidebar.getByRole("navigation", { name: "Primary" });
  for (const name of [
    "Overview",
    "Collect",
    "Evaluate",
    "Resolve",
    "Governance",
    "Review & export",
    "Settings",
  ]) {
    await expect(
      nav.getByRole("button", { name, exact: true }).locator("svg").first(),
    ).toBeVisible();
  }
  await toggle.click();
  await expect(sidebar).toHaveCSS("width", "64px");
  await expect(nav.getByRole("button")).toHaveCount(7);
  await expect(nav.getByRole("link")).toHaveCount(0);
  expect(await nav.evaluate((el) => el.scrollHeight <= el.clientHeight)).toBe(
    true,
  );
  const governance = nav.getByRole("button", {
    name: "Governance",
    exact: true,
  });
  await governance.focus();
  await governance.press("Enter");
  const menu = page.getByRole("menu", { name: "Governance", exact: true });
  await expect(menu).toBeVisible();
  await menu
    .getByRole("menuitem", { name: "Access reviews", exact: true })
    .click();
  await expect(page).toHaveURL(/\/console\/access-reviews\/$/);
  await page.reload();
  await expect(sidebar).toHaveCSS("width", "64px");
  await expect(governance).toHaveAttribute("aria-current", "true");
  await governance.focus();
  await governance.press("Enter");
  await page.keyboard.press("Escape");
  await expect(governance).toBeFocused();
  await sidebar.getByRole("button", { name: "Expand sidebar" }).click();
  await expect(
    nav.getByRole("link", { name: "Access reviews", exact: true }),
  ).toHaveAttribute("aria-current", "page");
});
