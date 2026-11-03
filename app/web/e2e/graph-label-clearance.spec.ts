import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"])
  for (const width of [1440, 390])
    test(`relationship labels stay clear at ${width}px in ${theme}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(
        (value) =>
          localStorage.setItem("trustops:theme", JSON.stringify(value)),
        theme,
      );
      await page.goto("/console/graph/");
      await page.getByLabel("Show relationship labels").check();
      await expect(page.locator(".react-flow__edge-textwrapper")).toHaveCount(
        20,
      );
      const collisions = await page.evaluate(() => {
        const labels = [
          ...document.querySelectorAll(".react-flow__edge-textwrapper"),
        ];
        const cards = [...document.querySelectorAll(".react-flow__node")];
        const paths = [
          ...document.querySelectorAll<SVGPathElement>(
            ".react-flow__edge-path",
          ),
        ];
        const overlaps = (a: DOMRect, b: DOMRect) =>
          a.left < b.right &&
          a.right > b.left &&
          a.top < b.bottom &&
          a.bottom > b.top;
        return labels.flatMap((label, i) => {
          const box = label.getBoundingClientRect();
          const cardHits = [...cards, ...labels.slice(i + 1)]
            .filter((other) => overlaps(box, other.getBoundingClientRect()))
            .map(
              (other) => `${label.textContent} overlaps ${other.textContent}`,
            );
          const ownEdge = label.closest(".react-flow__edge");
          const lineHits = paths
            .filter((path) => path.closest(".react-flow__edge") !== ownEdge)
            .flatMap((path) => {
              const matrix = path.getScreenCTM()!;
              for (let d = 0; d < path.getTotalLength(); d += 2) {
                const point = path.getPointAtLength(d).matrixTransform(matrix);
                if (
                  point.x > box.left &&
                  point.x < box.right &&
                  point.y > box.top &&
                  point.y < box.bottom
                )
                  return [`${label.textContent} crosses another relationship`];
              }
              return [];
            });
          return [...cardHits, ...lineHits];
        });
      });
      expect(collisions).toEqual([]);
    });

test("scrolling at the inspector boundary continues through the page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/console/graph/");
  await page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]').click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(inspector).toBeVisible();
  await inspector.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await page.evaluate(() => window.scrollTo(0, 100));
  await inspector.hover();
  const before = await page.evaluate(() => scrollY);
  await page.mouse.wheel(0, 500);
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(before);
});

test("Shift scroll pans the graph while ordinary scroll moves the page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/console/graph/");
  await expect(page.locator(".react-flow__node")).toHaveCount(20);
  await page.getByRole("button", { name: "Zoom In", exact: true }).click();
  await page.locator(".react-flow").hover();
  const viewport = page.locator(".react-flow__viewport");
  const matrix = () =>
    viewport.evaluate((element) => {
      const m = new DOMMatrixReadOnly(getComputedStyle(element).transform);
      return { x: m.e, y: m.f, zoom: m.a };
    });
  await expect
    .poll(async () => (await matrix()).zoom)
    .toBeGreaterThanOrEqual(0.7);
  const before = await matrix();
  const scrollBefore = await page.evaluate(() => scrollY);
  await page.keyboard.down("Shift");
  await page.mouse.wheel(0, 250);
  await page.keyboard.up("Shift");
  await expect.poll(matrix).not.toEqual(before);
  expect((await matrix()).zoom).toBeCloseTo(before.zoom, 3);
  expect(await page.evaluate(() => scrollY)).toBe(scrollBefore);
  await page.mouse.wheel(0, -500);
  await expect
    .poll(() => page.evaluate(() => scrollY))
    .toBeLessThan(scrollBefore);
});
