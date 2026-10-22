import { expect, test } from "@playwright/test";

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

// Mock provider access and configuration; no Google API or shared-lake mutation.
// Python contracts cover persisted configuration, fixture sync and replay.
for (const width of [1280, 390]) {
  test(`GCP connected configuration saves optional identity scope at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    let options: Record<string, unknown> = {
      include_non_human_identities: false,
    };
    let saved: Record<string, unknown> | undefined;
    await page.route(/\/api\/v1\/connectors(?:\?.*)?$/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.data = body.data.map((row: { connector_id: string }) =>
        row.connector_id === "gcp-posture"
          ? {
              ...row,
              state: "enabled",
              credential_fingerprint: "fixture-credential",
              configured_options: options,
            }
          : row,
      );
      await route.fulfill({ response, json: body });
    });
    await page.route("**/connectors/gcp-posture/probe", async (route) => {
      await route.fulfill({
        status: 201,
        json: {
          data: {
            connector_id: "gcp-posture",
            kind: "probe",
            result: "ok",
            metadata: { probe_mode: "config_only" },
          },
        },
      });
    });
    await page.route("**/connectors/gcp-posture/configure", async (route) => {
      saved = route.request().postDataJSON();
      options = saved!.options as Record<string, unknown>;
      await route.fulfill({
        status: 201,
        json: { data: { ...saved, connector_id: "gcp-posture" } },
      });
    });
    await page.goto("/console/connectors/?connect=gcp-posture");
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("tab", { name: "Config", exact: true }).click();
    const checkbox = dialog.getByRole("checkbox", {
      name: "Collect service accounts",
    });
    await expect(checkbox).not.toBeChecked();
    await expect(dialog).toContainText("iam.serviceAccounts.list");
    await checkbox.check();
    await dialog
      .getByRole("button", { name: "Test connection", exact: true })
      .click();
    const save = dialog.getByRole("button", {
      name: "Save changes",
      exact: true,
    });
    await expect(save).toBeEnabled();
    await save.click();
    await expect
      .poll(() => saved?.options)
      .toEqual(
        expect.objectContaining({ include_non_human_identities: "true" }),
      );
    await expect(page.getByText(/GCP Posture changes saved/)).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
