import { test, expect } from "@playwright/test";

test("framework drawer has adjustable width, focused tabs and paginated controls", async ({
  page,
}) => {
  await page.goto("/console/frameworks/?framework=soc2&control=SOC2-CC6.1");
  const drawer = page.getByRole("dialog");
  await expect(
    drawer.getByRole("tab", { name: "Controls", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  const resize = drawer.getByRole("separator", { name: "Resize drawer" });
  const before = await drawer.boundingBox();
  await resize.focus();
  await resize.press("ArrowLeft");
  await expect
    .poll(async () => (await drawer.boundingBox())!.width)
    .toBeGreaterThan(before!.width);
  await drawer
    .getByRole("button", { name: "Expand drawer", exact: true })
    .click();
  await expect(
    drawer.getByRole("button", { name: "Restore drawer width" }),
  ).toBeVisible();
  await expect(
    drawer.getByRole("navigation", { name: "Controls pages" }),
  ).toBeVisible();
  const first = drawer.locator('[id="control-SOC2-CC6.1"]');
  await first.getByRole("tab", { name: "Evidence", exact: true }).click();
  await expect(
    first.getByText("Explain assessment gaps", { exact: true }),
  ).toHaveCount(0);
  await first.getByRole("tab", { name: "Assessment", exact: true }).click();
  await expect(
    first.getByRole("button", { name: "Explain assessment gaps" }),
  ).toBeVisible();
  await drawer.getByRole("tab", { name: "Overview", exact: true }).click();
  await expect(
    drawer.getByRole("heading", { name: "Control results" }),
  ).toBeVisible();
});

test("finding tabs preserve triage edits and isolate long history", async ({
  page,
  request,
}) => {
  const rows = (await (await request.get("/api/v1/violations")).json()).data;
  await page.goto(
    "/console/violations/?id=" + encodeURIComponent(rows[0].violation_id),
  );
  const drawer = page.getByRole("dialog");
  await expect(
    drawer.getByRole("tab", { name: "Overview", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(drawer.getByLabel("Assignee", { exact: true })).toHaveCount(0);
  await drawer.getByRole("tab", { name: "Triage", exact: true }).click();
  await drawer.getByLabel("Assignee", { exact: true }).fill("synthetic-owner");
  await drawer.getByRole("tab", { name: "History", exact: true }).click();
  await expect(
    drawer.getByRole("heading", { name: /Triage history/ }),
  ).toBeVisible();
  await drawer.getByRole("tab", { name: "Triage", exact: true }).click();
  await expect(drawer.getByLabel("Assignee", { exact: true })).toHaveValue(
    "synthetic-owner",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await drawer.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
    true,
  );
});

test("access review empty state explains workflow before exposing a form", async ({
  page,
}) => {
  await page.route("**/api/v1/access-reviews**", (r) =>
    r.fulfill({ json: { data: [] } }),
  );
  await page.goto("/console/access-reviews/");
  await expect(
    page.getByRole("heading", { name: "Start a user access review" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Decisions are recorded here; provider access is not changed.",
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Campaign name", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("link", { name: "Connect an identity source" }),
  ).toBeVisible();
});
