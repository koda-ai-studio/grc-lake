import { expect, test } from "@playwright/test";

test("bounded investigation expands exact relationships with visible icons", async ({
  page,
}) => {
  const initialResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/graph/investigation") && response.ok(),
  );
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  const initial = (await (await initialResponse).json()).data;
  expect(initial.nodes.length).toBeGreaterThan(0);
  expect(initial.nodes.length).toBeLessThanOrEqual(150);
  await expect(page.getByTestId("graph-node-icon").first()).toBeVisible();
  await page
    .getByText("Search and change starting point", { exact: true })
    .click();
  const shallowResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/graph/investigation") &&
      new URL(response.url()).searchParams.get("depth") === "1" &&
      response.ok(),
  );
  await page.getByLabel("Graph depth").selectOption("1");
  const shallow = (await (await shallowResponse).json()).data;
  const evidence = shallow.nodes.find(
    (node: { label: string }) =>
      node.label === "repository.governance.branch_protection",
  );
  expect(evidence).toBeDefined();
  await page.locator(`.react-flow__node[data-id="${evidence.id}"]`).click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(inspector).toBeVisible();
  const focusedResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/graph/investigation") &&
      new URL(response.url()).searchParams.get("root") === evidence.id &&
      response.ok(),
  );
  await inspector
    .getByRole("button", { name: "Focus this evidence path" })
    .click();
  const focused = (await (await focusedResponse).json()).data;
  expect(focused.root).toBe(evidence.id);
  expect(focused.edges.length).toBeGreaterThan(0);
  await expect(
    page.getByText(/Recorded relationships; not network reachability/),
  ).toBeVisible();
  await expect
    .poll(() => page.locator(".react-flow__edge-path").count())
    .toBeGreaterThan(0);
});

test("every catalog provider opens the shared setup or cloud preparation", async ({
  page,
  request,
}) => {
  const response = await request.get("/api/v1/connectors?limit=100");
  expect(response.ok()).toBeTruthy();
  const rows = (await response.json()).data;
  for (const row of rows) {
    await page.goto(
      `/console/connectors/?connect=${encodeURIComponent(row.connector_id)}`,
    );
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: row.name, exact: true }),
    ).toBeVisible();
    if (
      !["aws-posture", "azure-posture", "gcp-posture"].includes(
        row.connector_id,
      )
    ) {
      await expect(
        dialog.getByRole("navigation", { name: "Connection setup steps" }),
      ).toBeVisible();
      if (row.state !== "enabled") {
        await expect(
          dialog.getByRole("heading", { name: "Configure read-only access" }),
        ).toBeVisible();
        await expect(
          dialog.getByText("Optional sync schedule", { exact: true }),
        ).toHaveCount(0);
      }
    }
  }
});

for (const id of ["kubernetes-cluster", "intune-devices"]) {
  test(`${id} setup fits a mobile viewport`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/console/connectors/?connect=${id}`);
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: "Configure read-only access" }),
    ).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box!.width).toBeLessThanOrEqual(391);
    expect(
      await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    ).toBeTruthy();
    await expect(
      dialog.getByRole("button", { name: "Next: test access" }),
    ).toBeDisabled();
  });
}

test("failed access test keeps configuration recoverable", async ({ page }) => {
  await page.route("**/api/v1/connectors/kubernetes-cluster/probe", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Provider is temporarily unavailable" }),
    }),
  );
  await page.goto("/console/connectors/?connect=kubernetes-cluster");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/Cluster name/).fill("synthetic-cluster");
  await dialog.getByRole("button", { name: "Next: test access" }).click();
  await dialog.getByRole("button", { name: "Test connection" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Enable connector" }),
  ).toHaveCount(0);
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await expect(dialog.getByLabel(/Cluster name/)).toHaveValue(
    "synthetic-cluster",
  );
});

test("selected investigation highlights direct relationships and clears selection", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  const control = page.locator(
    '.react-flow__node[data-id="control:SOC2-CC6.1"]',
  );
  await control.click();
  const inspector = page.getByRole("complementary", {
    name: "Selected graph node",
  });
  await expect(
    inspector.getByRole("heading", { name: "SOC2-CC6.1", exact: true }),
  ).toBeVisible();
  // Move away from the canvas so this asserts selection, independently of hover.
  await page
    .getByRole("heading", { name: "Evidence investigation", exact: true })
    .hover();
  const relationships = page.getByText(
    "Selected relationships and mapping review state",
    { exact: true },
  );
  const canvas = await page.locator(".react-flow").boundingBox();
  const panel = await relationships.boundingBox();
  expect(panel!.y).toBeGreaterThanOrEqual(canvas!.y + canvas!.height);
  await expect(
    page
      .getByTestId("graph-node-label")
      .filter({ hasText: "Branch protection" }),
  ).toBeVisible();
  await expect(control.locator(".opacity-50")).toHaveCount(0);
  const branchEvidence = page.locator(".react-flow__node").filter({
    has: page
      .getByTestId("graph-node-label")
      .filter({ hasText: "Branch protection" }),
  });
  await expect(branchEvidence.locator(".opacity-50")).toHaveCount(0);
  // Keep downstream context readable; selection emphasizes links and the root card.
  await expect(
    page.locator('.react-flow__node[data-id^="asset:"]').first(),
  ).toBeVisible();
  await expect(
    page.locator('.react-flow__node[data-id^="asset:"] .opacity-50'),
  ).toHaveCount(0);
  await expect(page.locator(".react-flow__edge-text")).toHaveCount(0);
  await expect(page.getByLabel("Mapping review states")).toContainText(
    "proposed",
  );
  await inspector.getByRole("button", { name: "Close node details" }).click();
  await expect(inspector).toHaveCount(0);
  await expect(page.locator(".react-flow__node .opacity-50")).toHaveCount(0);
});

test("graph expands, drills into a record and rolls back to its parent", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/console/graph/");
  const canvas = page.locator(".react-flow");
  await expect(canvas).toBeVisible();
  const initialWidth = (await canvas.boundingBox())!.width;
  await page.getByRole("button", { name: "Expand graph workspace" }).click();
  await expect(
    page.getByRole("button", { name: "Exit expanded workspace" }),
  ).toBeVisible();
  expect((await canvas.boundingBox())!.width).toBeGreaterThan(initialWidth);
  await page.getByLabel("Workspace graph depth").selectOption("1");
  await page.locator('.react-flow__node[data-id^="evidence:"]').first().click();
  await page.getByRole("button", { name: "Focus this evidence path" }).click();
  await expect(page.getByLabel("Current graph path")).toContainText(
    "1 level deeper",
  );
  await page.getByRole("button", { name: "Roll up", exact: true }).click();
  await expect(page.getByLabel("Current graph path")).toContainText(
    "SOC2-CC6.1",
  );
  await expect(
    page.getByRole("button", { name: "Roll up", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Roll up", exact: true }).click();
  await expect(page.getByLabel("Current graph path")).toContainText(
    "SOC 2 Trust Services Criteria",
  );
  await page.getByRole("button", { name: "Exit expanded workspace" }).click();
  await expect(
    page.getByRole("button", { name: "Expand graph workspace" }),
  ).toBeVisible();
});

test("recorded graph edges reach card boundaries without broken segments", async ({
  page,
  request,
}) => {
  const graph = (
    await (await request.get("/api/v1/graph/investigation")).json()
  ).data;
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/console/graph/");
  await expect(page.locator(".react-flow__edge-path")).toHaveCount(
    graph.edges.length,
  );
  await expect
    .poll(async () =>
      page.evaluate(
        (edges: { id: string; source: string; target: string }[]) => {
          let worstGap = 0;
          for (const edge of edges) {
            const path = document.querySelector<SVGPathElement>(
              `.react-flow__edge[data-id="${edge.id}"] .react-flow__edge-path`,
            )!;
            const source = document
              .querySelector(`.react-flow__node[data-id="${edge.source}"]`)!
              .getBoundingClientRect();
            const target = document
              .querySelector(`.react-flow__node[data-id="${edge.target}"]`)!
              .getBoundingClientRect();
            const start = path
              .getPointAtLength(0)
              .matrixTransform(path.getScreenCTM()!);
            const end = path
              .getPointAtLength(path.getTotalLength())
              .matrixTransform(path.getScreenCTM()!);
            worstGap = Math.max(
              worstGap,
              Math.hypot(
                start.x - source.right,
                start.y - (source.top + source.height / 2),
              ),
              Math.hypot(
                end.x - target.left,
                end.y - (target.top + target.height / 2),
              ),
            );
          }
          return worstGap;
        },
        graph.edges,
      ),
    )
    .toBeLessThan(5);
  await expect(page.locator(".react-flow__edge.animated")).toHaveCount(0);
  const markers = await page
    .locator(".react-flow__edge-path")
    .evaluateAll((paths) => paths.every((p) => p.hasAttribute("marker-end")));
  expect(markers).toBe(true);
});

test("graph expands within the page when browser fullscreen is unavailable", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Element.prototype.requestFullscreen = async () => {
      throw new Error("Fullscreen unavailable");
    };
  });
  await page.goto("/console/graph/");
  await expect(page.locator(".react-flow")).toBeVisible();
  await page.getByRole("button", { name: "Expand graph workspace" }).click();
  await expect(
    page.getByRole("button", { name: "Exit expanded workspace" }),
  ).toBeVisible();
  const workspace = page.locator('section[aria-label="Graph workspace"]');
  expect((await workspace.boundingBox())!.x).toBe(0);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Expand graph workspace" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Expand graph workspace" }),
  ).toBeFocused();
});

for (const [provider, vendor] of [
  ["github-public-repo", "GitHub"],
  ["gitlab-repo-governance", "GitLab"],
  ["unknown", ""],
]) {
  test(`repository graph uses the observed ${provider} identity`, async ({
    page,
  }) => {
    await page.route("**/api/v1/graph/investigation?*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      for (const node of body.data.nodes) {
        if (node.kind === "repository") node.provider = provider;
      }
      await route.fulfill({ json: body });
    });
    await page.goto("/console/graph/");
    const repo = page
      .locator(".react-flow__node")
      .filter({ hasText: "acme/model-service" });
    await expect(repo).toBeVisible();
    if (vendor)
      await expect(
        repo.getByRole("img", { name: `${vendor} connector` }),
      ).toBeVisible();
    else
      await expect(repo.getByRole("img", { name: /connector/ })).toHaveCount(0);
    await expect(repo.locator("svg.lucide-git-branch")).toBeVisible();
    await repo.click();
    const inspector = page.getByRole("complementary", {
      name: "Selected graph node",
    });
    const action = inspector.getByRole("link", {
      name: "Review repository source",
    });
    if (vendor) {
      await expect(
        inspector.getByRole("img", { name: `${vendor} connector` }),
      ).toBeVisible();
      await expect(action).toHaveAttribute(
        "href",
        new RegExp(`connect=${vendor.toLowerCase()}-security`),
      );
    } else await expect(action).not.toHaveAttribute("href", /github-security/);
  });
}

test("double-clicking a repository drills into its recorded relationships", async ({
  page,
}) => {
  await page.goto("/console/graph/");
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "acme/model-service" })
    .dblclick();
  await expect(page.getByLabel("Current graph path")).toContainText(
    "1 level deeper",
  );
  await expect(page.getByLabel("Current graph path")).toContainText(
    "acme/model-service",
  );
});

for (const [status, label] of [
  ["passed", "Passing evidence"],
  ["failed", "Failing evidence"],
  ["observed", "Observed · not evaluated"],
  ["requires_authenticated_connector", "Not observable"],
]) {
  test(`repository evidence keeps ${status} distinct and shows its control impact`, async ({
    page,
  }) => {
    await page.route("**/api/v1/graph/investigation?*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      for (const node of body.data.nodes) {
        if (node.kind === "evidence_type") {
          node.status = status;
          // Expired passing evidence reads as stale; keep this case current.
          node.freshness_status = "fresh";
          node.control_ids = ["SOC2-CC6.1"];
        }
      }
      await route.fulfill({ json: body });
    });
    await page.goto("/console/graph/");
    await page
      .locator(".react-flow__node")
      .filter({ hasText: "acme/model-service" })
      .click();
    const records = page.getByLabel("Visible repository evidence");
    await expect(records.getByText(label).first()).toBeVisible();
    await records.getByRole("button", { name: /Branch protection/ }).click();
    const inspector = page.getByRole("complementary", {
      name: "Selected graph node",
    });
    await expect(inspector.getByText(label, { exact: true })).toBeVisible();
    await expect(
      inspector.getByRole("link", { name: "SOC2-CC6.1", exact: true }),
    ).toBeVisible();
    await expect(
      inspector.getByText(/required reviews, status checks/),
    ).toBeVisible();
  });
}

test("mobile graph keeps the complete current path visible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/console/graph/?root=control%3ASOC2-CC6.1");
  const path = page.getByLabel("Current graph path", { exact: true });
  await expect(path).toContainText("CC6.1");
  expect((await path.boundingBox())?.width).toBeGreaterThan(300);
  const dimensions = await path.evaluate((element) => ({
    clipped: element.scrollWidth > element.clientWidth,
    ellipsis: getComputedStyle(element).textOverflow === "ellipsis",
  }));
  expect(dimensions).toEqual({ clipped: false, ellipsis: false });
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
});
