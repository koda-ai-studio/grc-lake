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
  await page.route(/\/api\/v1\/graph(?:\?|$)/, (route) =>
    route.fulfill({
      json: {
        data: {
          nodes: [
            {
              id: "finding:graph-only",
              kind: "finding",
              label: "Unlinked finding",
            },
            {
              id: "evidence:type",
              kind: "evidence_type",
              label: "Aggregate evidence",
            },
          ],
          edges: [],
          counts: { finding: 1, evidence_type: 1 },
        },
      },
    }),
  );
  await page.goto("/console/graph/");
  await page
    .getByRole("button", { name: "Framework and repository maps", exact: true })
    .click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await page.locator('.react-flow__node[data-id="finding:graph-only"]').click();
  await expect(
    inspector.getByRole("link", { name: "Review finding and remediation" }),
  ).toHaveAttribute("href", /\/violations\/?$/);
  await page.locator('.react-flow__node[data-id="evidence:type"]').click();
  await expect(
    inspector.getByRole("link", { name: "Open evidence room" }),
  ).toHaveAttribute("href", /\/evidence\/?$/);
});
