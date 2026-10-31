import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`named account selection and creation at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const requested: string[] = [];
    await page.route("**/api/v1/connectors?*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const base = body.data.find(
        (row: { connector_id: string }) => row.connector_id === "aws-posture",
      );
      body.data = ["a", "b", "c"].map((id) => ({
        ...base,
        connection_id: `account-${id}`,
        source_account_id: id,
        name: `Account ${id.toUpperCase()}`,
        state: "disabled",
        last_probe: null,
        last_sync: null,
        configured_options: {},
      }));
      body.meta = { ...body.meta, count: 3, total: 3, next_cursor: null };
      await route.fulfill({ response, json: body });
    });
    await page.route("**/api/v1/connections/*/runs*", async (route) => {
      requested.push(new URL(route.request().url()).pathname);
      await route.fulfill({ json: { data: [], meta: {}, errors: [] } });
    });
    await page.goto("/console/connectors/");
    await page
      .getByRole("button", { name: "Open Account C", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText("Account C");
    await expect
      .poll(() =>
        requested.some((url) => url.includes("/connections/account-c/runs")),
      )
      .toBe(true);
    await page.keyboard.press("Escape");
    await page
      .getByRole("tab", { name: "Accounts & scope", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Add account connection", exact: true })
      .click();
    await page.getByLabel("Connection ID", { exact: true }).fill("account-d");
    await page.getByLabel("Connection name", { exact: true }).fill("Account D");
    await page.getByLabel("Source account ID", { exact: true }).fill("d");
    let created: Record<string, unknown> = {};
    await page.route("**/api/v1/connections", async (route) => {
      created = route.request().postDataJSON();
      await route.fulfill({
        status: 201,
        json: { data: created, meta: {}, errors: [] },
      });
    });
    await page
      .getByRole("button", { name: "Create connection", exact: true })
      .click();
    await expect.poll(() => created.connection_id).toBe("account-d");
    expect(created.source_account_id).toBe("d");
    await expect(
      page.getByRole("button", { name: "Add account connection", exact: true }),
    ).toBeVisible();
    await page.unrouteAll({ behavior: "wait" });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
