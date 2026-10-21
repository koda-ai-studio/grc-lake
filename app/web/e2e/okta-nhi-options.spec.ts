import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`Okta metadata collection is opt-in and persists at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await request.post("/api/v1/connectors/okta-identity/configure", {
      data: {
        state: "disabled",
        actor: "e2e",
        options: { include_non_human_identities: false },
      },
    });
    await page.goto("/console/connectors/?connect=okta-identity");
    const dialog = page.getByRole("dialog");
    const option = dialog.getByRole("checkbox", {
      name: "Collect non-human identities",
    });
    await expect(option).not.toBeChecked();
    await expect(dialog).toContainText("credential values are excluded");
    await option.check();
    await dialog.getByLabel(/Okta org URL/).fill("https://fixture.okta.com");
    await dialog
      .getByLabel(/API token env var/)
      .fill("GRC_LAKE_TENANT_INSECURE__OKTA_TOKEN");
    await dialog.getByRole("button", { name: "Next: test access" }).click();
    await dialog.getByRole("button", { name: "Test connection" }).click();
    const enable = dialog.getByRole("button", {
      name: "Enable connector",
      exact: true,
    });
    await expect(enable).toBeEnabled();
    await enable.click();
    await expect(page.getByText(/Okta Identity enabled/i)).toBeVisible();
    const connectors = (await (await request.get("/api/v1/connectors")).json())
      .data;
    const saved = connectors.find(
      (row: { connector_id: string }) => row.connector_id === "okta-identity",
    );
    expect(saved.configured_options.include_non_human_identities).toBe("true");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
