import { expect, test, type Page } from "@playwright/test";

const UNAVAILABLE = /not available in the live demo/;
const READ_ONLY = /The live demo is read-only/;
const API_DOWN = /Can.t reach the assessment API|Couldn.t load/;

/**
 * Fail the test on anything a visitor would see as broken: a script error, a
 * console error, a failed asset, or a request that tried to reach a live API.
 */
function watch(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/"))
      problems.push(`live API request: ${request.method()} ${request.url()}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400)
      problems.push(`${response.status()} ${response.url()}`);
  });
  page.on("requestfailed", (request) => {
    // Navigations away abort in-flight RSC prefetches; those are not breakage.
    if (request.failure()?.errorText !== "net::ERR_ABORTED")
      problems.push(`failed: ${request.url()} ${request.failure()?.errorText}`);
  });
  return problems;
}

async function open(page: Page, route: string) {
  await page.goto(`console${route}`);
  await expect(page.getByTestId("demo-banner")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

async function expectHealthy(page: Page) {
  await expect(page.getByText(UNAVAILABLE)).toHaveCount(0);
  await expect(page.getByText(API_DOWN)).toHaveCount(0);
}

test("the site root opens the dashboard with the demo notice", async ({
  page,
}) => {
  const problems = watch(page);
  await page.goto("./");
  await expect(page).toHaveURL(/\/console\/dashboard\/$/);
  const banner = page.getByTestId("demo-banner");
  await expect(banner).toContainText(
    "read-only, synthetic sample data recorded",
  );
  await expect(
    banner.getByRole("link", { name: /Evaluate your own evidence/ }),
  ).toHaveAttribute(
    "href",
    /github\.com\/koda-ai-studio\/grc-lake\/blob\/main\/docs\/PILOT\.md$/,
  );
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  // No live API behind the demo; the status must not claim one.
  await expect(page.getByText("API connected")).toHaveCount(0);
  await expect(page.getByText("Recorded snapshot")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Framework posture list" }),
  ).toBeVisible();
  await expectHealthy(page);
  expect(problems).toEqual([]);
});

test("frameworks list and a framework detail render recorded data", async ({
  page,
}) => {
  const problems = watch(page);
  await open(page, "/frameworks/");
  const roster = page.getByLabel("Framework roster").locator("li");
  await expect(roster.nth(3)).toBeVisible();
  await open(page, "/frameworks/?framework=soc2");
  await expect(page.getByText(/SOC 2/).first()).toBeVisible();
  await expectHealthy(page);
  expect(problems).toEqual([]);
});

test("controls table opens a control drawer with its tabs", async ({
  page,
}) => {
  const problems = watch(page);
  await open(page, "/controls/");
  const rows = page.locator("main table tbody tr");
  await expect(rows.nth(5)).toBeVisible();
  await rows.nth(2).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  for (const tab of await drawer.getByRole("tab").all()) {
    await tab.click();
    await expectHealthy(page);
  }
  expect(problems).toEqual([]);
});

test("graph selects a node and drills into it", async ({ page }) => {
  const problems = watch(page);
  await open(page, "/graph/");
  await page.keyboard.press("Escape");
  await page.locator('.react-flow__node[data-id="control:SOC2-CC6.1"]').click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(inspector).toBeVisible();
  const path = page.getByLabel("Current graph path");
  // Drill into a neighbour, then one step further from the new graph.
  const nodeIds = () =>
    page
      .locator(".react-flow__node")
      .evaluateAll((nodes) => nodes.map((node) => node.dataset.id ?? ""));
  const visited = new Set(["control:SOC2-CC6.1"]);
  let root = "control:SOC2-CC6.1";
  let previous = "";
  for (const level of [1, 2]) {
    // The explorer shows the previous graph until the drilled one arrives.
    await expect
      .poll(async () => {
        const ids = await nodeIds();
        return (
          ids.join() !== previous &&
          ids.includes(root) &&
          ids.some((id) => !visited.has(id))
        );
      })
      .toBe(true);
    previous = (await nodeIds()).join();
    const next = (await nodeIds()).find((id) => id && !visited.has(id)) ?? "";
    root = next;
    visited.add(next);
    const node = page.locator(`.react-flow__node[data-id="${next}"]`);
    await node.click();
    await expect(node).toHaveClass(/selected/);
    await inspector
      .getByRole("button", { name: "Focus this evidence path" })
      .click();
    await expect(path).toContainText(
      `${level} level${level === 1 ? "" : "s"} deeper`,
    );
    await page.waitForLoadState("networkidle");
    await expect(page.locator(".react-flow__node").nth(1)).toBeVisible();
    await expectHealthy(page);
  }
  expect(problems).toEqual([]);
});

test("graph depth, starting point and refresh replay the requested recorded graph", async ({
  page,
}) => {
  const problems = watch(page);
  await open(page, "/graph/");
  await page.evaluate(() => {
    const replay = window.fetch;
    window.fetch = async (...args) => {
      const response = await replay(...args);
      if (String(args[0]).includes("/graph/investigation?")) {
        document.documentElement.dataset.graphResponse = JSON.stringify({
          status: response.status,
          request: String(args[0]),
          ...(await response.clone().json()),
        });
      }
      return response;
    };
  });
  await page
    .getByText("Search and change starting point", { exact: true })
    .click();
  const rendered = () =>
    page
      .locator(".react-flow__node")
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("data-id")).sort(),
      );
  for (const depth of [1, 3, 2]) {
    await page
      .getByLabel("Graph depth", { exact: true })
      .selectOption(String(depth));
    await expect
      .poll(async () =>
        page.evaluate(() => {
          const response = JSON.parse(
            document.documentElement.dataset.graphResponse || "{}",
          );
          return response.status === 200
            ? response.data?.depth
            : response.status;
        }),
      )
      .toBe(depth);
    const expected = await page.evaluate(() =>
      JSON.parse(document.documentElement.dataset.graphResponse!)
        .data.nodes.map((node: { id: string }) => node.id)
        .sort(),
    );
    await expect.poll(rendered).toEqual(expected);
    await expectHealthy(page);
    if (depth === 1) {
      const neighbour = expected.find(
        (id: string) => id !== "control:SOC2-CC6.1",
      );
      await page.locator(`.react-flow__node[data-id="${neighbour}"]`).click();
      await page
        .getByRole("button", { name: "Focus this evidence path" })
        .click();
      await expect
        .poll(async () =>
          page.evaluate(
            () =>
              JSON.parse(document.documentElement.dataset.graphResponse || "{}")
                .data?.root,
          ),
        )
        .toBe(neighbour);
      await expectHealthy(page);
      await page.getByRole("button", { name: "Roll up", exact: true }).click();
      await expect(page.getByLabel("Graph depth", { exact: true })).toHaveValue(
        "1",
      );
      await expect.poll(rendered).toEqual(expected);
    }
  }
  // A different starting point pins the recorded generation; refresh removes it.
  const startingPoint = page.getByLabel("Graph starting point", {
    exact: true,
  });
  const next = await startingPoint
    .locator("option")
    .evaluateAll((options) =>
      options
        .map((option) => (option as HTMLOptionElement).value)
        .find((id) => id && id !== "control:SOC2-CC6.1"),
    );
  expect(next).toBeTruthy();
  await startingPoint.selectOption(next!);
  await expect
    .poll(async () =>
      page.evaluate(
        () =>
          JSON.parse(document.documentElement.dataset.graphResponse || "{}")
            .data?.root,
      ),
    )
    .toBe(next);
  await page.evaluate(
    () => delete document.documentElement.dataset.graphResponse,
  );
  await page
    .getByRole("button", { name: "Refresh evidence", exact: true })
    .click();
  await expect
    .poll(async () =>
      page.evaluate(() => {
        const response = JSON.parse(
          document.documentElement.dataset.graphResponse || "{}",
        );
        return response.status === 200 &&
          !new URL(response.request, location.origin).searchParams.has(
            "version",
          )
          ? response.data?.root
          : null;
      }),
    )
    .toBe(next);
  await expect(
    page.getByRole("region", { name: "Graph workspace", exact: true }),
  ).toHaveAttribute("aria-busy", "false");
  await expectHealthy(page);
  expect(problems).toEqual([]);
});

test("an unavailable graph resets its query to recorded defaults", async ({
  page,
}) => {
  await page.route("**/demo-api/manifest.json", async (route) => {
    const manifest = await (await route.fetch()).json();
    for (const key of Object.keys(manifest.entries)) {
      if (
        key.startsWith("/api/v1/graph/investigation?") &&
        new URL(key, "http://demo").searchParams.get("depth") === "3"
      )
        delete manifest.entries[key];
    }
    await route.fulfill({ json: manifest });
  });
  await open(page, "/graph/");
  await page
    .getByText("Search and change starting point", { exact: true })
    .click();
  await page.getByLabel("Graph depth", { exact: true }).selectOption("3");
  await expect(page.getByText(UNAVAILABLE)).toBeVisible();
  await page
    .getByLabel("Find a starting point", { exact: true })
    .fill("unrecorded search");
  await page.getByText("Visible relationship layers", { exact: true }).click();
  await page.getByRole("checkbox", { name: "source", exact: true }).uncheck();
  await page.getByRole("button", { name: "Reset to current evidence" }).click();
  await expect(page.getByLabel("Graph depth", { exact: true })).toHaveValue(
    "2",
  );
  await expect(
    page.getByLabel("Find a starting point", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByRole("checkbox", { name: "source", exact: true }),
  ).toBeChecked();
  await expect(page.locator(".react-flow__node").nth(1)).toBeVisible();
  await expectHealthy(page);
});

test("evidence table opens an evidence drawer with lineage", async ({
  page,
}) => {
  const problems = watch(page);
  await open(page, "/evidence/");
  const rows = page.locator("main table tbody tr");
  await expect(rows.nth(5)).toBeVisible();
  await rows.nth(4).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: "Trace frozen results" }).click();
  await expect(drawer.getByText(/Generation integrity/)).toBeVisible();
  await expect(drawer.getByText(/Lineage could not be verified/)).toHaveCount(
    0,
  );
  await expectHealthy(page);
  expect(problems).toEqual([]);
});

test("findings open a review drawer", async ({ page }) => {
  const problems = watch(page);
  await open(page, "/violations/");
  await page
    .getByRole("button", { name: /Review finding/ })
    .nth(3)
    .click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  for (const tab of await drawer.getByRole("tab").all()) {
    await tab.click();
    await expectHealthy(page);
  }
  expect(problems).toEqual([]);
});

test("AI governance renders models and agents", async ({ page }) => {
  const problems = watch(page);
  await open(page, "/ai-governance/");
  await expect(page.getByTestId("ai-governance-strip")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Models and agents" }),
  ).toBeVisible();
  await expectHealthy(page);
  expect(problems).toEqual([]);
});

test("every console route renders without a broken request", async ({
  page,
}) => {
  const problems = watch(page);
  for (const route of [
    "/insights/",
    "/connectors/",
    "/crosswalk/",
    "/mapping-review/",
    "/remediation/",
    "/risks/",
    "/access-reviews/",
    "/policies/",
    "/vendor-risk/",
    "/audit-room/",
    "/trust-center/",
    "/audit-log/",
    "/automation/",
    "/agents/",
    "/auth/",
    "/onboarding/",
  ]) {
    await open(page, route);
    await expect(page.getByText(API_DOWN), route).toHaveCount(0);
  }
  expect(problems).toEqual([]);
});

test("a write is blocked with one read-only notice and nothing changes", async ({
  page,
}) => {
  const problems = watch(page);
  await open(page, "/dashboard/");
  await page
    .getByRole("button", { name: /snapshot/i })
    .first()
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /snapshot/i })
    .last()
    .click();
  await expect(page.getByText(READ_ONLY)).toHaveCount(1);
  expect(problems).toEqual([]);
});

test("an unrecorded read says it is unavailable in the demo", async ({
  page,
}) => {
  await open(page, "/dashboard/");
  const result = await page.evaluate(async () => {
    const res = await fetch("/api/v1/not-recorded?x=1");
    return { status: res.status, body: await res.json() };
  });
  expect(result.status).toBe(501);
  expect(result.body.errors[0].detail).toMatch(UNAVAILABLE);
});

test("a view missing from the snapshot renders as unavailable, not as an outage", async ({
  page,
}) => {
  await page.route("**/demo-api/manifest.json", async (route) => {
    const manifest = await (await route.fetch()).json();
    for (const key of Object.keys(manifest.entries))
      if (key.startsWith("/api/v1/risks?")) delete manifest.entries[key];
    await route.fulfill({ json: manifest });
  });
  await open(page, "/risks/");
  await expect(
    page.getByRole("status").filter({ hasText: UNAVAILABLE }),
  ).toBeVisible();
  await expect(page.getByText(API_DOWN)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
});

test("the demo fits a phone without horizontal scrolling", async ({
  browser,
}) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const problems = watch(page);
  await open(page, "/dashboard/");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  expect(problems).toEqual([]);
  await page.close();
});

test("demo offers a guided first task and an authenticated real-evidence pilot", async ({
  page,
}) => {
  await open(page, "/graph/");
  const banner = page.getByTestId("demo-banner");
  await expect(
    banner.getByRole("link", { name: "Follow the sample tour" }),
  ).toHaveAttribute("href", /\/blob\/main\/docs\/TUTORIAL_5_MIN\.md$/);
  await expect(
    banner.getByRole("link", { name: "Evaluate your own evidence" }),
  ).toHaveAttribute("href", /\/blob\/main\/docs\/PILOT\.md$/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    banner.getByRole("link", { name: "Evaluate your own evidence" }),
  ).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 390);
});
