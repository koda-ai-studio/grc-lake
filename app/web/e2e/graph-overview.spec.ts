import { expect, test, type Page } from "@playwright/test";

async function expectWholeGraph(page: Page) {
  await expect
    .poll(() =>
      page.locator(".react-flow").evaluate((canvas) => {
        const box = canvas.getBoundingClientRect();
        const items = [
          ...canvas.querySelectorAll(
            ".react-flow__node, .react-flow__edge-path, [data-testid=graph-lane-heading]",
          ),
        ];
        return (
          items.length > 0 &&
          items.every((item) => {
            const node = item.getBoundingClientRect();
            return (
              node.left >= box.left &&
              node.right <= box.right &&
              node.top >= box.top &&
              node.bottom <= box.bottom
            );
          })
        );
      }),
    )
    .toBe(true);
}

for (const theme of ["light", "dark"]) {
  for (const width of [1440, 1280, 390]) {
    test(`whole investigation fits with its inspector at ${width}px in ${theme}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: width === 1280 ? 720 : 900 });
      await page.addInitScript(
        (value) =>
          localStorage.setItem("trustops:theme", JSON.stringify(value)),
        theme,
      );
      await page.goto("/console/graph/");
      const nodes = page.locator(".react-flow__node");
      await expect(nodes).toHaveCount(20);
      await expectWholeGraph(page);
      await expect(
        page.getByRole("button", { name: "Fit all nodes", exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Readable view", exact: true }),
      ).toHaveCount(0);
      await expect(page.locator(".react-flow__controls button")).toHaveCount(4);
      await expect(page.locator(".react-flow__minimap")).toBeHidden();
      await page
        .locator('.react-flow__node[data-id="control:SOC2-CC6.1"]')
        .click();
      await expect(
        page.getByRole("complementary", { name: "Selected graph node" }),
      ).toBeVisible();
      await expectWholeGraph(page);
      await expect(page.getByTestId("graph-lane-heading")).toHaveText([
        "Assurance hierarchy",
        "Evidence lineage · Source → observation → asset",
      ]);
      await expect(page.locator(".react-flow__edge-path")).toHaveCount(20);
      await page.screenshot({
        path: testInfo.outputPath("overview.png"),
        fullPage: true,
      });
      await page.getByRole("button", { name: "Zoom In", exact: true }).click();
      await expect
        .poll(() =>
          page
            .locator(".react-flow__viewport")
            .evaluate(
              (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
            ),
        )
        .toBeGreaterThanOrEqual(width < 600 ? 0.85 : 0.7);
      await expect(page.getByTestId("graph-overflow-hint")).toBeVisible();
      const zoom = () =>
        page
          .locator(".react-flow__viewport")
          .evaluate(
            (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
          );
      const readableZoom = await zoom();
      await page.getByRole("button", { name: "Zoom In", exact: true }).click();
      await expect.poll(zoom).toBeGreaterThan(readableZoom);
      const enlargedZoom = await zoom();
      await page.getByRole("button", { name: "Zoom Out", exact: true }).focus();
      await page.keyboard.press("Enter");
      await expect.poll(zoom).toBeLessThan(enlargedZoom);
      await page.getByRole("button", { name: /^fit view$/i }).click();
      await expectWholeGraph(page);
      await expect(page.getByTestId("graph-overflow-hint")).toBeHidden();
      await page
        .getByRole("button", { name: "Expand graph workspace" })
        .click();
      await expectWholeGraph(page);
      await expect(nodes).toHaveCount(20);
      await expect(page.locator(".react-flow__edge-path")).toHaveCount(20);
    });
  }
}

test("fit all retains every node and link in a tall loaded neighborhood", async ({
  page,
}) => {
  const nodes = [
    { id: "control:c", kind: "control", label: "Synthetic control" },
    ...Array.from({ length: 149 }, (_, i) => ({
      id: `evidence:${i}`,
      kind: "evidence_type",
      label: `Recorded observation ${i}`,
    })),
  ];
  const edges = nodes.slice(1).map((node) => ({
    id: `requires:${node.id}`,
    source: "control:c",
    target: node.id,
    kind: "control_requires_evidence",
  }));
  await page.route("**/api/v1/graph/investigation?*", (route) =>
    route.fulfill({
      json: {
        data: {
          nodes,
          edges,
          counts: {},
          root: "control:c",
          roots: [nodes[0]],
          root_count: 1,
          root_offset: 0,
          version: "tall",
          depth: 2,
          limit: 150,
          truncated: false,
          matching_nodes: nodes.length,
          boundary: "Recorded relationships",
          framework_groups: [],
        },
      },
    }),
  );
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/console/graph/");
  await expect(page.locator(".react-flow__node")).toHaveCount(150);
  await expect(page.locator(".react-flow__edge-path")).toHaveCount(149);
  await expectWholeGraph(page);
  await expect
    .poll(() =>
      page
        .locator(".react-flow__viewport")
        .evaluate(
          (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
        ),
    )
    .toBeLessThan(0.16);
});

test("repository evidence keeps incremental zoom after zooming out", async ({
  page,
}) => {
  await page.goto("/console/graph/");
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "acme/model-service" })
    .dblclick();
  await expect(page.getByLabel("Current graph path")).toContainText(
    "1 level deeper",
  );
  await page.getByRole("button", { name: /^fit view$/i }).click();
  await expectWholeGraph(page);
  const zoom = () =>
    page
      .locator(".react-flow__viewport")
      .evaluate(
        (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
      );
  for (let i = 0; i < 8; i++) {
    const before = await zoom();
    await page.getByRole("button", { name: "Zoom Out", exact: true }).click();
    await expect.poll(zoom).toBeLessThan(before);
  }
  const before = await zoom();
  await page.getByRole("button", { name: "Zoom In", exact: true }).click();
  await page.waitForTimeout(300);
  expect(await zoom()).toBeCloseTo(before * 1.2, 3);
});
