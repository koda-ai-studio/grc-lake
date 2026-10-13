import { expect, test } from "@playwright/test";

test("public repository onboarding explains scope and opens the exact graph root", async ({
  page,
}) => {
  let polls = 0;
  await page.route("**/api/v1/repositories/public-audit", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      repo: "https://github.com/acme/agent-api",
    });
    expect(route.request().headers()["prefer"]).toBe("respond-async");
    await route.fulfill({
      status: 202,
      json: { meta: { resource: "operations" }, data: { id: "public-job" } },
    });
  });
  await page.route("**/api/v1/operations/public-job", async (route) => {
    polls++;
    await route.fulfill({
      json: {
        data: {
          status: polls < 2 ? "running" : "succeeded",
          http_status: 201,
          response:
            polls < 2
              ? null
              : {
                  data: {
                    repo: "acme/agent-api",
                    provider: "github",
                    source_commit: "a".repeat(40),
                    source_ref: "main",
                    observation_id: "fixture-observation",
                    observed_at: "2026-10-13T12:00:00Z",
                    synthetic: true,
                    evidence_count: 9,
                    investigate_href: "/graph/?root=asset%3Afixture",
                  },
                },
        },
      },
    });
  });
  await page.goto("/console/onboarding/");
  await page.getByText("What this checks", { exact: true }).click();
  await expect(
    page.getByText(
      /Branch protection, private alerts and organization policies remain unknown/,
    ),
  ).toBeVisible();
  await page
    .getByLabel("Public GitHub repository URL", { exact: true })
    .fill("https://github.com/acme/agent-api");
  await page
    .getByRole("button", { name: "Investigate repository", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Collecting public evidence…" }),
  ).toBeDisabled();
  await expect(page.getByText("9 observations · acme/agent-api")).toBeVisible();
  await expect(page.getByText(/Commit a{40}/)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open evidence investigation" }),
  ).toHaveAttribute("href", "/console/graph/?root=asset%3Afixture");
  await page.getByRole("link", { name: "Open evidence investigation" }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("root"))
    .toBe("asset:fixture");
});

test("public rate limits stay actionable without a false success", async ({
  page,
}) => {
  await page.route("**/api/v1/repositories/public-audit", (route) =>
    route.fulfill({
      status: 429,
      json: {
        errors: [
          {
            detail:
              "GitHub public API rate limit reached; retry after the limit resets.",
          },
        ],
      },
    }),
  );
  await page.goto("/console/onboarding/");
  await page
    .getByLabel("Public GitHub repository URL", { exact: true })
    .fill("https://github.com/acme/agent-api");
  await page
    .getByRole("button", { name: "Investigate repository", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "rate limit reached" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open evidence investigation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Investigate repository", exact: true }),
  ).toBeEnabled();
});

test("repository investigations start readable and retain the complete neighborhood", async ({
  page,
}) => {
  const root = "asset:wide-repo";
  const nodes = [
    {
      id: root,
      kind: "repository",
      label: "acme/large-repo",
      provider: "github-public-repo",
    },
    {
      id: "gap",
      kind: "signal_gap",
      label: "Authenticated evidence unavailable",
    },
    ...Array.from({ length: 10 }, (_, i) => ({
      id: `evidence:${i}`,
      kind: "evidence_type",
      label: `repository.signal_${i}`,
      status: "observed",
    })),
    ...Array.from({ length: 80 }, (_, i) => ({
      id: `file:${i}`,
      kind: "file",
      label: `src/module-${i}.py`,
    })),
  ];
  const edges = nodes.slice(1).map((node, i) => ({
    id: `edge:${i}`,
    source: root,
    target: node.id,
    kind: "has_signal",
  }));
  await page.route("**/api/v1/graph/investigation?*", (route) =>
    route.fulfill({
      json: {
        data: {
          nodes,
          edges,
          root,
          roots: [nodes[0]],
          root_count: 1,
          root_offset: 0,
          next_root_offset: null,
          version: "test-version",
          matching_nodes: nodes.length,
          truncated: false,
          root_missing: false,
          boundary:
            "Recorded relationships; not network reachability or complete inventory",
        },
      },
    }),
  );
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto(`/console/graph/?root=${encodeURIComponent(root)}`);
  await expect(page.locator(".react-flow__node")).toHaveCount(12);
  await expect(
    page.getByText("12 of 92 loaded nodes", { exact: false }),
  ).toBeVisible();
  await expect(
    page
      .getByTestId("graph-node-label")
      .filter({ hasText: "Authenticated evidence unavailable" }),
  ).toBeVisible();
  await expect
    .poll(
      async () =>
        (await page.getByTestId("graph-node-icon").first().boundingBox())!
          .height,
    )
    .toBeGreaterThanOrEqual(48);
  await expect
    .poll(async () =>
      page.evaluate(() => {
        const labels = Array.from(
          document.querySelectorAll('[data-testid="graph-node-label"]'),
        ).map((el) => el.getBoundingClientRect());
        const nodes = Array.from(
          document.querySelectorAll<HTMLElement>(".react-flow__node"),
        );
        let collisions = 0;
        for (const edge of document.querySelectorAll<SVGPathElement>(
          ".react-flow__edge-path",
        )) {
          const length = edge.getTotalLength();
          const matrix = edge.getScreenCTM()!;
          for (let at = 6; at < length - 6; at += 4) {
            const point = edge.getPointAtLength(at).matrixTransform(matrix);
            if (
              labels.some(
                (box) =>
                  point.x > box.left &&
                  point.x < box.right &&
                  point.y > box.top &&
                  point.y < box.bottom,
              )
            ) {
              collisions++;
              break;
            }
          }
        }
        for (let i = 0; i < nodes.length; i++) {
          const a = nodes[i].getBoundingClientRect();
          for (const next of nodes.slice(i + 1)) {
            const b = next.getBoundingClientRect();
            if (
              a.left < b.right &&
              b.left < a.right &&
              a.top < b.bottom &&
              b.top < a.bottom
            )
              collisions++;
          }
        }
        return collisions;
      }),
    )
    .toBe(0);
  await page.getByRole("button", { name: "All relationships (92)" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(92);
  await expect(page.locator(".react-flow__edge-path")).toHaveCount(91);
  await page.getByRole("button", { name: "Evidence focus (12)" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(12);
  await expect(page.locator(".react-flow__edge-path")).toHaveCount(11);
});
