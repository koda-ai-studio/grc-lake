import { expect, test, type Page } from "@playwright/test";

async function openMap(page: Page, connected: boolean) {
  await page.route(/\/api\/v1\/graph(?:\?|$)/, (route) =>
    route.fulfill({
      json: {
        data: {
          nodes: ["a", "b", "c"].map((id) => ({
            id,
            kind: "asset",
            label: `Asset ${id.toUpperCase()}`,
          })),
          edges: [
            { id: "ab", source: "a", target: "b", kind: "recorded" },
            { id: "ba", source: "b", target: "a", kind: "recorded" },
            ...(connected
              ? [{ id: "cb", source: "c", target: "b", kind: "recorded" }]
              : []),
          ],
          counts: { asset: 3 },
        },
      },
    }),
  );
  await page.goto("/console/graph/");
  await page
    .getByRole("button", { name: "Framework and repository maps", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await page.getByRole("button", { name: "Trace path", exact: true }).click();
  await page.locator('.react-flow__node[data-id="a"]').click();
  await page.locator('.react-flow__node[data-id="c"]').click();
}

test("disconnected selections report no connection instead of claiming a shortest path", async ({
  page,
}) => {
  await openMap(page, false);
  await expect(page.getByTestId("graph-connection-trace")).toContainText(
    "No recorded connection in the visible graph",
  );
  await expect(page.locator(".react-flow__edge.animated")).toHaveCount(0);
  await page.getByRole("button", { name: "Clear path", exact: true }).click();
  await expect(page.getByTestId("graph-connection-trace")).toHaveCount(0);
});

test("a connection highlights only its selected edges and explains reverse traversal", async ({
  page,
}) => {
  await openMap(page, true);
  await expect(page.getByTestId("graph-connection-trace")).toContainText(
    "3 nodes · 2 relationships",
  );
  await expect(page.getByTestId("graph-connection-trace")).toContainText(
    "either direction",
  );
  await expect(page.locator(".react-flow__edge.animated")).toHaveCount(2);
  await expect(page.locator('.react-flow__edge[data-id="ba"]')).not.toHaveClass(
    /animated/,
  );
});

test("reverse links retain their arrows without crossing node labels", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  await openMap(page, true);
  await page.waitForTimeout(500);
  const collisions = await page.evaluate(() => {
    const labels = [
      ...document.querySelectorAll('[data-testid="graph-node-label"]'),
    ].map((el) => ({ text: el.textContent, box: el.getBoundingClientRect() }));
    return [
      ...document.querySelectorAll<SVGPathElement>(".react-flow__edge-path"),
    ].flatMap((path) => {
      const matrix = path.getScreenCTM()!;
      const hits = new Set<string>();
      for (let d = 0; d < path.getTotalLength(); d += 2) {
        const p = path.getPointAtLength(d).matrixTransform(matrix);
        for (const label of labels)
          if (
            p.x > label.box.left &&
            p.x < label.box.right &&
            p.y > label.box.top &&
            p.y < label.box.bottom
          )
            hits.add(label.text ?? "");
      }
      return [...hits];
    });
  });
  expect(collisions).toEqual([]);
});
