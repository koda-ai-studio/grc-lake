import { expect, test, type Page } from "@playwright/test";

// Runs against the live API (tools/run_e2e_console.sh serves the golden
// fixture). Nothing here mocks the graph endpoint: layer visibility, focus and
// URL state are checked against the server's own bounded neighborhood.

type Node = {
  id: string;
  kind: string;
  label: string;
  source_account_id?: string;
};
type Edge = { source: string; target: string };
type Neighborhood = {
  root: string;
  nodes: Node[];
  edges: Edge[];
  root_count: number;
  truncated: boolean;
};

async function neighborhood(page: Page, root = "") {
  const params = new URLSearchParams({
    view: "controls",
    depth: "2",
    limit: "150",
  });
  if (root) params.set("root", root);
  const response = await page.request.get(
    `/api/v1/graph/investigation?${params}`,
  );
  expect(response.ok()).toBe(true);
  return (await response.json()).data as Neighborhood;
}

const shownIds = (page: Page) =>
  page
    .locator(".react-flow__node")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-id") ?? "").sort(),
    );

function totals(data: Neighborhood, hidden: Set<string>) {
  const shown = new Set(
    data.nodes.filter((n) => !hidden.has(n.kind)).map((n) => n.id),
  );
  const edges = data.edges.filter(
    (e) => shown.has(e.source) && shown.has(e.target),
  ).length;
  return { ids: [...shown].sort(), nodes: shown.size, edges };
}

function graphRequests(page: Page) {
  const seen: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/graph/investigation?"))
      seen.push(request.url());
  });
  return seen;
}

const param = (page: Page, name: string) =>
  new URL(page.url()).searchParams.get(name);

async function openLayers(page: Page) {
  const setup = page.getByText("Search and change starting point", {
    exact: true,
  });
  if (!(await page.getByLabel("Graph depth", { exact: true }).isVisible()))
    await setup.click();
  const layers = page.getByText("Visible relationship layers", {
    exact: true,
  });
  if (
    !(await page
      .getByRole("checkbox", { name: "source", exact: true })
      .isVisible())
  )
    await layers.click();
  return page.getByRole("checkbox", { name: "source", exact: true });
}

const status = (page: Page) =>
  page
    .getByRole("status")
    .filter({ hasText: "Recorded relationships; not network reachability" });

async function loaded(
  page: Page,
  data: Neighborhood,
  hidden = new Set<string>(),
) {
  await expect.poll(() => shownIds(page)).toEqual(totals(data, hidden).ids);
}

for (const width of [1440, 390])
  for (const theme of ["light", "dark"] as const) {
    test(`live layer filters keep the loaded neighborhood at ${width}px in ${theme}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(
        (mode) => localStorage.setItem("trustops:theme", JSON.stringify(mode)),
        theme,
      );
      const data = await neighborhood(page);
      expect(data.truncated).toBe(false);
      expect(data.nodes.some((n) => n.kind === "source")).toBe(true);
      await page.goto("/console/graph/");
      await loaded(page, data);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const requests = graphRequests(page);
      const source = await openLayers(page);

      await source.uncheck();
      const hidden = totals(data, new Set(["source"]));
      await expect.poll(() => shownIds(page)).toEqual(hidden.ids);
      await expect(status(page)).toContainText(
        `${hidden.nodes} of ${data.nodes.length} loaded nodes · ${hidden.edges} of ${data.edges.length} relationships`,
      );
      expect(param(page, "hide")).toBe("source");

      await source.check();
      await loaded(page, data);
      await expect(status(page)).toContainText(
        `${data.nodes.length} nodes · ${data.edges.length} relationships`,
      );
      expect(param(page, "hide")).toBeNull();
      // Visibility is a view of the bounded slice already loaded.
      expect(requests).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth - innerWidth,
        ),
      ).toBe(0);
    });
  }

test("live direct focus reveals a hidden relationship and survives reload and history", async ({
  page,
}) => {
  const data = await neighborhood(page);
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const produced = data.edges.find(
    (e) =>
      byId.get(e.source)?.kind === "source" &&
      byId.get(e.target)?.kind === "evidence_type",
  )!;
  const evidence = byId.get(produced.target)!;
  const producer = byId.get(produced.source)!;
  const direct = (hidden: Set<string>) => {
    const ids = new Set([evidence.id]);
    for (const e of data.edges) {
      if (e.source === evidence.id) ids.add(e.target);
      if (e.target === evidence.id) ids.add(e.source);
    }
    const shown = [...ids].filter((id) => !hidden.has(byId.get(id)!.kind));
    const edges = data.edges.filter(
      (e) =>
        (e.source === evidence.id || e.target === evidence.id) &&
        shown.includes(e.source) &&
        shown.includes(e.target),
    ).length;
    return `${shown.length} nodes · ${edges} relationships shown (${data.nodes.length} nodes · ${data.edges.length} relationships loaded)`;
  };

  await page.goto("/console/graph/");
  await loaded(page, data);
  await (await openLayers(page)).uncheck();
  await loaded(page, data, new Set(["source"]));
  await page.locator(`.react-flow__node[data-id="${evidence.id}"]`).click();
  await page
    .getByRole("button", { name: "Focus direct relationships", exact: true })
    .click();
  const counts = page.getByLabel("Direct relationship counts", {
    exact: true,
  });
  await expect(counts).toHaveText(direct(new Set(["source"])));
  expect(param(page, "direct")).toBe(evidence.id);

  await page
    .getByText("Selected relationships and mapping review state", {
      exact: true,
    })
    .click();
  await page
    .getByRole("button", {
      name: `Inspect ${producer.label} in ${producer.source_account_id}`,
      exact: true,
    })
    .click();
  const sourceLayer = page.getByRole("checkbox", {
    name: "source",
    exact: true,
  });
  await expect(sourceLayer).toBeChecked();
  const selected = page.locator(`.react-flow__node[data-id="${producer.id}"]`);
  await expect(selected).toBeVisible();
  await expect(selected).toHaveClass(/selected/);
  await expect(counts).toHaveText(direct(new Set()));
  expect(param(page, "hide")).toBeNull();
  expect(param(page, "node")).toBe(producer.id);
  expect(param(page, "direct")).toBe(evidence.id);

  await page.reload();
  await expect(counts).toHaveText(direct(new Set()));
  await expect(selected).toHaveClass(/selected/);
  await expect(
    page.getByRole("complementary", { name: "Selected graph node" }),
  ).toContainText(producer.label);

  // Back returns to the entry before direct focus: source hidden, evidence
  // selected, full loaded neighborhood in view.
  await page.goBack();
  await expect(counts).toHaveCount(0);
  await loaded(page, data, new Set(["source"]));
  expect(param(page, "direct")).toBeNull();
  expect(param(page, "hide")).toBe("source");
  await expect(
    page.locator(`.react-flow__node[data-id="${evidence.id}"]`),
  ).toHaveClass(/selected/);
  await page.goForward();
  await expect(counts).toHaveText(direct(new Set()));
});

test("live drill-down restores the prior neighborhood through roll up and history", async ({
  page,
}) => {
  const data = await neighborhood(page);
  const safeguard = data.nodes.find((n) => n.kind === "safeguard")!;
  const child = await neighborhood(page, safeguard.id);
  const sourceHidden = new Set(["source"]);

  // A shared link restores the hidden layer before anything is clicked.
  await page.goto("/console/graph/?hide=source");
  await loaded(page, data, sourceHidden);
  await expect(await openLayers(page)).not.toBeChecked();

  await page.locator(`.react-flow__node[data-id="${safeguard.id}"]`).dblclick();
  await loaded(page, child, sourceHidden);
  expect(param(page, "root")).toBe(safeguard.id);
  expect(new URL(page.url()).searchParams.getAll("trail")).toEqual([data.root]);
  const path = page.getByLabel("Current graph path", { exact: true });
  await expect(path).toContainText("1 level deeper");

  await (await openLayers(page)).check();
  await loaded(page, child);
  expect(param(page, "hide")).toBeNull();

  await page.getByRole("button", { name: "Roll up", exact: true }).click();
  await loaded(page, data, sourceHidden);
  expect(param(page, "root")).toBe(data.root);
  expect(param(page, "hide")).toBe("source");
  expect(param(page, "trail")).toBeNull();

  await page.goBack();
  await loaded(page, child);
  await expect(path).toContainText("1 level deeper");
  await page.goBack();
  await loaded(page, data, sourceHidden);
  expect(param(page, "root")).toBeNull();
  await page.goForward();
  await loaded(page, child);

  await page.reload();
  await loaded(page, child);
  await expect(path).toContainText("1 level deeper");
  await page.getByRole("button", { name: "Roll up", exact: true }).click();
  await loaded(page, data);
  expect(param(page, "root")).toBe(data.root);
});

test("live starting-point pages keep the neighborhood and history restores a chosen root", async ({
  page,
}) => {
  const data = await neighborhood(page);
  expect(data.root_count).toBeGreaterThan(50);
  await page.goto("/console/graph/");
  await loaded(page, data);
  await openLayers(page);
  await page
    .getByRole("button", { name: "Next starting points", exact: true })
    .click();
  await expect(status(page)).toContainText(
    `Starting points 51–100 of ${data.root_count}`,
  );
  await loaded(page, data);
  const select = page.getByLabel("Graph starting point", { exact: true });
  const choice = await select
    .locator("option")
    .evaluateAll(
      (options, current) =>
        options
          .map((option) => (option as HTMLOptionElement).value)
          .find((value) => value && value !== current) ?? "",
      data.root,
    );
  expect(choice).not.toBe("");
  await select.selectOption(choice);
  const chosen = await neighborhood(page, choice);
  await loaded(page, chosen);
  expect(param(page, "root")).toBe(choice);

  await page.goBack();
  await loaded(page, data);
  expect(param(page, "root")).toBeNull();
  await page.goForward();
  await loaded(page, chosen);
});

test("switching from a maps link to the investigation keeps it on reload", async ({
  page,
}) => {
  const data = await neighborhood(page);
  await page.goto("/console/graph/?focus=control%3ASOC2-CC6.1");
  await page
    .getByRole("button", { name: "Evidence investigation", exact: true })
    .click();
  await loaded(page, data);
  await (await openLayers(page)).uncheck();
  expect(param(page, "focus")).toBeNull();
  expect(param(page, "hide")).toBe("source");
  await page.reload();
  await loaded(page, data, new Set(["source"]));
});
