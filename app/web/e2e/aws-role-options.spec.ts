import { expect, test } from "@playwright/test";

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

// Mock provider access and configuration; no AWS API or shared-lake mutation.
// Python contracts cover persisted configuration, fixture sync and replay.
for (const width of [1280, 390]) {
  test(`AWS connected configuration saves optional role policy scope at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    let options: Record<string, unknown> = {
      include_role_policies: false,
    };
    let saved: Record<string, unknown> | undefined;
    await page.route(/\/api\/v1\/connectors(?:\?.*)?$/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.data = body.data.map((row: { connector_id: string }) =>
        row.connector_id === "aws-posture"
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
    await page.route("**/connectors/aws-posture/probe", async (route) => {
      await route.fulfill({
        status: 201,
        json: {
          data: {
            connector_id: "aws-posture",
            kind: "probe",
            result: "ok",
            metadata: { probe_mode: "config_only" },
          },
        },
      });
    });
    await page.route("**/connectors/aws-posture/configure", async (route) => {
      saved = route.request().postDataJSON();
      options = saved!.options as Record<string, unknown>;
      await route.fulfill({
        status: 201,
        json: { data: { ...saved, connector_id: "aws-posture" } },
      });
    });
    await page.goto("/console/connectors/?connect=aws-posture");
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("tab", { name: "Config", exact: true }).click();
    const checkbox = dialog.getByRole("checkbox", {
      name: "Collect IAM role policies",
    });
    await expect(checkbox).not.toBeChecked();
    await expect(dialog).toContainText("six additional IAM read permissions");
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
      .toEqual(expect.objectContaining({ include_role_policies: "true" }));
    await expect(page.getByText(/AWS Posture changes saved/)).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
