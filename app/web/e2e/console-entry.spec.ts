import { expect, test } from "@playwright/test";

for (const entry of ["/", "/console", "/console/"]) {
  test(`${entry} opens the packaged dashboard`, async ({ page }) => {
    await page.goto(entry);
    await expect(page).toHaveURL(/\/console\/dashboard\/$/);
    await expect(
      page.getByRole("heading", { name: "Overview", exact: true, level: 1 }),
    ).toBeVisible();
  });
}
