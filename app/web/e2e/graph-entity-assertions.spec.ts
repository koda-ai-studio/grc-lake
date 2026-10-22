import { expect, test } from "@playwright/test";

const canonical = {
  id: "canonical:device-17",
  kind: "canonical_entity",
  label: "device-17",
  status: "caller_asserted",
  basis: "Caller-asserted canonical identity; source records remain separate",
};
const alias = {
  id: "alias:intune",
  kind: "entity_alias",
  label: "Alias for device-17",
  status: "caller_asserted",
  source_account_id: "org",
  provider: "intune",
  asserted_by: "reviewer",
  asserted_at: "2026-10-21T13:00:00Z",
  assertion_reason: "Enrollment reference",
  binding_revision: 1,
  evidence_sha256: "a".repeat(64),
  binding_record_hash: "b".repeat(64),
  basis:
    "Caller-asserted alias; not authenticated approval or a compliance verdict",
};
const evidence = {
  id: "evidence:1",
  kind: "evidence_type",
  label: "device.posture",
  status: "pass",
};

for (const theme of ["light", "dark"]) {
  test(`canonical assertions show provenance in ${theme} desktop and mobile views`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.addInitScript(
      (value) => localStorage.setItem("trustops:theme", JSON.stringify(value)),
      theme,
    );
    await page.route("**/api/v1/graph/investigation?*", (route) =>
      route.fulfill({
        json: {
          data: {
            version: "assertions-v1",
            root: canonical.id,
            root_missing: false,
            roots: [canonical],
            root_count: 1,
            root_offset: 0,
            next_root_offset: null,
            nodes: [canonical, alias, evidence],
            edges: [
              {
                id: "claim",
                source: canonical.id,
                target: alias.id,
                kind: "has_alias_assertion",
                review_state: "caller_asserted",
              },
              {
                id: "anchor",
                source: alias.id,
                target: evidence.id,
                kind: "assertion_references_evidence",
                review_state: "caller_asserted",
              },
            ],
            counts: { canonical_entity: 1, entity_alias: 1, evidence_type: 1 },
            framework_groups: [],
            selected_framework: "",
            control_count: 0,
            control_offset: 0,
            next_control_offset: null,
            depth: 2,
            limit: 150,
            truncated: false,
            matching_nodes: 3,
            boundary: "Recorded relationships; not network reachability",
          },
        },
      }),
    );
    await page.goto("/console/graph/?root=canonical%3Adevice-17");
    const node = page.locator('.react-flow__node[data-id="alias:intune"]');
    await expect(node).toContainText("Caller asserted");
    await node.click();
    const inspector = page.getByRole("complementary", {
      name: "Selected graph node",
    });
    await expect(inspector).toContainText("not authenticated approval");
    await expect(inspector).toContainText("reviewer");
    await expect(inspector).toContainText("Enrollment reference");
    await expect(inspector).toContainText("a".repeat(64));
    await expect(
      inspector.getByText("Passing evidence", { exact: true }),
    ).toHaveCount(0);
    const paths = page.locator(".react-flow__edge-path");
    await expect(paths).toHaveCount(2);
    expect(
      await paths
        .first()
        .evaluate((el) => getComputedStyle(el).strokeDasharray),
    ).not.toBe("none");
    await page.screenshot({
      path: testInfo.outputPath(`assertions-${theme}.png`),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(inspector).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(391);
    await page.screenshot({
      path: testInfo.outputPath(`assertions-${theme}-mobile.png`),
      fullPage: true,
    });
  });
}
