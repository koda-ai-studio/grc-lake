import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const theme of ["light", "dark"])
  for (const width of [1440, 390]) {
    test(`selected evidence has a readable directed focus and exact lifecycle at ${width}px in ${theme}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 1100 });
      await page.addInitScript(
        (theme) =>
          localStorage.setItem("trustops:theme", JSON.stringify(theme)),
        theme,
      );
      const nodes = [
        { id: "framework:f", kind: "framework", label: "Test framework" },
        {
          id: "control:c",
          kind: "control",
          label: "SOC2-CC6.1",
          status: "open",
        },
        {
          id: "source:s",
          kind: "source",
          label: "GitHub",
          source_account_id: "account-a",
        },
        {
          id: "evidence:e",
          kind: "evidence_type",
          label: "repository.governance.branch_protection",
          status: "observed",
          source_account_id: "account-a",
          observed_at: "2026-10-01T12:00:00.123456Z",
          collected_at: "2026-10-02T01:00:00+02:00",
          freshness_evaluated_at: "2026-10-03T02:00:00Z",
          freshness_status: "fresh",
        },
        { id: "asset:a", kind: "repository", label: "acme/service" },
        {
          id: "evidence:other",
          kind: "evidence_type",
          label: "Other evidence",
          status: "open",
        },
      ];
      const edges = [
        {
          id: "framework",
          source: "framework:f",
          target: "control:c",
          kind: "framework_has_control",
        },
        {
          id: "requires",
          source: "control:c",
          target: "evidence:e",
          kind: "control_requires_evidence",
        },
        {
          id: "produces",
          source: "source:s",
          target: "evidence:e",
          kind: "produces",
        },
        {
          id: "covers",
          source: "evidence:e",
          target: "asset:a",
          kind: "evidence_covers_asset",
        },
        {
          id: "other",
          source: "control:c",
          target: "evidence:other",
          kind: "control_requires_evidence",
        },
      ];
      await page.route("**/api/v1/graph/investigation?*", (route) =>
        route.fulfill({
          json: {
            data: {
              nodes,
              edges,
              counts: {},
              root: "control:c",
              roots: [nodes[1]],
              root_count: 1,
              root_offset: 0,
              version: "reading",
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
      await page.goto("/console/graph/");
      await page.locator('.react-flow__node[data-id="evidence:e"]').click();
      await expect(page.locator(".react-flow__edge-path")).toHaveCount(5);
      const entry = await page.evaluate(() => {
        const node = document
          .querySelector('.react-flow__node[data-id="evidence:e"]')!
          .getBoundingClientRect();
        return ["requires", "produces"].map((id) => {
          const path = document.querySelector<SVGPathElement>(
            `.react-flow__edge[data-id="${id}"] .react-flow__edge-path`,
          )!;
          const end = path
            .getPointAtLength(path.getTotalLength())
            .matrixTransform(path.getScreenCTM()!);
          return {
            x: end.x - node.x,
            y: end.y - node.y,
            width: node.width,
            height: node.height,
          };
        });
      });
      expect(entry[0].x).toBeCloseTo(entry[0].width / 2, 0);
      expect(entry[0].y).toBeCloseTo(0, 0);
      expect(entry[1].x).toBeCloseTo(0, 0);
      expect(entry[1].y).toBeCloseTo(entry[1].height / 2, 0);

      const inspector = page.getByRole("complementary", {
        name: "Selected graph node",
      });
      await expect(
        inspector.getByRole("heading", {
          name: "Branch protection",
          exact: true,
        }),
      ).toBeVisible();
      await expect(inspector).toContainText(
        "repository.governance.branch_protection",
      );
      const lifecycle = page.getByRole("region", {
        name: "Evidence lifecycle",
      });
      await expect(lifecycle).toContainText("01 Oct 2026");
      await expect(lifecycle).toContainText("23:00:00 UTC");
      await lifecycle
        .getByText("Exact recorded timestamps", { exact: true })
        .click();
      await expect(
        lifecycle.getByText("2026-10-01T12:00:00.123456Z", { exact: true }),
      ).toBeVisible();
      await expect(
        lifecycle.getByText("2026-10-02T01:00:00+02:00", { exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", {
          name: "Focus direct relationships",
          exact: true,
        })
        .click();
      await expect(page.locator(".react-flow__node")).toHaveCount(4);
      await expect(page.locator(".react-flow__edge")).toHaveCount(3);
      await expect(page.getByLabel("Direct relationship counts")).toContainText(
        "4 nodes · 3 relationships",
      );
      await expect(
        page.getByRole("status").filter({ hasText: "4 of 6 loaded nodes" }),
      ).toContainText("3 of 5 relationships");
      await expect(
        page.locator('.react-flow__edge[data-id="produces"]'),
      ).toHaveAttribute("aria-label", "produces");
      await expect(
        page.locator('.react-flow__edge[data-id="covers"]'),
      ).toHaveAttribute("aria-label", "evidence covers asset");
      await expect(
        page.getByText("Direct relationships only", { exact: true }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Show full neighborhood", exact: true })
        .click();
      await expect(page.locator(".react-flow__node")).toHaveCount(6);
      await expect(page.locator(".react-flow__edge")).toHaveCount(5);
      await page
        .getByRole("heading", { name: "Evidence investigation", exact: true })
        .hover();
      await expect(
        page.locator(
          '.react-flow__edge[data-id="other"] .react-flow__edge-path',
        ),
      ).toHaveCSS("opacity", "0.4");
      await expect(
        page.locator(
          '.react-flow__edge[data-id="covers"] .react-flow__edge-path',
        ),
      ).toHaveCSS("opacity", "1");
      await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.screenshot({
        path: testInfo.outputPath("reading-flow.png"),
        fullPage: true,
      });
      await page
        .getByRole("button", {
          name: "Focus direct relationships",
          exact: true,
        })
        .click();
      await page
        .getByText("Selected relationships and mapping review state", {
          exact: true,
        })
        .click();
      const relationships = page.getByRole("region", {
        name: "Selected node relationships",
      });
      await relationships
        .getByRole("button", { name: "Inspect SOC2-CC6.1", exact: true })
        .click();
      await relationships
        .getByRole("button", { name: "Inspect Test framework", exact: true })
        .click();
      await expect(page.locator(".react-flow__node")).toHaveCount(6);
      await expect(
        inspector.getByRole("heading", { name: "Test framework", exact: true }),
      ).toBeVisible();
    });
  }

test("recorded investigation routes avoid every rendered node label", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/console/graph/");
  await expect(page.locator(".react-flow__node")).not.toHaveCount(0);
  await expect(page.locator(".react-flow__edge")).not.toHaveCount(0);
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

test("direct focus counts excluded neighbor links even when all nodes remain", async ({
  page,
}) => {
  await page.route("**/api/v1/graph/investigation?*", (route) =>
    route.fulfill({
      json: {
        data: {
          nodes: [
            { id: "e", kind: "evidence_type", label: "Evidence" },
            { id: "s", kind: "source", label: "Source" },
            { id: "a", kind: "asset", label: "Asset" },
          ],
          edges: [
            { id: "se", source: "s", target: "e", kind: "produces" },
            {
              id: "ea",
              source: "e",
              target: "a",
              kind: "evidence_covers_asset",
            },
            { id: "sa", source: "s", target: "a", kind: "observes" },
          ],
          counts: {},
          root: "e",
          roots: [],
          root_count: 0,
          root_offset: 0,
          version: "focus-counts",
          depth: 2,
          limit: 150,
          truncated: false,
          matching_nodes: 3,
          boundary: "Recorded relationships",
          framework_groups: [],
        },
      },
    }),
  );
  await page.goto("/console/graph/");
  await page.locator('.react-flow__node[data-id="e"]').click();
  await page
    .getByRole("button", { name: "Focus direct relationships", exact: true })
    .click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(2);
  await expect(
    page.getByRole("status").filter({ hasText: "3 of 3 loaded nodes" }),
  ).toContainText("2 of 3 relationships");
  await page.getByRole("button", { name: "Show full neighborhood" }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);
});
