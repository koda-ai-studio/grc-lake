import { expect, test } from "@playwright/test";

test("graph actions open the selected control, finding, and evidence", async ({
  page,
}) => {
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  await page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]').click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  const controlLink = inspector.getByRole("link", {
    name: "Open controls workbench",
  });
  await expect(controlLink).toHaveAttribute(
    "href",
    /\/controls\/?\?id=SOC2-CC6.1$/,
  );
  await controlLink.click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("heading", { name: "SOC2-CC6.1", exact: true }),
  ).toBeVisible();

  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  await page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]').click();
  await inspector
    .getByRole("region", { name: "Findings on this control" })
    .getByRole("button")
    .first()
    .click();
  const findingLink = inspector.getByRole("link", {
    name: "Review finding and remediation",
  });
  await expect(findingLink).toHaveAttribute(
    "href",
    /\/violations\/?\?id=SOC2-CC6.1%3A.+/,
  );
  await findingLink.click();
  await expect(page.getByRole("dialog")).toBeVisible();

  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  await page.locator('.react-flow__node[data-id^="evidence:"]').first().click();
  const evidenceLink = inspector.getByRole("link", {
    name: "Open evidence room",
  });
  await expect(evidenceLink).toHaveAttribute("href", /\/evidence\/?\?id=.+/);
  await evidenceLink.click();
  await expect(page.getByRole("dialog")).toBeVisible();
});

test("graph-only findings and evidence never invent record identifiers", async ({
  page,
}) => {
  await page.route("**/api/v1/graph/investigation?*", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    for (const node of payload.data.nodes) {
      delete node.evidence_id;
      delete node.violation_id;
      for (const finding of node.findings ?? []) delete finding.violation_id;
    }
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  await page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]').click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await inspector
    .getByRole("region", { name: "Findings on this control" })
    .getByRole("button")
    .first()
    .click();
  await expect(
    inspector.getByRole("link", { name: "Review finding and remediation" }),
  ).toHaveAttribute("href", /\/violations\/?$/);
  await page.locator('.react-flow__node[data-id^="evidence:"]').first().click();
  await expect(
    inspector.getByRole("link", { name: "Open evidence room" }),
  ).toHaveAttribute("href", /\/evidence\/?$/);
});
