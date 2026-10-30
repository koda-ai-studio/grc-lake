import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`organization selects arbitrary accounts at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/v1/connectors?*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const base = body.data.find(
        (r: { connector_id: string }) => r.connector_id === "aws-posture",
      );
      body.data = ["a", "b", "c"].map((id) => ({
        ...base,
        connection_id: id,
        name: `Account ${id.toUpperCase()}`,
        source_account_id: id,
      }));
      await route.fulfill({ response, json: body });
    });
    let saved: Record<string, unknown> = {};
    await page.route("**/api/v1/organizations", async (route) => {
      if (route.request().method() === "POST") {
        saved = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          json: { data: { ...saved, revision: 1 }, meta: {}, errors: [] },
        });
      } else await route.fulfill({ json: { data: [], meta: {}, errors: [] } });
    });
    await page.goto("/console/connectors/");
    await page
      .getByRole("button", { name: "New organization scope", exact: true })
      .click();
    await page.getByLabel("Organization ID", { exact: true }).fill("org");
    await page
      .getByLabel("Organization name", { exact: true })
      .fill("Organization");
    await page
      .getByRole("checkbox", { name: "Account A · a", exact: true })
      .check();
    await page
      .getByRole("checkbox", { name: "Account C · c", exact: true })
      .check();
    await page.getByRole("button", { name: "Save scope", exact: true }).click();
    await expect.poll(() => saved.connection_ids).toEqual(["a", "c"]);
    expect(saved).toEqual({
      organization_id: "org",
      name: "Organization",
      connection_ids: ["a", "c"],
      expected_revision: 0,
    });
    await expect(
      page.getByRole("button", {
        name: "Collect selected accounts",
        exact: true,
      }),
    ).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("organization-scope.png"),
      fullPage: true,
    });
    await page.unrouteAll({ behavior: "wait" });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}
