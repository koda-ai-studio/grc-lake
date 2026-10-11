import { test, expect } from "@playwright/test";

test("auditor can trace exact frozen results without treating hash integrity as assurance", async ({
  page,
}) => {
  await page.goto("/console/evidence/?id=golden-001");
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "Trace frozen results" }).click();
  await expect(
    drawer.getByText("Generation integrity verified", { exact: true }),
  ).toBeVisible();
  await expect(drawer).toContainText("Source account");
  await expect(drawer).toContainText("Declared control");
  await expect(drawer).toContainText("does not establish source authenticity");
});

test("verification errors are visible and can be retried", async ({ page }) => {
  await page.route("**/api/v1/evidence/*/verify", (route) =>
    route.fulfill({
      status: 503,
      json: { errors: [{ detail: "unavailable" }] },
    }),
  );
  await page.goto("/console/evidence/?id=golden-001");
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "Verify hash" }).click();
  await expect(drawer.getByRole("alert")).toContainText(
    "Hash verification could not be completed",
  );
  await expect(
    drawer.getByRole("button", { name: "Verify hash" }),
  ).toBeEnabled();
});

test("unavailable lineage never displays a verified conclusion", async ({
  page,
}) => {
  await page.route("**/api/v1/evidence/*/lineage?*", (route) =>
    route.fulfill({
      status: 409,
      json: { errors: [{ detail: "unavailable" }] },
    }),
  );
  await page.goto("/console/evidence/?id=golden-001");
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "Trace frozen results" }).click();
  await expect(drawer.getByRole("alert")).toContainText(
    "Lineage could not be verified",
  );
  await expect(
    drawer.getByText("Generation integrity verified", { exact: true }),
  ).toHaveCount(0);
});

test("lineage pagination pins the generation and rejects drift", async ({
  page,
}) => {
  let pageCount = 0;
  await page.route("**/api/v1/evidence/*/lineage?*", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    pageCount++;
    if (query.get("offset") === "5") {
      expect(query.get("generation_id")).toBe("frozen-generation");
      await route.fulfill({
        status: 409,
        json: { errors: [{ detail: "generation changed" }] },
      });
      return;
    }
    await route.fulfill({
      json: {
        data: {
          event_id: "golden-001",
          raw_sha256: "a".repeat(64),
          source: {
            source_account_id: "fixture-account",
            source_event_id: "golden-001",
            connector_id: null,
            source: "fixture",
            event_time: "2026-01-01T00:00:00Z",
          },
          integrity: {
            verified: true,
            external_authenticity: "not_established",
          },
          generation: {
            generation_id: "frozen-generation",
            manifest_sha256: "b".repeat(64),
          },
          links: Array.from({ length: 5 }, (_, index) => ({
            kind: "declared_control",
            control_id: `CONTROL-${index}`,
            result: "not_evaluated",
          })),
        },
        meta: { count: 6, returned: 5 },
      },
    });
  });
  await page.goto("/console/evidence/?id=golden-001");
  const drawer = page.getByRole("dialog");
  expect(pageCount).toBe(0);
  await drawer.getByRole("button", { name: "Trace frozen results" }).click();
  await drawer.getByRole("button", { name: "Next links" }).click();
  await expect(drawer.getByRole("alert")).toBeVisible();
  await expect(
    drawer.getByText("Generation integrity verified", { exact: true }),
  ).toHaveCount(0);
  await drawer.getByRole("button", { name: "Reload trace" }).click();
  await expect(
    drawer.getByText("Generation integrity verified", { exact: true }),
  ).toBeVisible();
});

test("late verification of a closed record cannot mark a different record verified", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested = false;
  await page.route("**/api/v1/evidence/golden-001/verify", async (route) => {
    requested = true;
    await gate;
    await route.fulfill({
      json: {
        data: {
          verified: true,
          source_layer: "bronze",
          expected_sha256: "a".repeat(64),
          computed_sha256: "a".repeat(64),
        },
      },
    });
  });
  await page.goto("/console/evidence/?id=golden-001");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Verify hash" })
    .click();
  await expect.poll(() => requested).toBe(true);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page
    .getByRole("button", { name: /^Open evidence golden-002 from / })
    .click();
  const response = page.waitForResponse("**/api/v1/evidence/golden-001/verify");
  release();
  await response;
  await page.waitForTimeout(100);
  await expect(page.getByRole("dialog")).not.toContainText(
    "Hash matches bronze raw record.",
  );
});

test("reopening evidence keeps cached lineage behind the explicit trace action", async ({
  page,
}) => {
  await page.goto("/console/evidence/?id=golden-001");
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "Trace frozen results" }).click();
  await expect(
    drawer.getByText("Generation integrity verified", { exact: true }),
  ).toBeVisible();
  await drawer.getByRole("button", { name: "Close", exact: true }).click();
  await page
    .getByRole("button", { name: /^Open evidence golden-001 from / })
    .click();
  await expect(
    drawer.getByRole("button", { name: "Trace frozen results" }),
  ).toBeVisible();
  await expect(
    drawer.getByText("Generation integrity verified", { exact: true }),
  ).toHaveCount(0);
});
