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
