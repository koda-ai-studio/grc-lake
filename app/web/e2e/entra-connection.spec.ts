import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`Entra preview setup saves tenant-bound identity references at ${width}px`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const reset = await request.post(
      "/api/v1/connectors/entra-identity/configure",
      {
        data: { state: "disabled", actor: "e2e", credentials: {} },
      },
    );
    expect(reset.ok()).toBe(true);
    await page.goto("/console/connectors/?connect=entra-identity");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Application.Read.All");
    await expect(dialog).toContainText(
      "Azure subscription Reader access does not grant",
    );
    await dialog
      .getByLabel(/Microsoft Entra tenant ID/)
      .fill("22222222-2222-2222-2222-222222222222");
    await dialog
      .getByText("Advanced identity and scope", { exact: true })
      .click();
    await dialog
      .getByLabel(/App registration client ID/)
      .fill("33333333-3333-3333-3333-333333333333");
    await dialog
      .getByLabel(/Client secret env var/)
      .fill("GRC_LAKE_TENANT_INSECURE__AZURE_SECRET");
    await dialog.getByRole("button", { name: "Next: test access" }).click();
    await dialog.getByRole("button", { name: "Test connection" }).click();
    const enable = dialog.getByRole("button", {
      name: "Enable connector",
      exact: true,
    });
    await expect(enable).toBeEnabled();
    const savedRequest = page.waitForRequest(
      (req) =>
        req.method() === "POST" &&
        req.url().endsWith("/entra-identity/configure"),
    );
    const savedResponse = page.waitForResponse(
      (res) =>
        res.request().method() === "POST" &&
        res.url().endsWith("/entra-identity/configure"),
    );
    await enable.click();
    expect((await savedResponse).ok()).toBe(true);
    const submitted = (await savedRequest).postDataJSON().credentials;
    const rows = (await (await request.get("/api/v1/connectors")).json()).data;
    const saved = rows.find(
      (row: { connector_id: string }) => row.connector_id === "entra-identity",
    );
    expect(saved.state).toBe("enabled");
    expect(saved.release_stage).toBe("preview");
    expect(submitted.tenant_id).toBe("22222222-2222-2222-2222-222222222222");
    expect(submitted.client_secret_ref).toBe(
      "GRC_LAKE_TENANT_INSECURE__AZURE_SECRET",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
