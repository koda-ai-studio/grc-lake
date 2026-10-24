import { defineConfig, devices } from "@playwright/test";

// Drives the assembled static live demo (npm run build:demo) the way GitHub
// Pages serves it: no API server, every request answered from the snapshot.
const port = Number(process.env.DEMO_SITE_PORT || 4173);
const sitePath = process.env.DEMO_SITE_PATH || "/grc-lake";

export default defineConfig({
  testDir: "./e2e-demo",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}${sitePath}/`,
    trace: "on-first-retry",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "node scripts/serve_demo_site.mjs",
    url: `http://127.0.0.1:${port}${sitePath}/console/dashboard/`,
    reuseExistingServer: !process.env.CI,
    env: { DEMO_SITE_PORT: String(port), DEMO_SITE_PATH: sitePath },
  },
  projects: [{ name: "chromium", use: { channel: undefined } }],
});
