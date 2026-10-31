import { expect, test, type Page } from "@playwright/test";

const methods = {
  require_auth: true,
  methods: [
    {
      id: "api_key",
      label: "API key",
      configured: true,
      login_url: "/api/v1/auth/session-from-key",
      setup_hint: "Use a key issued by your workspace administrator.",
    },
  ],
};

async function identity(page: Page) {
  await page.route("**/api/v1/stream", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: "",
    }),
  );
  await page.route("**/api/v1/auth/whoami", (route) =>
    route.fulfill({
      json: {
        data: {
          user_id: "synthetic-user",
          tenant_id: "synthetic-workspace",
          email: "reviewer@example.test",
          role: "reader",
          scopes: ["read"],
          auth_method: "session:oidc",
        },
      },
    }),
  );
  await page.route("**/api/v1/auth/methods", (route) =>
    route.fulfill({ json: { data: methods } }),
  );
}

for (const [status, message] of [
  [
    401,
    "This API key was not accepted. It may be invalid, expired, or revoked.",
  ],
  [
    403,
    "This sign-in is not allowed. Ask your administrator to check your access.",
  ],
  [429, "Too many sign-in attempts. Wait and try again."],
  [503, "Sign-in is temporarily unavailable. Try again."],
] as const) {
  test(`API-key sign-in explains ${status} without exposing diagnostics`, async ({
    page,
  }) => {
    await identity(page);
    await page.route("**/api/v1/auth/session-from-key", (route) =>
      route.fulfill({
        status,
        json: { detail: "synthetic-provider-diagnostic" },
      }),
    );
    await page.goto(
      "/console/login/?return_to=%2Fconsole%2Fgraph%2F%3Froot%3Dcontrol%253ASOC2-CC6.1",
    );
    await page.getByLabel("Bearer token").fill("synthetic-rejected-key");
    await page.getByRole("button", { name: "Open console session" }).click();
    await expect(page.getByText(message, { exact: true })).toBeVisible();
    await expect(
      page.getByText("synthetic-provider-diagnostic", { exact: true }),
    ).toHaveCount(0);
    await expect(page).toHaveURL(/\/console\/login\//);
    await expect(
      page.getByRole("button", { name: "Open console session" }),
    ).toBeEnabled();
    expect(
      await page.evaluate(() =>
        JSON.stringify({ ...localStorage, ...sessionStorage }),
      ),
    ).not.toContain("synthetic-rejected-key");
  });
}

test("failed sign-in discovery is recoverable and does not claim SSO is unconfigured", async ({
  page,
}) => {
  await identity(page);
  let attempts = 0;
  await page.route("**/api/v1/auth/methods", (route) =>
    ++attempts === 1
      ? route.fulfill({ status: 503, json: { detail: "unavailable" } })
      : route.fulfill({ json: { data: methods } }),
  );
  await page.goto("/console/login/");
  const discoveryError = page
    .getByRole("alert")
    .filter({ hasText: "Couldn't load sign-in options." });
  await expect(discoveryError).toBeVisible();
  await expect(
    page.getByText("No browser SSO provider is configured.", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Retry sign-in options" }).click();
  await expect(page.getByLabel("Bearer token")).toBeVisible();
  await expect(discoveryError).toHaveCount(0);
});

for (const failure of ["server", "network"] as const) {
  test(`logout ${failure} failure keeps the current page and allows retry`, async ({
    page,
  }) => {
    await identity(page);
    await page.setViewportSize({ width: 390, height: 844 });
    let attempts = 0;
    await page.route("**/api/v1/auth/logout", (route) => {
      if (++attempts > 1)
        return route.fulfill({ json: { data: { ok: true } } });
      return failure === "network"
        ? route.abort("failed")
        : route.fulfill({ status: 503, json: { detail: "unavailable" } });
    });
    await page.goto("/console/dashboard/");
    await page
      .getByRole("button", { name: /reviewer@example.test.*account menu/ })
      .click();
    await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
    await expect(
      page.getByText(
        "Couldn't sign out. Your session may still be active. Try again.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/console\/dashboard\//);
    await page
      .getByRole("button", { name: /reviewer@example.test.*account menu/ })
      .click();
    await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
    await expect(page).toHaveURL(/\/console\/login\/?$/);
    expect(attempts).toBe(2);
  });
}

test("successful logout replaces the document at the session boundary", async ({
  page,
}) => {
  await identity(page);
  await page.route("**/api/v1/auth/logout", (route) =>
    route.fulfill({ json: { data: { ok: true } } }),
  );
  await page.goto("/console/dashboard/");
  await page.evaluate(() => {
    document.documentElement.dataset.previousSession = "loaded";
  });
  await page
    .getByRole("button", { name: /reviewer@example.test.*account menu/ })
    .click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/console\/login\/?$/);
  await expect(page.locator("html")).not.toHaveAttribute(
    "data-previous-session",
    "loaded",
  );
});

test("authentication loss restores the exact investigation after signing in", async ({
  page,
}) => {
  await identity(page);
  let accepted = false;
  await page.route("**/api/v1/graph/investigation**", (route) =>
    accepted
      ? route.continue()
      : route.fulfill({
          status: 401,
          json: { detail: "invalid or expired session" },
        }),
  );
  await page.route("**/api/v1/auth/session-from-key", (route) => {
    accepted = true;
    return route.fulfill({ json: { data: { user_id: "synthetic-user" } } });
  });
  const target = "/console/graph/?root=control%3ASOC2-CC6.1#details";
  await page.goto(target);
  await expect(page).toHaveURL(/\/console\/login\/?\?return_to=/);
  expect(new URL(page.url()).searchParams.get("return_to")).toBe(target);
  await page.getByLabel("Bearer token").fill("synthetic-accepted-key");
  await page.getByLabel("Bearer token").press("Enter");
  await expect(page).toHaveURL(
    new RegExp("/console/graph/\\?root=control%3ASOC2-CC6.1#details$"),
  );
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  expect(page.url()).not.toContain("synthetic-accepted-key");
});

test("a forbidden resource does not turn into a sign-in loop", async ({
  page,
}) => {
  await identity(page);
  await page.route("**/api/v1/graph/investigation**", (route) =>
    route.fulfill({
      status: 403,
      json: { detail: "requires scope: read" },
    }),
  );
  await page.goto("/console/graph/");
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Some data requires additional permission." }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/console\/graph\//);
});
