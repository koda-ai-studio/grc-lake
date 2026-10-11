import { expect, test, type Page } from "@playwright/test";

const endpoint = "**/api/v1/ccf/requirement-gaps?*";
const row = {
  control_id: "SOC2-CC6.1",
  framework_id: "soc2",
  status: "stale",
  gap_codes: ["mapping_review_pending", "safeguard_stale", "unassessed_assets"],
  has_gaps: true,
  reviewed_safeguard_count: 1,
  pending_mapping_count: 2,
  contextual_mapping_count: 0,
  blocking_safeguards: [
    {
      safeguard_id: "SG-IDENTITY-001",
      status: "stale",
      unassessed_asset_count: 3,
      invalid_binding_count: 0,
    },
  ],
  population_completeness: "not_established",
};
function body(data = [row]) {
  return {
    data,
    meta: {
      count: data.length,
      returned: data.length,
      generation: {
        generation_id: "frozen-demo-17",
        manifest_sha256: "a".repeat(64),
      },
    },
    errors: [],
  };
}
async function openRequirement(page: Page) {
  await page.goto("/console/frameworks/?framework=soc2&control=SOC2-CC6.1");
  const section = page.locator('[id="control-SOC2-CC6.1"]');
  await expect(section).toBeVisible();
  return section;
}

test("explains frozen blockers and next actions without implying coverage", async ({
  page,
}) => {
  let calls = 0;
  await page.route(endpoint, async (route) => {
    calls++;
    const url = new URL(route.request().url());
    expect(url.searchParams.get("control_id")).toBe(row.control_id);
    expect(url.searchParams.get("framework_id")).toBe(row.framework_id);
    await route.fulfill({ json: body() });
  });
  const section = await openRequirement(page);
  expect(calls).toBe(0);
  await section
    .getByRole("button", { name: "Explain assessment gaps" })
    .click();
  const panel = section.getByRole("region", {
    name: "Frozen requirement gaps",
  });
  await expect(panel).toContainText("Stored result: Stale");
  await expect(panel).toContainText("Refresh stale evidence");
  await panel.getByText("Blocking safeguards (1)", { exact: true }).click();
  await expect(panel).toContainText("3 unassessed observed assets");
  await panel.getByText("Frozen assessment source", { exact: true }).click();
  await expect(panel).toContainText("frozen-demo-17");
  await expect(panel).toContainText(
    "Complete asset inventory is not established",
  );
  await expect(
    panel.getByRole("link", { name: "Review mappings" }),
  ).toHaveAttribute("href", /mapping-review.*framework=soc2/);
  await section.getByRole("button", { name: "Hide assessment gaps" }).click();
  await section
    .getByRole("button", { name: "Explain assessment gaps" })
    .click();
  await expect.poll(() => calls).toBe(2);
});

test("unavailable generation can retry without displaying old coverage", async ({
  page,
}) => {
  let unavailable = true;
  await page.route(endpoint, (route) =>
    route.fulfill(
      unavailable
        ? { status: 409, json: { errors: [{ message: "unavailable" }] } }
        : { json: body() },
    ),
  );
  const section = await openRequirement(page);
  await section
    .getByRole("button", { name: "Explain assessment gaps" })
    .click();
  const panel = section.getByRole("region", {
    name: "Frozen requirement gaps",
  });
  await expect(panel.getByRole("alert")).toContainText(
    "Assessment details are unavailable or have changed",
  );
  await expect(panel).not.toContainText("Stored result");
  unavailable = false;
  await panel.getByRole("button", { name: "Retry latest assessment" }).click();
  await expect(panel).toContainText("Stored result: Stale");
});

test("missing rows and missing provenance never become a pass", async ({
  page,
}) => {
  await page.route(endpoint, (route) => route.fulfill({ json: body([]) }));
  const section = await openRequirement(page);
  await section
    .getByRole("button", { name: "Explain assessment gaps" })
    .click();
  const panel = section.getByRole("region", {
    name: "Frozen requirement gaps",
  });
  await expect(panel).toContainText(
    "No frozen result is available for this requirement",
  );
  await page.unroute(endpoint);
  await page.route(endpoint, (route) =>
    route.fulfill({ json: { data: [row], meta: {} } }),
  );
  await panel.getByRole("button", { name: "Retry latest assessment" }).click();
  await expect(panel.getByRole("alert")).toContainText(
    "Assessment details could not be loaded",
  );
  await expect(panel).not.toContainText("Stored result");
});

test("unknown packaged console route has branded keyboard recovery on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const response = await page.goto("/console/this-page-does-not-exist/");
  expect(response?.status()).toBe(404);
  await expect(
    page.getByRole("heading", { name: "This page is not available" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "GRC Lake", exact: true }).first(),
  ).toBeVisible();
  const recovery = page.getByRole("link", { name: "Return to overview" });
  await recovery.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/console\/dashboard\/?$/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("a late response from a closed panel cannot replace a newly opened result", async ({
  page,
}) => {
  let calls = 0;
  let releaseFirst!: () => void;
  const held = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  await page.route(endpoint, async (route) => {
    const call = ++calls;
    if (call === 1) await held;
    await route.fulfill({
      json: body([{ ...row, status: call === 1 ? "pass" : "stale" }]),
    });
  });
  const section = await openRequirement(page);
  await section
    .getByRole("button", { name: "Explain assessment gaps" })
    .click();
  await expect.poll(() => calls).toBe(1);
  await section.getByRole("button", { name: "Hide assessment gaps" }).click();
  await section
    .getByRole("button", { name: "Explain assessment gaps" })
    .click();
  const panel = section.getByRole("region", {
    name: "Frozen requirement gaps",
  });
  await expect(panel).toContainText("Stored result: Stale");
  const returned = page.waitForResponse((response) =>
    response.url().includes("requirement-gaps"),
  );
  releaseFirst();
  await returned;
  await expect(panel).toContainText("Stored result: Stale");
  await expect(panel).not.toContainText("Stored result: Pass");
});

test("real frozen API remains usable in mobile dark mode", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem("theme", "dark"));
  const section = await openRequirement(page);
  await section
    .getByRole("button", { name: "Explain assessment gaps" })
    .click();
  const panel = section.getByRole("region", {
    name: "Frozen requirement gaps",
  });
  await expect(panel).toContainText("Stored result:");
  await expect(panel).toContainText(
    "Complete asset inventory is not established",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
