import { expect, test } from "@playwright/test";

for (const status of [503, 403]) {
  test(`catalog ${status} does not shrink the dashboard coverage denominator`, async ({
    page,
  }) => {
    let failed = true;
    await page.route(
      (url) => url.pathname === "/api/v1/frameworks",
      async (route) => {
        if (failed) {
          await route.fulfill({
            status,
            json: { error: "Catalog unavailable" },
          });
        } else {
          await route.continue();
        }
      },
    );
    await page.goto("/console/dashboard/");
    const assessment = page.getByRole("region", {
      name: "Latest lake assessment",
    });
    await expect(assessment).toBeVisible();
    const coverage = assessment.getByRole("link", {
      name: /^Assessed coverage/,
    });
    await expect(coverage).toContainText("Framework catalog unavailable");
    await expect(coverage.getByRole("progressbar")).toHaveCount(0);
    await expect(
      assessment.getByText(/\d+ of \d+ framework packs assessed/),
    ).toHaveCount(0);
    await expect(assessment.getByText("Loading framework catalog")).toHaveCount(
      0,
    );
    await expect(
      assessment.getByRole("link", { name: /^Open findings/ }),
    ).toBeVisible();
    const error = page
      .getByRole("tabpanel", { name: "Frameworks", exact: true })
      .getByRole("alert")
      .filter({
        hasText:
          status === 403 ? "permission" : "Couldn’t load framework catalog",
      });
    await expect(error).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Framework posture list" }),
    ).toHaveCount(0);
    if (status === 503) {
      failed = false;
      await error.getByRole("button", { name: "Retry", exact: true }).click();
      await expect(error).toHaveCount(0);
      await expect(
        assessment.getByText(/\d+ of 22 framework packs assessed/),
      ).toBeVisible();
      await expect(coverage.getByRole("progressbar")).toBeVisible();
    } else {
      await expect(
        error.getByRole("button", { name: "Retry", exact: true }),
      ).toHaveCount(0);
    }
  });
}

test("pending catalog never uses observed framework count as the total", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    (url) => url.pathname === "/api/v1/frameworks",
    async (route) => {
      await gate;
      await route.continue();
    },
  );
  try {
    await page.goto("/console/dashboard/");
    const assessment = page.getByRole("region", {
      name: "Latest lake assessment",
    });
    await expect(assessment).toBeVisible();
    await expect(
      assessment.getByText("Loading framework catalog"),
    ).toBeVisible();
    await expect(
      assessment.getByText(/\d+ of \d+ framework packs assessed/),
    ).toHaveCount(0);
  } finally {
    release();
  }
});

test("failed catalog refresh does not keep cached coverage looking current", async ({
  page,
}) => {
  let failed = false;
  await page.route(
    (url) => url.pathname === "/api/v1/frameworks",
    async (route) => {
      if (failed)
        await route.fulfill({
          status: 503,
          json: { error: "Catalog unavailable" },
        });
      else await route.continue();
    },
  );
  await page.goto("/console/dashboard/");
  const assessment = page.getByRole("region", {
    name: "Latest lake assessment",
  });
  await expect(
    assessment.getByText(/\d+ of 22 framework packs assessed/),
  ).toBeVisible();
  failed = true;
  await page.getByRole("button", { name: "Refresh data", exact: true }).click();
  await expect(
    assessment.getByRole("link", { name: /^Assessed coverage/ }),
  ).toContainText("Framework catalog unavailable");
  await expect(
    assessment.getByText(/\d+ of \d+ framework packs assessed/),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Framework posture list" }),
  ).toHaveCount(0);
  await expect(
    assessment.getByRole("link", { name: /^Open findings/ }),
  ).toBeVisible();
});
