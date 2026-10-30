import { expect, test } from "@playwright/test";

test("graph preserves failing posture and record labels across views", async ({
  page,
}) => {
  await page.goto("/console/graph/");
  const control = page.locator(
    '.react-flow__node[data-id="control:SOC2-CC6.1"]',
  );
  await expect(control).toContainText("Failing control");
  const color = await control
    .getByTestId("graph-node-icon")
    .evaluate((el) => getComputedStyle(el).color);
  const danger = await page.evaluate(() =>
    getComputedStyle(document.documentElement)
      .getPropertyValue("--color-danger")
      .trim(),
  );
  expect(color).toBe(
    await page.evaluate((value) => {
      const el = document.createElement("span");
      el.style.color = value;
      document.body.append(el);
      const rgb = getComputedStyle(el).color;
      el.remove();
      return rgb;
    }, danger),
  );
  await expect(
    page
      .locator(".react-flow__node")
      .filter({ hasText: "Failing evidence" })
      .first(),
  ).toBeVisible();
  const canvas = page.locator(".react-flow");
  expect((await canvas.boundingBox())!.y).toBeLessThan(440);
  await page.goto("/console/graph/?focus=control%3ASOC2-CC6.1");
  await expect(control).toContainText("Failing control");
  await expect(
    page
      .locator(".react-flow__node")
      .filter({ hasText: "Failing evidence" })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByText("First ten catalog controls", { exact: false }),
  ).toBeVisible();
});

test("safeguard groups expose full counts and page five controls without wheel zoom", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
  const framework = page.getByRole("combobox", {
    name: "Safeguard framework",
    exact: true,
  });
  await expect(framework).toBeVisible();
  await framework.selectOption("fedramp-moderate");
  const groups = page.getByLabel("Safeguard framework groups", { exact: true });
  await expect(groups).toContainText("mapped controls across");
  const nodes = page.locator('.react-flow__node[data-id^="control:"]');
  await expect(nodes).toHaveCount(5);
  await expect(
    page.locator('.react-flow__node[data-id="safeguard:SG-IDENTITY-001"]'),
  ).toContainText("Not evaluated");
  const before = await nodes.evaluateAll((els) =>
    els.map((el) => el.getAttribute("data-id")),
  );
  await page.getByRole("button", { name: "Next mapped controls" }).click();
  await expect
    .poll(() =>
      nodes.evaluateAll((els) => els.map((el) => el.getAttribute("data-id"))),
    )
    .not.toEqual(before);
  expect(await nodes.count()).toBeLessThanOrEqual(5);
  const viewport = page.locator(".react-flow__viewport");
  await page.waitForTimeout(600);
  const scale = await viewport.evaluate(
    (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
  );
  await page.locator(".react-flow").hover();
  await page.mouse.wheel(0, 300);
  await page.waitForTimeout(300);
  expect(
    await viewport.evaluate(
      (el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).a,
    ),
  ).toBeCloseTo(scale, 4);
});

async function openSafeguard(page: import("@playwright/test").Page) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/graph/?root=safeguard%3ASG-IDENTITY-001");
  await page
    .getByRole("combobox", { name: "Safeguard framework", exact: true })
    .selectOption("fedramp-moderate");
  await expect(
    page.locator('.react-flow__node[data-id^="control:"]'),
  ).toHaveCount(5);
  await page.waitForTimeout(400);
}

test("safeguard paths never cross node labels", async ({ page }) => {
  await openSafeguard(page);
  const collisions = await page.evaluate(() => {
    const labels = [
      ...document.querySelectorAll('[data-testid="graph-node-label"]'),
    ].map((el) => ({ text: el.textContent, box: el.getBoundingClientRect() }));
    return [
      ...document.querySelectorAll<SVGPathElement>(".react-flow__edge-path"),
    ].flatMap((path) => {
      const matrix = path.getScreenCTM()!;
      const hits = new Set<string>();
      for (let distance = 0; distance < path.getTotalLength(); distance += 2) {
        const point = path.getPointAtLength(distance).matrixTransform(matrix);
        for (const label of labels)
          if (
            point.x > label.box.left &&
            point.x < label.box.right &&
            point.y > label.box.top &&
            point.y < label.box.bottom
          )
            hits.add(label.text ?? "");
      }
      return [...hits];
    });
  });
  expect(collisions).toEqual([]);
});

test("dragged nodes keep their position and hover emphasizes only their links", async ({
  page,
}) => {
  await openSafeguard(page);
  const node = page.locator(
    '.react-flow__node[data-id="control:FEDRAMP-AC-11"]',
  );
  await node.scrollIntoViewIfNeeded();
  await expect(node).toBeInViewport();
  const original = await node.getAttribute("style");
  const icon = await node.getByTestId("graph-node-icon").boundingBox();
  await page.mouse.move(icon!.x + icon!.width / 2, icon!.y + icon!.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    icon!.x + icon!.width / 2 + 55,
    icon!.y + icon!.height / 2 + 20,
    { steps: 12 },
  );
  await page.mouse.up();
  await expect.poll(() => node.getAttribute("style")).not.toBe(original);
  const moved = await node.getAttribute("style");
  await node.hover();
  await expect
    .poll(() =>
      page
        .locator(".react-flow__edge-path")
        .evaluateAll(
          (els) =>
            els.filter((el) => Number(getComputedStyle(el).opacity) < 0.5)
              .length,
        ),
    )
    .toBeGreaterThan(0);
  await page
    .getByRole("heading", { name: "Evidence investigation", exact: true })
    .hover();
  await expect(node).toHaveAttribute("style", moved!);
});

test("dragging toward another card preserves the gap between cards", async ({
  page,
}) => {
  await openSafeguard(page);
  const node = page.locator(
    '.react-flow__node[data-id="control:FEDRAMP-AC-11"]',
  );
  const other = page.locator(
    '.react-flow__node[data-id="control:FEDRAMP-AC-12"]',
  );
  const start = (await node.getByTestId("graph-node-icon").boundingBox())!;
  const target = (await other.getByTestId("graph-node-icon").boundingBox())!;
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    target.x + target.width / 2,
    target.y + target.height / 2,
    { steps: 20 },
  );
  await page.mouse.up();
  const a = (await node.boundingBox())!;
  const b = (await other.boundingBox())!;
  expect(
    a.x + a.width <= b.x ||
      b.x + b.width <= a.x ||
      a.y + a.height <= b.y ||
      b.y + b.height <= a.y,
  ).toBe(true);
});
