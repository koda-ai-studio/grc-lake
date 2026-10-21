import { expect, test } from "@playwright/test";

for (const view of ["setup", "connected", "provider"] as const) {
  test(`partial collection remains visible in ${view} run history`, async ({
    page,
  }) => {
    const connectorId = view === "provider" ? "github-security" : "aws-posture";
    const message = "Read access did not cover the selected scope.";
    const run = {
      connector_id: connectorId,
      kind: "sync",
      result: "error",
      actor: "test",
      evidence_count: 3,
      occurred_at: new Date().toISOString(),
      error: "Partial collection",
      duration_ms: 10,
      access_fingerprint: null,
      metadata: { coverage_gaps: [{ message }] },
    };
    await page.route("**/api/v1/connectors?*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const connector = body.data.find(
        (row: { connector_id: string }) => row.connector_id === connectorId,
      );
      body.data = [
        {
          ...connector,
          state: view === "setup" ? "disabled" : "enabled",
          last_sync: run,
        },
      ];
      body.meta = { ...body.meta, count: 1, total: 1, next_cursor: null };
      await route.fulfill({ response, json: body });
    });
    await page.route(`**/api/v1/connectors/${connectorId}/runs*`, (route) =>
      route.fulfill({ json: { data: [run], meta: { next_cursor: null } } }),
    );
    await page.goto(`/console/connectors/?connect=${connectorId}`);
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    if (view === "provider")
      await dialog.getByText("Run history", { exact: true }).click();
    else await dialog.getByRole("tab", { name: /^Runs/ }).click();
    await expect(dialog.getByText(message, { exact: true })).toBeVisible();
    await expect(
      dialog.getByText("Partial collection · 1 coverage gap", { exact: true }),
    ).toBeVisible();
  });
}
