import { expect, test } from "@playwright/test";

const routes = [
  "dashboard",
  "insights",
  "connectors",
  "evidence",
  "access-reviews",
  "vendor-risk",
  "controls",
  "frameworks",
  "mapping-review",
  "violations",
  "risks",
  "policies",
  "ai-governance",
  "crosswalk",
  "graph",
  "remediation",
  "automation",
  "agents",
  "audit-room",
  "trust-center",
  "audit-log",
  "auth",
  "deploy",
];

for (const route of routes) {
  test(`${route} keeps a single page heading and fits desktop and mobile`, async ({
    page,
  }) => {
    const crashes: string[] = [];
    page.on("pageerror", (error) => crashes.push(error.message));
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/console/${route}/`);
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(main.getByRole("heading", { level: 1 })).toBeVisible();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width + 1);
    }
    expect(crashes).toEqual([]);
  });
}
