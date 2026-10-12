import { expect, test } from "@playwright/test";

test("finding details remain top-aligned at normal, expanded and mobile widths", async ({
  page,
  request,
}) => {
  const findings = (await (await request.get("/api/v1/violations")).json())
    .data;
  const finding = findings.find(
    (row: { control_id: string }) =>
      row.control_id === "NIST-AI-RMF-GOVERN-1.2",
  );
  expect(finding).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(
    `/console/violations/?id=${encodeURIComponent(finding.violation_id)}`,
  );
  const drawer = page.getByRole("dialog");
  const details = drawer.getByRole("region", { name: "Details", exact: true });
  const steps = drawer
    .locator("details")
    .filter({ hasText: "Remediation steps" });
  await expect(steps).toBeVisible();
  await expect(steps).not.toHaveAttribute("open", "");
  for (const expanded of [false, true]) {
    if (expanded)
      await drawer.getByRole("button", { name: "Expand drawer" }).click();
    const heading = await details.getByRole("heading").boundingBox();
    const fields = await details.locator("dl").boundingBox();
    expect(fields!.y - (heading!.y + heading!.height)).toBeLessThan(20);
    expect(fields!.height).toBeLessThan(260);
    const remediation = await drawer
      .getByRole("heading", { name: "Remediation", exact: true })
      .boundingBox();
    expect(Math.abs(remediation!.y - heading!.y)).toBeLessThan(2);
  }
  await steps.locator("summary").click();
  await expect(steps.locator("li").first()).toBeVisible();
  await expect(drawer.getByRole("img", { name: /framework/ })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => drawer.evaluate((el) => el.scrollWidth - el.clientWidth))
    .toBeLessThanOrEqual(1);
  const fields = await details.locator("dl").boundingBox();
  const remediation = await drawer
    .getByRole("heading", { name: "Remediation", exact: true })
    .boundingBox();
  expect(remediation!.y).toBeGreaterThan(fields!.y + fields!.height);
});

test("audit priorities bound gaps and keep calculation prose on demand", async ({
  page,
}) => {
  await page.goto("/console/audit-room/");
  await expect(
    page.getByRole("heading", { name: "Blocking gaps" }),
  ).toBeVisible();
  const pages = page.getByRole("navigation", { name: "Audit gaps pages" });
  await expect(pages.getByRole("status")).toHaveText(/^1–3 of \d+$/);
  await pages.getByRole("button", { name: "Next audit gaps page" }).click();
  await expect(pages.getByRole("status")).toHaveText(/^4–6 of \d+$/);
  await expect(
    page.getByLabel("Evaluated framework scope").getByRole("img"),
  ).not.toHaveCount(0);
  await page.getByRole("tab", { name: "Coverage & scores" }).click();
  await expect(page.getByText("Blocking gaps")).not.toBeVisible();
  const disclosure = page
    .locator("details")
    .filter({ hasText: "How these scores are calculated" });
  await expect(disclosure).not.toHaveAttribute("open", "");
  await disclosure.locator("summary").click();
  await expect(disclosure.locator("dd").first()).toBeVisible();
});

test("source logos open connection details and record counts filter exact source", async ({
  page,
}) => {
  await page.goto("/console/dashboard/");
  await page.getByRole("tab", { name: "Sources & operations" }).click();
  const source = page.getByRole("link", {
    name: "Open Aws config source",
    exact: true,
  });
  await expect(source).toHaveAttribute(
    "href",
    "/console/connectors/?connect=aws-posture",
  );
  await source.click();
  await expect(page.getByRole("dialog")).toContainText("AWS");
  await page.goto("/console/dashboard/");
  await page.getByRole("tab", { name: "Sources & operations" }).click();
  await page
    .getByRole("link", {
      name: /View \d+ evidence records from Github$/,
      exact: true,
    })
    .click();
  await expect(page).toHaveURL(/source=github/);
  await expect(
    page.getByText("Source:", { exact: false }).filter({ hasText: "github" }),
  ).toBeVisible();
  const sourceCells = page.locator("tbody tr td:nth-child(2)");
  await expect(
    page.getByRole("button", { name: "Clear source filter" }),
  ).toBeVisible();
  await expect(sourceCells).not.toHaveCount(0);
  for (const cell of await sourceCells.all())
    await expect(cell).toHaveText("github");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Clear source filter" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear source filter" }).click();
  await expect(page).not.toHaveURL(/source=/);
});

for (const route of ["audit-room", "trust-center"]) {
  test(`${route} keeps a single visible workspace and fits mobile`, async ({
    page,
  }) => {
    await page.goto(`/console/${route}/`);
    await expect(page.getByRole("tabpanel")).toBeVisible();
    await expect(page.getByRole("tabpanel")).toHaveCount(1);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
  });
}
