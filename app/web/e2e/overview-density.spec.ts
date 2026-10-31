import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"]) {
  test(`BambooHR, BigQuery and Google Cloud use brand marks in ${theme} mode`, async ({
    page,
  }) => {
    await page.addInitScript((mode) => {
      window.localStorage.setItem("trustops:theme", JSON.stringify(mode));
    }, theme);
    await page.goto("/console/connectors/");
    for (const [search, vendor] of [
      ["BambooHR", "BambooHR"],
      ["BigQuery", "Google BigQuery"],
      ["GCP", "Google Cloud"],
    ]) {
      await page.getByRole("textbox", { name: "Search sources" }).fill(search);
      const mark = page.getByRole("img", {
        name: `${vendor} connector`,
        exact: true,
      });
      await expect(mark.locator("svg")).toBeVisible();
      expect(await mark.locator("svg path").count()).toBeGreaterThan(0);
    }
  });
}

test("connections separates source browsing from account setup and status", async ({
  page,
}) => {
  await page.goto("/console/connectors/");
  await expect(
    page.getByRole("button", { name: "Add account connection", exact: true }),
  ).not.toBeVisible();
  await page
    .getByRole("tab", { name: "Accounts & scope", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Add account connection", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Status", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "From connection to evidence" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Sources", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Search sources" }),
  ).toBeVisible();
});

for (const width of [390, 1440]) {
  test(`connection tiles stay compact and open their full details at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/console/connectors/");
    await page
      .getByRole("textbox", { name: "Search sources" })
      .fill("GitHub Security");
    const open = page.getByRole("button", {
      name: "Open GitHub Security",
      exact: true,
    });
    await expect(open).toBeVisible();
    expect((await open.boundingBox())!.height).toBeLessThanOrEqual(110);
    await open.click();
    const details = page.getByRole("dialog");
    await expect(details).toBeVisible();
    await expect(details).toContainText("GitHub Security");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
  });
}

test("overview pages framework rows and resets after sorting", async ({
  page,
}) => {
  await page.goto("/console/dashboard/");
  const rows = page.getByRole("region", { name: "Framework posture list" });
  await expect(rows.getByRole("link")).toHaveCount(4);
  const first = await rows.getByRole("link").first().getAttribute("href");
  const pages = page.getByRole("navigation", {
    name: "Framework posture pages",
  });
  await pages
    .getByRole("button", { name: "Next framework posture page" })
    .click();
  await expect(rows.getByRole("link")).toHaveCount(4);
  await expect(rows.getByRole("link").first()).not.toHaveAttribute(
    "href",
    first!,
  );
  await page.getByRole("combobox", { name: "Sort" }).selectOption("name");
  await expect(pages.getByRole("status")).toHaveText(/^1–4 of /);
  await expect(
    page.getByRole("button", { name: /^Show all .* framework packs/ }),
  ).toHaveCount(0);
});

for (const width of [390, 1440]) {
  test(`framework KPI explanations are on demand at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/console/frameworks/");
    const summary = page.getByRole("region", {
      name: "Framework coverage summary",
    });
    await expect(
      summary.getByText("Reviewed requirements", { exact: true }),
    ).toBeVisible();
    const explanation = summary.getByText(/source-native self-maps ·/);
    await expect(explanation).not.toBeVisible();
    await summary.getByText("Coverage details", { exact: true }).click();
    await expect(explanation).toBeVisible();
    await expect(
      summary.getByText(/Mapping review counts individual mappings/),
    ).toBeVisible();
    await summary.getByText("Coverage details", { exact: true }).click();
    const cards = summary.locator(":scope > dl > div");
    await expect(cards).toHaveCount(4);
    for (const card of await cards.all()) {
      expect((await card.innerText()).length).toBeLessThan(130);
    }
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
  });
}

test("mobile inspector bounds secondary evidence details without losing provenance", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const node = {
    id: "evidence:density",
    kind: "evidence_type",
    label: "MFA observation",
    status: "not_evaluated",
    source_account_id: "synthetic-account",
    observed_at: "2026-10-01T00:00:00Z",
    collected_at: "2026-10-02T00:00:00Z",
    freshness_status: "missing",
    evidence_sha256: "a".repeat(64),
    control_ids: Array.from({ length: 20 }, (_, i) => `CONTROL-${i}`),
  };
  await page.route("**/api/v1/graph/investigation?*", (route) =>
    route.fulfill({
      json: {
        data: {
          nodes: [node],
          edges: [],
          counts: { evidence_type: 1 },
          root: node.id,
          version: "fixed",
          roots: [node],
          root_count: 1,
          root_offset: 0,
          depth: 2,
          limit: 150,
          truncated: false,
          matching_nodes: 1,
          boundary: "Recorded relationships",
        },
      },
    }),
  );
  await page.goto("/console/graph/?root=evidence%3Adensity");
  await page.locator('.react-flow__node[data-id="evidence:density"]').click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  expect((await inspector.boundingBox())!.height).toBeLessThanOrEqual(650);
  const lifecycle = inspector.getByRole("region", {
    name: "Evidence lifecycle",
  });
  await expect(lifecycle).not.toBeVisible();
  await inspector.getByText("Evidence timeline", { exact: true }).click();
  await expect(lifecycle).toContainText("2026-10-01T00:00:00Z");
  await inspector.getByText("Record provenance", { exact: true }).click();
  await expect(
    inspector.getByText("a".repeat(64), { exact: true }),
  ).toBeVisible();
  await inspector.getByText("Linked controls (20)", { exact: true }).click();
  await expect(inspector.getByRole("link", { name: /^CONTROL-/ })).toHaveCount(
    6,
  );
  await inspector
    .getByRole("button", { name: "Next linked controls page" })
    .click();
  await expect(
    inspector.getByRole("link", { name: "CONTROL-6", exact: true }),
  ).toBeVisible();
});

test("a cached failure does not leave a warning on unrelated pages", async ({
  page,
}) => {
  await page.route("**/api/v1/platform/features", (route) =>
    route.fulfill({
      json: {
        data: {
          commercial_hosted: true,
          plan_usage: true,
          billing: false,
          scim: false,
        },
      },
    }),
  );
  await page.route("**/api/v1/platform/usage", (route) =>
    route.fulfill({ status: 500, json: { detail: "Unavailable" } }),
  );
  await page.goto("/console/auth/");
  await expect(
    page.getByRole("alert").filter({
      hasText: /Some data is unavailable|Can.t reach the assessment API/,
    }),
  ).toBeVisible();
  await page
    .getByRole("banner")
    .locator('a[href="/console/dashboard/"]')
    .click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("alert").filter({
      hasText: /Some data is unavailable|Can.t reach the assessment API/,
    }),
  ).toHaveCount(0);
});

test("audit review scope stays paginated for large evaluations", async ({
  page,
  request,
}) => {
  const response = await request.get("/api/v1/platform/audit-readiness");
  const body = await response.json();
  body.data.frameworks = Array.from({ length: 9 }, (_, i) => ({
    ...body.data.frameworks[0],
    framework: `Density framework ${i}`,
  }));
  body.data.posture.frameworks_total = 9;
  await page.route("**/api/v1/platform/audit-readiness", (route) =>
    route.fulfill({ json: body }),
  );
  await page.goto("/console/audit-room/");
  const scope = page.getByRole("region", { name: "Evaluated framework scope" });
  await expect(scope.getByText(/^Density framework /)).toHaveCount(3);
  await scope
    .getByRole("button", { name: "Next evaluated frameworks page" })
    .click();
  await expect(
    scope.getByText("Density framework 3", { exact: true }),
  ).toBeVisible();
  await expect(scope.getByText(/^Density framework /)).toHaveCount(3);
});
