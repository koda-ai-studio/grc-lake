import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  for (const theme of ["light", "dark"]) {
    test(`posture reasons cannot explain a CCF verdict at ${width}px in ${theme}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(
        (value) =>
          localStorage.setItem("trustops:theme", JSON.stringify(value)),
        theme,
      );
      await page.route("**/api/v1/graph/investigation?*", async (route) => {
        const response = await route.fetch();
        const payload = await response.json();
        const control = payload.data.nodes.find(
          (node: { id: string }) => node.id === "control:SOC2-CC6.1",
        );
        Object.assign(control, {
          status: "pass",
          posture_status: "pass",
          ccf_status: "not_evaluated",
          reviewed_safeguard_count: 0,
          proposed_safeguard_count: 2,
          evaluation_rule: "all_events_pass",
          open_event_count: 0,
          rule_reasons: ["All recorded technical checks passed."],
        });
        await route.fulfill({ response, json: payload });
      });
      await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
      await page
        .locator('.react-flow__node[data-id="control:SOC2-CC6.1"]')
        .click();
      const inspector = page.getByRole("complementary", {
        name: "Selected graph node",
      });
      const framework = inspector.getByRole("region", {
        name: "Framework result",
      });
      await expect(framework).toContainText("Not evaluated");
      await expect(framework).toContainText("0 reviewed");
      await expect(framework).not.toContainText(
        "All recorded technical checks passed.",
      );
      await expect(framework).not.toContainText("Open events");
      const posture = inspector.getByRole("region", {
        name: "Evidence posture",
      });
      await expect(posture).toContainText("Pass");
      await posture.getByText("Posture rule details", { exact: true }).click();
      await expect(posture).toContainText(
        "All recorded technical checks passed.",
      );
      await expect(posture).toContainText(
        "does not establish the CCF framework result",
      );
      await expect(page.getByRole("dialog")).toHaveCount(0);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width + 1);
      await page.screenshot({
        path: `../../build/graph-assessment-${width}-${theme}.png`,
        fullPage: true,
      });
    });
  }
}

test("posture-only records do not imply a recorded framework result", async ({
  page,
}) => {
  await page.route("**/api/v1/graph/investigation?*", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    const control = payload.data.nodes.find(
      (node: { id: string }) => node.id === "control:SOC2-CC6.1",
    );
    for (const key of [
      "ccf_status",
      "reviewed_safeguard_count",
      "proposed_safeguard_count",
      "posture_status",
    ])
      delete control[key];
    control.rule_reasons = ["No evaluated event result is recorded."];
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  await page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]').click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(
    inspector.getByRole("region", { name: "Framework result" }),
  ).toHaveCount(0);
  await expect(
    inspector.getByRole("region", { name: "Evidence posture" }),
  ).toContainText("Not recorded");
});
