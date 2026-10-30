import { expect, test, type Page } from "@playwright/test";

async function openMaps(page: Page) {
  await page.goto("/console/graph/");
  await page
    .getByRole("button", { name: /^(Framework and repository )?maps$/i })
    .click();
  const framework = page.getByRole("combobox", {
    name: "Filter graph by framework",
  });
  await expect(framework).not.toHaveValue("", { timeout: 45_000 });
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  return framework;
}

async function zoom(page: Page) {
  await page.waitForTimeout(700);
  return page
    .locator(".react-flow__viewport")
    .evaluate((el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);
}

test("the all-frameworks map stays bounded and explains how to narrow it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const framework = await openMaps(page);
  const started = Date.now();
  await framework.selectOption("");
  const notice = page.getByTestId("graph-too-large");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("Evidence investigation");
  expect(Date.now() - started).toBeLessThan(5_000);
  expect(await page.locator(".react-flow__node").count()).toBeLessThanOrEqual(
    500,
  );
  expect(
    await page.evaluate(() => document.querySelectorAll("*").length),
  ).toBeLessThan(8_000);
  await notice.getByRole("button", { name: /Show SOC 2/ }).click();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  await expect(framework).toHaveValue("soc2");
});

test("graph nodes are named, keyboard focus is visible, and nodes precede edges", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  const node = page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]');
  await expect(node).toHaveAttribute(
    "aria-label",
    "Control: SOC2-CC6.1, Failing control",
  );
  expect(await page.locator('.react-flow__edge[tabindex="0"]').count()).toBe(0);
  await page.getByRole("button", { name: "Expand graph workspace" }).focus();
  let reached = false;
  for (let i = 0; i < 30 && !reached; i += 1) {
    await page.keyboard.press("Tab");
    reached = await page.evaluate(
      () =>
        document.activeElement?.classList.contains("react-flow__node") ?? false,
    );
  }
  expect(reached).toBe(true);
  const outline = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement!);
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth) };
  });
  expect(outline.style).not.toBe("none");
  expect(outline.width).toBeGreaterThanOrEqual(2);
});

const NODES = [
  {
    id: "framework:soc2",
    kind: "framework",
    label: "SOC 2 Trust Services Criteria",
    framework_id: "soc2",
  },
  {
    id: "control:SOC2-CC6.1",
    kind: "control",
    label: "SOC2-CC6.1",
    framework_id: "soc2",
    status: "pass",
    ccf_status: "open",
    reviewed_safeguard_count: 1,
    proposed_safeguard_count: 2,
    rule_reasons: ["Reviewed safeguard SG-IDENTITY-001 has open evidence"],
    evaluation_rule: "all_reviewed_safeguards_pass",
    open_event_count: 3,
  },
  {
    id: "evidence:mfa",
    kind: "evidence_type",
    label: "okta.mfa",
    status: "passed",
    freshness_status: "expired",
  },
  {
    id: "safeguard:SG-IDENTITY-001",
    kind: "safeguard",
    label: "Logical access and MFA",
    status: "not_evaluated",
  },
  { id: "asset:db", kind: "asset", label: "Billing DB" },
  { id: "asset:laptop", kind: "asset", label: "Shared laptop" },
];
const EDGES = [
  {
    id: "e1",
    source: "framework:soc2",
    target: "control:SOC2-CC6.1",
    kind: "framework_has_control",
  },
  {
    id: "e2",
    source: "control:SOC2-CC6.1",
    target: "evidence:mfa",
    kind: "control_requires_evidence",
  },
  {
    id: "e3",
    source: "control:SOC2-CC6.1",
    target: "safeguard:SG-IDENTITY-001",
    kind: "maps_to",
    review_state: "maintainer_reviewed",
  },
  {
    id: "e4",
    source: "evidence:mfa",
    target: "asset:db",
    kind: "evidence_covers_asset",
  },
  {
    id: "e5",
    source: "evidence:mfa",
    target: "asset:laptop",
    kind: "evidence_covers_asset",
    binding: "invalid_asset_type",
  },
];

function investigation(root: string, missing = false) {
  return {
    data: {
      version: "labels-v1",
      root,
      root_missing: missing,
      roots: NODES.slice(0, 2).map(({ id, kind, label }) => ({
        id,
        kind,
        label,
      })),
      root_count: 2,
      root_offset: 0,
      next_root_offset: null,
      nodes: missing ? [] : NODES,
      edges: EDGES,
      counts: { framework: 1, control: 1, evidence_type: 1, asset: 2 },
      framework_groups: [],
      selected_framework: "",
      control_count: 0,
      control_offset: 0,
      next_control_offset: null,
      depth: 2,
      limit: 150,
      truncated: false,
      matching_nodes: NODES.length,
      boundary: "Recorded relationships; not network reachability",
    },
  };
}

test("investigation labels stale evidence, unattested controls, safeguards and invalid bindings", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route("**/api/v1/graph/investigation?*", (route) =>
    route.fulfill({ json: investigation("control:SOC2-CC6.1") }),
  );
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  const control = page.locator(
    '.react-flow__node[data-id="control:SOC2-CC6.1"]',
  );
  await expect(control).toContainText("Control test passing · Not attested");
  await expect(control).not.toContainText("Passing · Attested");
  await expect(
    page.locator('.react-flow__node[data-id="evidence:mfa"]'),
  ).toContainText("Stale evidence");
  await expect(
    page.locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]'),
  ).toContainText("Safeguard · Not evaluated");
  const invalid = page.locator('.react-flow__edge[data-id="e5"]');
  await expect(invalid).toHaveClass(/graph-edge-invalid/);
  await expect(invalid).toHaveAttribute("aria-label", /invalid asset type/i);
  const dash = await invalid
    .locator(".react-flow__edge-path")
    .evaluate((el) => getComputedStyle(el).strokeDasharray);
  expect(dash).not.toBe("none");
  await expect(
    page.locator('.react-flow__edge[data-id="e3"] .react-flow__edge-path'),
  ).toHaveCSS("stroke-dasharray", /\d/);
  await expect(page.getByTestId("graph-column-legend")).toContainText(
    "Assurance hierarchy: Framework → Control → Safeguard",
  );
  await expect(page.getByTestId("graph-column-legend")).toContainText(
    "Evidence lineage: Source → Observation → Asset",
  );

  await control.click();
  const drawer = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(drawer).toContainText("Control test passing · Not attested");
  await expect(drawer).toContainText("Framework result");
  await expect(drawer).toContainText("Open");
  await expect(drawer).toContainText("1 reviewed");
  await expect(drawer).toContainText("2 proposed");
  await expect(drawer).toContainText(
    "Reviewed safeguard SG-IDENTITY-001 has open evidence",
  );
  await expect(drawer.getByText(/^Pass$/)).toHaveCount(0);
});

test("an unknown starting point says so and offers a reset", async ({
  page,
}) => {
  await page.goto("/console/graph/?root=safeguard%3ANOPE");
  await expect(page.getByText("Starting point not found")).toBeVisible();
  await expect(page.getByText("No recorded relationships")).toHaveCount(0);
  await page.getByRole("button", { name: "Reset starting point" }).click();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
});

test("maps open at a readable zoom and status is not colour alone", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openMaps(page);
  await page.getByRole("button", { name: "Show whole framework" }).click();
  expect(await zoom(page)).toBeGreaterThanOrEqual(0.6);
  const glyphs = page.locator(
    '.react-flow__node [data-testid="graph-status-glyph"]',
  );
  await expect(glyphs.first()).toBeVisible();
  const kinds = await glyphs.evaluateAll((els) =>
    els.map((el) => el.getAttribute("data-tone")),
  );
  expect(new Set(kinds).size).toBeGreaterThan(1);
  await expect(page.getByTestId("graph-overflow-hint")).toBeVisible();
});

test("tablet canvases say when content is outside the view; phones hide the minimap", async ({
  page,
}) => {
  await page.setViewportSize({ width: 834, height: 1112 });
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  await page.getByRole("button", { name: "Expand graph workspace" }).waitFor();
  await page
    .getByText("Search and change starting point", { exact: true })
    .click();
  await page.getByRole("combobox", { name: "Graph depth" }).selectOption("3");
  await page.getByRole("button", { name: "Environment" }).click();
  await expect(page.getByTestId("graph-overflow-hint")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".react-flow__minimap")).toBeHidden();
});

test("the maps workspace uses readable names, plurals and fits a phone", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const framework = await openMaps(page);
  await expect(framework.locator('option[value="soc2"]')).toHaveText(/SOC 2/);
  await expect(page.getByTestId("graph-summary-line")).not.toContainText(
    /\bsoc2\b/,
  );
  const mapping = page
    .getByText("Mapping inspector", { exact: true })
    .locator("../..");
  await expect(mapping).not.toContainText(
    /\b(cloud\.config|iam\.access_review)\b/,
  );
  await expect(mapping).not.toContainText(/\b1 assets\b/);
  await expect(mapping).not.toContainText(/\bsoc2\b/);
  const legend = page.getByTestId("graph-maps-legend");
  const rail = page.getByTestId("graph-layer-rail");
  const [legendBox, railBox] = [
    await legend.boundingBox(),
    await rail.boundingBox(),
  ];
  expect(legendBox!.y + legendBox!.height).toBeLessThanOrEqual(
    railBox!.y + railBox!.height + 1,
  );

  await page.setViewportSize({ width: 390, height: 844 });
  for (const button of await page
    .getByRole("group", { name: "Graph workspace" })
    .getByRole("button")
    .all()) {
    const box = (await button.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  }
});

test("starting points do not repeat their kind and empty layers are dimmed", async ({
  page,
}) => {
  await page.goto("/console/graph/");
  await page
    .getByText("Search and change starting point", { exact: true })
    .click();
  await page.getByRole("button", { name: "Environment" }).click();
  const options = page
    .getByRole("combobox", { name: "Graph starting point" })
    .locator("option");
  await expect.poll(() => options.count()).toBeGreaterThan(3);
  const texts = await options.allTextContents();
  expect(texts.filter((t) => /repository · repository/.test(t))).toEqual([]);

  await openMaps(page);
  await page.getByRole("button", { name: "Repository", exact: true }).click();
  const empty = page.locator(
    '[data-testid="graph-layer-chip"][data-empty="true"]',
  );
  await expect.poll(() => empty.count()).toBeGreaterThan(0);
  expect(
    Number(await empty.first().evaluate((el) => getComputedStyle(el).opacity)),
  ).toBeLessThan(1);
});

test("graph workspace tabs align with the page content instead of touching the top bar", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/graph/");
  const tabs = page.getByRole("group", { name: "Graph workspace" });
  const heading = page.getByRole("heading", {
    level: 1,
    name: "Evidence investigation",
  });
  await expect(heading).toBeVisible();
  const [tabBox, headingBox, mainBox] = [
    await tabs.getByRole("button").first().boundingBox(),
    await heading.boundingBox(),
    await page.locator("main").first().boundingBox(),
  ];
  expect(Math.abs(tabBox!.x - headingBox!.x)).toBeLessThanOrEqual(1);
  expect(tabBox!.y - mainBox!.y).toBeGreaterThanOrEqual(16);
});

test("an overflowing node inspector shows that more details are below", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/graph/");
  await page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]').click();
  const inspector = page.getByTestId("graph-node-inspector");
  await expect(inspector).toBeVisible();
  const overflowing = await inspector.evaluate(
    (el) => el.scrollHeight > el.clientHeight + 1,
  );
  expect(overflowing).toBe(true);
  await expect(inspector.getByTestId("inspector-more-below")).toBeVisible();
});

test("a mapping without review provenance stays visibly unreviewed", async ({
  page,
}) => {
  const payload = investigation("control:SOC2-CC6.1");
  payload.data.edges = EDGES.map((edge) => {
    const copy = { ...edge };
    delete copy.review_state;
    return copy;
  });
  await page.route("**/api/v1/graph/investigation?*", (route) =>
    route.fulfill({ json: payload }),
  );
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  const mapping = page.locator('.react-flow__edge[data-id="e3"]');
  await expect(mapping).toHaveAttribute("aria-label", /review not recorded/i);
  await expect(mapping.locator(".react-flow__edge-path")).toHaveCSS(
    "stroke-dasharray",
    "2px, 4px",
  );
  const legend = page.getByLabel("Relationship styles", { exact: true });
  await expect(legend).toContainText("Review not recorded");
  await expect(legend).not.toContainText("Reviewed mapping");
  await page
    .getByText("Selected relationships and mapping review state", {
      exact: true,
    })
    .click();
  const mappingRow = page
    .getByRole("group", { name: "Outgoing relationships" })
    .getByRole("listitem")
    .filter({ hasText: "Logical access and MFA" });
  await expect(mappingRow).toContainText("maps to");
  await expect(mappingRow).toContainText(
    "Review not recorded · catalog mapping",
  );
});

test("fit view restores readable labels instead of shrinking the whole framework", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openMaps(page);
  await page.getByRole("button", { name: "Show whole framework" }).click();
  await page.getByRole("button", { name: /^fit view$/i }).click();
  expect(await zoom(page)).toBeGreaterThanOrEqual(0.6);
  await expect(page.getByTestId("graph-overflow-hint")).toBeVisible();
});

test("a dense investigation refuses layout promptly without silently dropping relationships", async ({
  page,
}) => {
  const nodes = [
    NODES[1],
    ...Array.from({ length: 49 }, (_, i) => ({
      id: `asset:dense-${i}`,
      kind: "asset",
      label: `Synthetic asset ${i}`,
    })),
  ];
  const edges = nodes.flatMap((node, i) =>
    nodes.slice(i + 1).map((target, j) => ({
      id: `dense-${i}-${j}`,
      source: node.id,
      target: target.id,
      kind: "contains",
    })),
  );
  await page.route("**/api/v1/graph/investigation?*", (route) =>
    route.fulfill({
      json: {
        data: {
          ...investigation(nodes[0].id).data,
          nodes,
          edges,
          counts: { control: 1, asset: 49 },
          matching_nodes: 50,
        },
      },
    }),
  );
  const started = Date.now();
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  const notice = page.getByTestId("graph-too-large");
  await expect(notice).toContainText("50 nodes and 1,225 relationships");
  expect(Date.now() - started).toBeLessThan(5_000);
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
  await expect(page.getByText(/50 nodes · 1225 relationships/)).toBeVisible();
  // The user can still inspect the supplied relationships without laying them out.
  await page
    .getByText("Selected relationships and mapping review state", {
      exact: true,
    })
    .click();
  const outgoing = page.getByRole("group", { name: "Outgoing relationships" });
  await expect(outgoing).toContainText("Outgoing · 49");
  const first = outgoing.getByRole("listitem").first();
  await expect(first).toContainText("SOC2-CC6.1 → Synthetic asset 0");
  await expect(first).toContainText("contains · Asset");
  await expect(outgoing.getByRole("listitem")).toHaveCount(5);
  await outgoing
    .getByRole("button", { name: "Next outgoing relationships" })
    .click();
  await expect(outgoing.getByRole("listitem").first()).toContainText(
    "SOC2-CC6.1 → Synthetic asset 5",
  );
});
