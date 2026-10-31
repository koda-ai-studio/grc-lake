import { expect, test, type Page } from "@playwright/test";

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

async function mockReviewIdentity(
  page: Page,
  authMethod: string,
  scopes = ["read", "mapping_review"],
) {
  await page.route("**/api/v1/auth/whoami", (route) =>
    route.fulfill({
      json: {
        data: {
          user_id: "synthetic-reviewer",
          tenant_id: "synthetic-workspace",
          email: "reviewer@example.test",
          role: "compliance_reviewer",
          scopes,
          auth_method: authMethod,
        },
      },
    }),
  );
}

async function openQueue(page: Page) {
  await page.goto("/console/mapping-review/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Mapping review" }),
  ).toBeVisible({ timeout: 20_000 });
  const table = page.getByRole("table", { name: "Mappings to review" });
  await expect(table.getByRole("row").nth(1)).toBeVisible({ timeout: 20_000 });
  return table;
}

test.describe("mapping review", () => {
  test("shows per-framework progress with the review states kept apart", async ({
    page,
  }) => {
    await openQueue(page);
    const progress = page.getByRole("region", { name: "Review progress" });
    await expect(progress).toBeVisible();
    for (const label of [
      "Maintainer-reviewed",
      "Org-reviewed",
      "Needs changes",
      "Rejected",
      "Pending",
    ]) {
      await expect(
        progress.locator("summary").getByText(label, { exact: true }),
      ).toBeVisible();
    }
    // The shared glossary defines each state on demand.
    await progress.getByText("What these mean").click();
    await expect(
      progress.getByText(
        "Approved by a reviewer in your organization, with a rationale.",
      ),
    ).toBeVisible();
    await expect(
      progress.getByText(/org-reviewed \d[\d,]* of \d[\d,]* mappings/).first(),
    ).toBeVisible();
    // The unit is mappings here; Frameworks counts requirements.
    await expect(
      progress.getByText(/^Of \d[\d,]* safeguard-to-requirement mappings:/),
    ).toBeVisible();
    await expect(
      progress.getByText(/Counts are mappings, not requirements/),
    ).toBeVisible();
    // An empty decision log never reads as "verified · 0".
    await expect(progress.getByText(/Decision log verified · 0/)).toHaveCount(
      0,
    );
  });

  test("insecure console cannot approve a pending mapping", async ({
    page,
  }) => {
    const table = await openQueue(page);
    const checkbox = table.getByRole("row").nth(1).getByRole("checkbox");
    await checkbox.focus();
    await page.keyboard.press("Space");
    await expect(checkbox).toBeChecked();
    const decision = page.getByRole("region", { name: "Record a decision" });
    await expect(decision.getByText("1 selected")).toBeVisible();
    await expect(decision.getByText(/signed-in console session/)).toBeVisible();
    await expect(decision.getByLabel("Rationale")).toHaveCount(0);
    await expect(decision.getByRole("button")).toHaveCount(0);
    await expect(page.getByText("Recorded 1 decision")).toHaveCount(0);
    await table
      .getByRole("button", { name: /^History for/ })
      .first()
      .click();
    const drawer = page.getByRole("region", { name: "Decide this mapping" });
    await expect(drawer.getByText(/signed-in console session/)).toBeVisible();
    await expect(drawer.getByRole("button")).toHaveCount(0);
  });

  test("works at 390px without horizontal page scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openQueue(page);
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(
      page.getByRole("combobox", { name: "Filter by framework" }),
    ).toBeVisible();
  });

  test("frameworks page links to the review queue and splits reviewer types", async ({
    page,
  }) => {
    await page.goto("/console/frameworks/");
    const portfolio = page.getByRole("region", {
      name: "Framework coverage summary",
    });
    await expect(portfolio).toBeVisible({ timeout: 20_000 });
    await expect(portfolio.getByText(/maintainer-reviewed/)).toBeVisible();
    await expect(portfolio.getByText(/org-reviewed/)).toBeVisible();
    await portfolio.getByRole("link", { name: "Review mappings" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Mapping review" }),
    ).toBeVisible({ timeout: 20_000 });
  });
});

test("contextual mappings are visibly separate from coverage", async ({
  page,
}) => {
  await page.route("**/api/v1/mapping-reviews/queue?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (Array.isArray(body.data) && body.data.length > 1) {
      body.data[0] = {
        ...body.data[0],
        role: "supporting",
        contributes_to_coverage: false,
      };
      body.data[1] = {
        ...body.data[1],
        role: "inherited",
        contributes_to_coverage: false,
      };
    }
    await route.fulfill({ response, json: body });
  });
  const table = await openQueue(page);
  // Assert the injected rows independently of other contextual catalog mappings.
  for (const [index, role] of ["supporting", "inherited"].entries()) {
    const row = table.getByRole("row").nth(index + 1);
    await expect(
      row.getByText("Context only · no coverage credit"),
    ).toBeVisible();
    await expect(row.getByText(role, { exact: true })).toBeVisible();
  }
});

test("review drawer exposes operating and evidence requirements", async ({
  page,
}, testInfo) => {
  const table = await openQueue(page);
  await table
    .getByRole("button", { name: /^History for/ })
    .first()
    .click();
  const contract = page.getByRole("region", {
    name: "Mapping evidence contract",
  });
  await expect(contract.getByText("Compare the obligations")).toBeVisible();
  await contract.getByText("Evidence and assessment requirements").click();
  await expect(contract.getByText(/Required evidence types:/)).toBeVisible();
  await expect(contract.getByText(/Asset types:/)).toBeVisible();
  await expect(
    page.getByText(/No organization decisions yet. Current state:/),
  ).toBeVisible();
  await contract.getByText("Compare the obligations").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("mapping-evidence-contract.png"),
    fullPage: false,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(contract.getByText("Compare the obligations")).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await page.screenshot({
    path: testInfo.outputPath("mapping-evidence-contract-mobile.png"),
    fullPage: false,
  });
});

test("stale review clears the selection without claiming a decision", async ({
  page,
}) => {
  await mockReviewIdentity(page, "session:oidc");
  await page.route("**/api/v1/mapping-reviews/decisions", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        data: null,
        errors: [
          {
            code: "bad_request",
            detail:
              "mapping decision history changed; refresh the queue and review again",
          },
        ],
      }),
    });
  });
  const table = await openQueue(page);
  const checkbox = table.getByRole("row").nth(1).getByRole("checkbox");
  await checkbox.check();
  const decision = page.getByRole("region", { name: "Record a decision" });
  await decision.getByLabel("Rationale").fill("Previously inspected evidence.");
  await decision.getByRole("button", { name: "Approve" }).click();
  await expect(
    page.getByText(/mapping decision history changed/),
  ).toBeVisible();
  await expect(checkbox).not.toBeChecked();
  await expect(page.getByText("Recorded 1 decision")).toHaveCount(0);
});

test("a stale approval is history without current review credit", async ({
  page,
}) => {
  const stale = {
    decision_id: "synthetic-stale-approval",
    decision: "approve",
    reviewer: "reviewer@example.test",
    reviewer_role: "compliance_reviewer",
    decided_at: "2026-10-14T12:00:00Z",
    rationale: "Prior definition only.",
    evidence_ref: null,
    basis_verified: false,
    auth_method: "oidc",
    supersedes: null,
  };
  await page.route("**/api/v1/mapping-reviews/queue?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.data[0] = {
      ...body.data[0],
      review_state: "proposed",
      latest_decision: stale,
      expected_decision_id: stale.decision_id,
    };
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/v1/mapping-reviews/decisions?**", async (route) => {
    await route.fulfill({
      json: { data: [stale], errors: [], meta: { count: 1 } },
    });
  });
  const table = await openQueue(page);
  await table
    .getByRole("button", { name: /^History for/ })
    .first()
    .click();
  const history = page.getByRole("region", { name: "Decision history" });
  await expect(
    history.getByText("Needs renewed review", { exact: true }),
  ).toBeVisible();
  await expect(history.getByText("In force", { exact: true })).toHaveCount(0);
});

test("background queue refresh cannot replace the selected review basis", async ({
  page,
}) => {
  await mockReviewIdentity(page, "session:saml");
  await page.clock.install();
  let reads = 0;
  await page.route("**/api/v1/mapping-reviews/queue?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    reads += 1;
    body.data[0] = {
      ...body.data[0],
      review_basis_sha256: (reads === 1 ? "1" : "2").repeat(64),
    };
    await route.fulfill({ response, json: body });
  });
  const table = await openQueue(page);
  await table.getByRole("row").nth(1).getByRole("checkbox").check();
  await page.clock.runFor(16_000);
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect.poll(() => reads).toBeGreaterThan(1);
  const decision = page.getByRole("region", { name: "Record a decision" });
  await expect(
    decision.getByRole("button", { name: "Approve" }),
  ).toBeDisabled();
  await decision
    .getByLabel("Rationale")
    .fill("I inspected the original definition.");
  await page.route("**/api/v1/mapping-reviews/decisions", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    return route.fulfill({
      status: 400,
      json: {
        data: null,
        errors: [
          { code: "bad_request", detail: "Synthetic submission captured" },
        ],
      },
    });
  });
  const submission = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/mapping-reviews/decisions"),
  );
  await decision.getByRole("button", { name: "Approve" }).click();
  const submitted = (await submission).postDataJSON();
  expect(submitted.items[0].review_basis_sha256).toBe("1".repeat(64));
  expect(submitted.items[0]).toHaveProperty("expected_decision_id", null);
  await expect(page.getByText("Synthetic submission captured")).toBeVisible();
});

test("an out-of-date maintainer review is not labeled as a current review", async ({
  page,
  request,
}) => {
  const body = (await (
    await request.get("/api/v1/mapping-reviews/queue?limit=200")
  ).json()) as {
    data: Array<{
      control_id: string;
      shipped_review_status: string;
      review_state: string;
      mapping_source?: string | null;
      mapping_basis?: string | null;
    }>;
  };
  // Exercise the UI contract independently of which shipped mappings are pending.
  const stale = body.data[0];
  expect(stale).toBeDefined();
  await page.route("**/api/v1/mapping-reviews/queue**", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.data = payload.data.map((row: { control_id: string }) =>
      row.control_id === stale.control_id
        ? {
            ...row,
            shipped_review_status: "reviewed",
            review_state: "proposed",
            mapping_source: null,
            mapping_basis: null,
          }
        : row,
    );
    await route.fulfill({ response, json: payload });
  });
  const table = await openQueue(page);
  await page
    .getByPlaceholder("Search requirement or safeguard")
    .fill(stale.control_id);
  const row = table
    .getByRole("row")
    .filter({ hasText: stale.control_id })
    .first();
  await expect(row).toContainText("Earlier maintainer review");
  await expect(row).not.toContainText(/Maintainer review(?! )/);
  await page.unrouteAll({ behavior: "wait" });
});

test("framework marks fit their badge on one line", async ({ page }) => {
  await openQueue(page);
  const marks = page.locator('[role="img"][aria-label$=" framework"]');
  await expect(marks.first()).toBeVisible();
  const broken = await marks.evaluateAll((elements) =>
    elements
      .filter((el) => {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const lines = new Set<number>();
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const range = document.createRange();
          range.selectNodeContents(node);
          for (const rect of range.getClientRects())
            lines.add(Math.round(rect.top));
        }
        return (
          lines.size > 1 ||
          el.scrollWidth > el.clientWidth + 1 ||
          el.scrollHeight > el.clientHeight + 1
        );
      })
      .map((el) => el.getAttribute("aria-label")),
  );
  expect(broken).toEqual([]);
});

for (const [method, scopes] of [
  ["api_key", ["read", "mapping_review"]],
  ["session:api_key", ["read", "mapping_review"]],
  ["session:oidc", ["read"]],
  ["session:saml", ["read"]],
] as const) {
  test(`${method} with ${scopes.join(",")} cannot record mapping decisions`, async ({
    page,
  }) => {
    await mockReviewIdentity(page, method, [...scopes]);
    let submissions = 0;
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        request.url().endsWith("/api/v1/mapping-reviews/decisions")
      )
        submissions += 1;
    });
    const table = await openQueue(page);
    await table.getByRole("row").nth(1).getByRole("checkbox").check();
    const decision = page.getByRole("region", { name: "Record a decision" });
    await expect(decision.getByText(/signed-in console session/)).toBeVisible();
    await expect(decision.getByLabel("Rationale")).toHaveCount(0);
    await expect(decision.getByRole("button")).toHaveCount(0);
    await table
      .getByRole("button", { name: /^History for/ })
      .first()
      .click();
    const drawer = page.getByRole("region", { name: "Decide this mapping" });
    await expect(drawer.getByText(/signed-in console session/)).toBeVisible();
    await expect(drawer.getByRole("button")).toHaveCount(0);
    expect(submissions).toBe(0);
  });
}
