import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const recorded of [true, false]) {
  test(`evidence lifecycle distinguishes recorded timestamps from missing data: ${recorded}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: recorded ? 1440 : 390, height: 1000 });
    await page.addInitScript(
      (theme) => localStorage.setItem("trustops:theme", JSON.stringify(theme)),
      recorded ? "light" : "dark",
    );
    await page.route("**/api/v1/graph/investigation?*", async (route) => {
      const node = {
        id: "evidence:record",
        kind: "evidence_type",
        label: "MFA observation",
        status: "pass",
        source_account_id: "account-a",
        observed_at: "2026-10-01T00:00:00Z",
        collected_at: recorded ? "2026-10-02T01:00:00Z" : null,
        freshness_evaluated_at: recorded ? "2026-10-03T02:00:00Z" : null,
        freshness_expires_at: recorded ? "2026-10-04T03:00:00Z" : null,
        freshness_status: recorded ? "fresh" : "missing",
        freshness_age_minutes: recorded ? 60 : null,
      };
      await route.fulfill({
        json: {
          data: {
            nodes: [node],
            edges: [],
            counts: { evidence_type: 1 },
            root: node.id,
            version: "pinned",
            roots: [node],
            root_count: 1,
            root_offset: 0,
            depth: 2,
            limit: 150,
            truncated: false,
            matching_nodes: 1,
            boundary: "Recorded relationships",
          },
        },
      });
    });
    await page.goto("/console/graph/?root=evidence%3Arecord");
    await page.locator('.react-flow__node[data-id="evidence:record"]').click();
    await page.getByText("Evidence timeline", { exact: true }).click();
    const lifecycle = page.getByRole("region", { name: "Evidence lifecycle" });
    await expect(lifecycle).toBeVisible();
    await expect(lifecycle).toContainText("Observed at source");
    await expect(lifecycle).toContainText("2026-10-01T00:00:00Z");
    await expect(lifecycle).toContainText("Collected");
    await expect(lifecycle).toContainText("Freshness evaluated");
    if (recorded) {
      await expect(lifecycle).toContainText("Age at evaluation: 1h");
      await expect(lifecycle).toContainText("2026-10-02T01:00:00Z");
      await expect(lifecycle).toContainText("2026-10-03T02:00:00Z");
      await expect(lifecycle).toContainText("2026-10-04T03:00:00Z");
    } else {
      await expect(
        lifecycle.getByText("Not recorded", { exact: true }),
      ).toHaveCount(2);
      await expect(lifecycle).not.toContainText("Freshness deadline");
    }
    await expect(lifecycle).toContainText(
      "Review, remediation and re-verification require separate receipts",
    );
    await lifecycle.screenshot({
      path: testInfo.outputPath("evidence-lifecycle.png"),
    });
  });
}

test("relationship guide and inspector preserve direction, review and invalid binding", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const nodes = [
    { id: "framework:test", kind: "framework", label: "Test framework" },
    { id: "control:test", kind: "control", label: "Test control" },
    { id: "safeguard:test", kind: "safeguard", label: "Test safeguard" },
    { id: "source:test", kind: "source", label: "Test source" },
    { id: "evidence:test", kind: "evidence_type", label: "Test observation" },
    { id: "asset:test", kind: "asset", label: "Test asset" },
  ];
  const edges = [
    {
      id: "hierarchy",
      source: nodes[0].id,
      target: nodes[1].id,
      kind: "framework_has_control",
    },
    {
      id: "mapping",
      source: nodes[1].id,
      target: nodes[2].id,
      kind: "maps_to",
      review_state: "proposed",
    },
    {
      id: "lineage",
      source: nodes[3].id,
      target: nodes[4].id,
      kind: "produces",
    },
    {
      id: "binding",
      source: nodes[2].id,
      target: nodes[4].id,
      kind: "has_evidence",
      binding: "invalid_asset_type",
    },
    {
      id: "coverage",
      source: nodes[4].id,
      target: nodes[5].id,
      kind: "evidence_covers_asset",
    },
  ];
  await page.route("**/api/v1/graph/investigation?*", async (route) =>
    route.fulfill({
      json: {
        data: {
          nodes,
          edges,
          counts: {},
          root: nodes[1].id,
          version: "fixed",
          roots: [nodes[1]],
          root_count: 1,
          root_offset: 0,
          depth: 2,
          limit: 150,
          truncated: false,
          matching_nodes: 6,
          boundary: "Recorded relationships",
          framework_groups: [],
        },
      },
    }),
  );
  await page.goto("/console/graph/");
  await expect(page.getByLabel("Graph relationship guide")).toContainText(
    "Assurance hierarchy",
  );
  await expect(page.getByLabel("Graph relationship guide")).toContainText(
    "Evidence lineage",
  );
  await page.getByLabel("Show relationship labels", { exact: true }).check();
  await expect(
    page.locator('.react-flow__edge[data-id="lineage"]'),
  ).toContainText("produces");
  await page.locator('.react-flow__node[data-id="safeguard:test"]').click();
  await page
    .getByText("Selected relationships and mapping review state", {
      exact: true,
    })
    .click();
  const relationships = page.getByRole("region", {
    name: "Selected node relationships",
  });
  const incoming = relationships.getByRole("group", {
    name: "Incoming relationships",
  });
  const outgoing = relationships.getByRole("group", {
    name: "Outgoing relationships",
  });
  await expect(incoming).toContainText("Test control");
  await expect(incoming).toContainText("Proposed mapping");
  await expect(outgoing).toContainText("Test observation");
  await expect(outgoing).toContainText("Invalid asset type");
  await outgoing
    .getByRole("button", { name: "Inspect Test observation" })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Selected graph node" }),
  ).toContainText("Test observation");
  await expect(relationships).toContainText("Test source");
  await expect(relationships).toContainText("Test asset");
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
    .disableRules(["svg-img-alt"])
    .analyze();
  expect(violations).toEqual([]);
  await relationships.screenshot({
    path: testInfo.outputPath("directed-relationships.png"),
  });
});

test("relationship paging keeps repeated labels scoped to their source accounts", async ({
  page,
}) => {
  const root = { id: "control:root", kind: "control", label: "Access control" };
  const records = Array.from({ length: 7 }, (_, i) => ({
    id: `evidence:${i}`,
    kind: "evidence_type",
    label: "Access observation",
    source_account_id: `account-${i}`,
  }));
  await page.route("**/api/v1/graph/investigation?*", async (route) =>
    route.fulfill({
      json: {
        data: {
          nodes: [root, ...records],
          edges: records.map((node, i) => ({
            id: `edge-${i}`,
            source: root.id,
            target: node.id,
            kind: "control_requires_evidence",
          })),
          counts: {},
          root: root.id,
          version: "fixed",
          roots: [root],
          root_count: 1,
          root_offset: 0,
          depth: 2,
          limit: 150,
          truncated: true,
          matching_nodes: 99,
          boundary: "Recorded relationships",
          framework_groups: [],
        },
      },
    }),
  );
  await page.goto("/console/graph/");
  await page
    .getByText("Selected relationships and mapping review state", {
      exact: true,
    })
    .click();
  const relationships = page.getByRole("region", {
    name: "Selected node relationships",
  });
  const outgoing = relationships.getByRole("group", {
    name: "Outgoing relationships",
  });
  await expect(outgoing.getByRole("button", { name: /^Inspect / })).toHaveCount(
    5,
  );
  await expect(relationships).toContainText("loaded neighborhood");
  await outgoing
    .getByRole("button", { name: "Next outgoing relationships" })
    .click();
  await expect(outgoing.getByRole("button", { name: /^Inspect / })).toHaveCount(
    2,
  );
  await outgoing
    .getByRole("button", { name: "Inspect Access observation in account-6" })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Selected graph node" }),
  ).toContainText("account-6");
  await expect(outgoing).toContainText("None in this loaded neighborhood");
});
