import { expect, test } from "@playwright/test";

// Golden demo: SOC2-CC6.8's control test passes, but it has only proposed
// safeguard mappings, so its framework (CCF) result is not evaluated. The
// console must never present it as an attested pass.

const CONTROL_ID = "SOC2-CC6.8";

test("controls API carries the CCF result next to the control test", async ({
  request,
}) => {
  const body = (await (
    await request.get("/api/v1/controls?limit=500")
  ).json()) as {
    data: Array<{
      control_id: string;
      status: string;
      ccf_status: string;
      reviewed_safeguard_count: number;
      proposed_safeguard_count: number;
    }>;
  };
  const control = body.data.find((row) => row.control_id === CONTROL_ID)!;
  expect(control.status).toBe("pass");
  expect(control.ccf_status).toBe("not_evaluated");
  expect(control.reviewed_safeguard_count).toBe(0);
  expect(control.proposed_safeguard_count).toBeGreaterThan(0);
});

test("controls page shows a passing control test as not attested", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/controls/");
  const search = page.getByPlaceholder(/Search by control id/);
  await search.fill(CONTROL_ID);
  const queue = page.getByRole("region", {
    name: "Latest control test results",
  });
  const row = queue.locator("tbody tr").filter({ hasText: CONTROL_ID });
  await expect(row).toContainText("Control test passing · Not attested");
  await expect(queue).not.toContainText("Passing · Attested");

  await row.click();
  const drawer = page.getByRole("dialog");
  await expect(
    drawer.getByText("Framework result", { exact: true }),
  ).toBeVisible();
  await expect(drawer).toContainText("Control test passing · Not attested");
  await expect(drawer).toContainText(/0 reviewed · \d+ proposed mappings?/);
  await expect(
    drawer.getByRole("link", { name: /Mapping review/ }),
  ).toHaveAttribute("href", /\/mapping-review\//);

  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page.getByRole("button", { name: "Card grid" }).click();
  const card = page
    .getByTestId("control-card-grid")
    .getByRole("button")
    .filter({ hasText: CONTROL_ID });
  await expect(card).toContainText("Control test passing · Not attested");
});

test("framework detail leads with attested passes, not control test passes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/frameworks/?framework=soc2");
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("tab", { name: "Overview", exact: true }).click();
  await expect(
    drawer.getByText(/^0 attested · \d+ failing · \d+ not attested$/),
  ).toBeVisible();
  await expect(
    drawer.getByText(/\d+ control tests? passing · 0 attested/),
  ).toBeVisible();

  await drawer.getByRole("tab", { name: "Controls", exact: true }).click();
  await expect(drawer.getByText(/0\/\d+ attested/)).toBeVisible();
  await drawer
    .getByRole("textbox", { name: "Search controls" })
    .fill(CONTROL_ID);
  await expect(drawer.locator(`[id="control-${CONTROL_ID}"]`)).toContainText(
    "Control test passing · Not attested",
  );
});
