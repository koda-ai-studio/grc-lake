import { expect, test } from "@playwright/test";

test("bounded investigation expands exact relationships with visible icons", async ({
  page,
}) => {
  let responseNodes = 0;
  page.on("response", async (response) => {
    if (response.url().includes("/graph/investigation") && response.ok())
      responseNodes = (await response.json()).data.nodes.length;
  });
  await page.goto("/console/graph/");
  await expect(
    page.getByRole("heading", { name: "Evidence investigation" }),
  ).toBeVisible();
  await expect(page.getByTestId("graph-node-icon").first()).toBeVisible();
  expect(responseNodes).toBeLessThanOrEqual(150);
  await page.getByLabel("Graph depth").selectOption("1");
  await page.locator(".react-flow__node").first().click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(inspector).toBeVisible();
  await inspector
    .getByRole("button", { name: "Focus this evidence path" })
    .click();
  await expect(
    page.getByText(/Recorded relationships; not network reachability/),
  ).toBeVisible();
  await expect
    .poll(() => page.locator(".react-flow__edge-path").count())
    .toBeGreaterThan(0);
});

test("every catalog provider opens the shared setup or cloud preparation", async ({
  page,
  request,
}) => {
  const response = await request.get("/api/v1/connectors");
  expect(response.ok()).toBeTruthy();
  const rows = (await response.json()).data;
  for (const row of rows) {
    await page.goto(
      `/console/connectors/?connect=${encodeURIComponent(row.connector_id)}`,
    );
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: row.name, exact: true }),
    ).toBeVisible();
    if (
      !["aws-posture", "azure-posture", "gcp-posture"].includes(
        row.connector_id,
      )
    ) {
      await expect(
        dialog.getByRole("navigation", { name: "Connection setup steps" }),
      ).toBeVisible();
      if (row.state !== "enabled") {
        await expect(
          dialog.getByRole("heading", { name: "Configure read-only access" }),
        ).toBeVisible();
        await expect(
          dialog.getByText("Optional sync schedule", { exact: true }),
        ).toHaveCount(0);
      }
    }
  }
});

for (const id of ["kubernetes-cluster", "intune-devices"]) {
  test(`${id} setup fits a mobile viewport`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/console/connectors/?connect=${id}`);
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: "Configure read-only access" }),
    ).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box!.width).toBeLessThanOrEqual(391);
    expect(
      await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    ).toBeTruthy();
    await expect(
      dialog.getByRole("button", { name: "Next: test access" }),
    ).toBeDisabled();
  });
}

test("failed access test keeps configuration recoverable", async ({ page }) => {
  await page.route("**/api/v1/connectors/kubernetes-cluster/probe", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Provider is temporarily unavailable" }),
    }),
  );
  await page.goto("/console/connectors/?connect=kubernetes-cluster");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/Cluster name/).fill("synthetic-cluster");
  await dialog.getByRole("button", { name: "Next: test access" }).click();
  await dialog.getByRole("button", { name: "Test connection" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Enable connector" }),
  ).toHaveCount(0);
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await expect(dialog.getByLabel(/Cluster name/)).toHaveValue(
    "synthetic-cluster",
  );
});
