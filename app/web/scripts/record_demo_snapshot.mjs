#!/usr/bin/env node
/**
 * Record the API responses the console makes against a golden-fixture server
 * into a static snapshot for the read-only live demo (`npm run build:demo`).
 *
 * Requires: a server at GRC_LAKE_DEMO_SOURCE_URL (default
 * http://127.0.0.1:8787) started with rate limiting off, and Playwright
 * Chromium. tools/record_demo_snapshot.sh does both.
 *
 * 1. Visit every console route (scripts/demo_routes.mjs) and open the main
 *    drawers and tabs, recording each GET /api/* response the page makes.
 * 2. Replay recorded detail URLs for every other record of the same kind
 *    (each control, finding, evidence record, framework...), so any drawer
 *    a visitor opens has its data, not just the one the crawl clicked.
 * 3. Record graph drill-downs: every node of each investigation view, and
 *    one level further, as the explorer requests them.
 *
 * Output: <out>/manifest.json (key -> status + file) and <out>/r/<sha>.json.
 */
import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { DEMO_ROUTES } from "./demo_routes.mjs";
import { loadTsModule } from "./load_ts_module.mjs";

const { snapshotKey } = await loadTsModule(
  new URL("../src/lib/demo/snapshot.ts", import.meta.url),
);

const base = (
  process.env.GRC_LAKE_DEMO_SOURCE_URL || "http://127.0.0.1:8787"
).replace(/\/$/, "");
const origin = new URL(base).origin;
const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.resolve(
  process.env.GRC_LAKE_DEMO_SNAPSHOT_DIR || path.join(webRoot, "demo-snapshot"),
);
const maxDrills = Number(process.env.GRC_LAKE_DEMO_MAX_GRAPH_DRILLS || 1500);
// Absolute paths that leak the recording host into responses (lake location,
// checkout, home directory) are rewritten before anything is published.
const scrub = [
  [process.env.GRC_LAKE_DEMO_LAKE, "./lake"],
  [path.resolve(webRoot, "..", ".."), "."],
  [homedir(), "~"],
]
  .filter(([from]) => from && from.length > 1)
  .map(([from, to]) => [path.resolve(from), to]);

/** key -> { status, body } */
const recorded = new Map();
const warnings = [];

function isApi(url) {
  const parsed = new URL(url, origin);
  return (
    parsed.origin === origin &&
    parsed.pathname.startsWith("/api/") &&
    parsed.pathname !== "/api/v1/stream"
  );
}

function store(url, status, body) {
  if (status === 429 || status >= 500 && status !== 501)
    throw new Error(`${url} -> ${status}; the snapshot would replay an outage`);
  recorded.set(snapshotKey(url, origin), { status, body });
}

async function get(url) {
  for (let attempt = 0; ; attempt += 1) {
    const res = await fetch(new URL(url, origin), {
      headers: { accept: "application/json" },
    });
    const body = await res.text();
    // Graph reads have a per-tenant concurrency cap; wait for a slot.
    if (res.status === 503 && body.includes("graph_tenant_capacity") && attempt < 20) {
      await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
      continue;
    }
    store(url, res.status, body);
    return { status: res.status, body };
  }
}

async function pool(items, size, task) {
  const queue = [...items];
  await Promise.all(
    Array.from({ length: size }, async () => {
      while (queue.length) await task(queue.shift());
    }),
  );
}

function json(key) {
  const entry = recorded.get(key);
  if (!entry || entry.status !== 200) return null;
  try {
    return JSON.parse(entry.body);
  } catch {
    return null;
  }
}

async function list(apiPath) {
  const { body } = await get(`/api${apiPath}`);
  return JSON.parse(body).data ?? [];
}

// ---- 1. browser crawl -------------------------------------------------------

const controls = await list("/v1/controls?limit=500&offset=0");
const evidence = await list("/v1/evidence?limit=500&offset=0");
const frameworks = await list("/v1/frameworks?limit=500&offset=0");
if (!controls.length || !evidence.length || !frameworks.length)
  throw new Error(
    "Empty lake: load it with `grc-lake fixtures load --company golden --rebase-times`.",
  );
const sample = {
  control:
    controls.find((c) => c.control_id === "SOC2-CC6.1")?.control_id ??
    controls[0].control_id,
  evidence: evidence[0].event_id,
  framework:
    frameworks.find((f) => f.framework_id === "soc2")?.framework_id ??
    frameworks[0].framework_id,
};

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
const pending = new Set();
page.on("request", (request) => {
  if (isApi(request.url()) && !["GET", "HEAD"].includes(request.method()))
    warnings.push(
      `${request.method()} ${new URL(request.url()).pathname} fired on ${page.url()}; the demo blocks it with a read-only notice`,
    );
});
page.on("response", (response) => {
  const request = response.request();
  if (request.method() !== "GET" || !isApi(response.url())) return;
  const task = response
    .text()
    .then((body) => store(response.url(), response.status(), body))
    .catch((error) => warnings.push(`${response.url()}: ${error.message}`))
    .finally(() => pending.delete(task));
  pending.add(task);
});

async function settle() {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(500);
  await Promise.all(pending);
}

// Buttons that only reveal recorded data. Never add one that writes.
const READ_ONLY_REVEALS = [/^Trace frozen results$/];

async function revealReads(scope) {
  for (const name of READ_ONLY_REVEALS) {
    for (const button of await scope.getByRole("button", { name }).all()) {
      if (!(await button.isVisible().catch(() => false))) continue;
      await button.click({ timeout: 5_000 }).catch(() => {});
      await settle();
    }
  }
}

async function clickTabs(scope) {
  await revealReads(scope);
  const tabs = await scope.getByRole("tab").all();
  for (const tab of tabs) {
    if (!(await tab.isVisible().catch(() => false))) continue;
    await tab.click({ timeout: 5_000 }).catch(() => {});
    await settle();
    await revealReads(scope);
  }
}

const interactions = {
  tabs: () => clickTabs(page.locator("main")),
  "dialog-tabs": async () => {
    await page.getByRole("dialog").first().waitFor({ timeout: 15_000 });
    await settle();
    await clickTabs(page.getByRole("dialog").first());
  },
  "finding-drawer": async () => {
    await page.getByRole("button", { name: /Review finding/ }).first().click();
    await interactions["dialog-tabs"]();
  },
  graph: async () => {
    await page.keyboard.press("Escape");
    const node = page.locator(
      `.react-flow__node[data-id="control:${sample.control}"]`,
    );
    await node.click({ timeout: 15_000 });
    await page
      .getByRole("complementary", { name: "Selected graph node" })
      .waitFor({ timeout: 15_000 });
    await settle();
  },
};

for (const { route, interact } of DEMO_ROUTES) {
  const target = route.replace(/\{(\w+)\}/g, (_, name) =>
    encodeURIComponent(sample[name]),
  );
  await page.goto(`${base}/console${target}`, { waitUntil: "domcontentloaded" });
  await settle();
  if (interact) {
    try {
      await interactions[interact]();
    } catch (error) {
      throw new Error(`${target}: "${interact}" failed: ${error.message}`);
    }
  }
  console.log(`crawled ${target}`);
}
await browser.close();

// ---- 2. replay detail URLs for every record of the same kind --------------

const ID_SOURCES = {
  "/api/v1/controls": "control_id",
  "/api/v1/frameworks": "framework_id",
  "/api/v1/violations": "violation_id",
  "/api/v1/evidence": "event_id",
  "/api/v1/connectors": "connector_id",
  "/api/v1/policies": "id",
  "/api/v1/risks": "id",
  "/api/v1/remediation/tasks": "id",
  "/api/v1/vendor-assessments": "id",
  "/api/v1/access-reviews": "id",
  "/api/v1/workflows": "id",
};
const idSets = [];
for (const [key] of recorded) {
  const url = new URL(key, origin);
  const field = ID_SOURCES[url.pathname];
  const rows = field ? json(key)?.data : null;
  if (!Array.isArray(rows)) continue;
  const ids = new Set(rows.map((row) => row?.[field]).filter(Boolean));
  if (ids.size) idSets.push(ids);
}

const variants = new Set();
for (const [key] of [...recorded]) {
  const url = new URL(key, origin);
  if (ID_SOURCES[url.pathname]) continue;
  const segments = url.pathname.split("/").map(decodeURIComponent);
  segments.forEach((segment, index) => {
    for (const ids of idSets) {
      if (!ids.has(segment)) continue;
      for (const id of ids) {
        const next = [...segments];
        next[index] = id;
        variants.add(
          `${next.map((part) => encodeURIComponent(part)).join("/")}${url.search}`,
        );
      }
    }
  });
  for (const [name, value] of url.searchParams) {
    for (const ids of idSets) {
      if (!ids.has(value)) continue;
      for (const id of ids) {
        const next = new URL(url);
        next.searchParams.set(name, id);
        variants.add(`${next.pathname}${next.search}`);
      }
    }
  }
}
const detailUrls = [...variants].filter(
  (url) => !recorded.has(snapshotKey(url, origin)),
);
await pool(detailUrls, 8, get);
console.log(`recorded ${detailUrls.length} detail variants`);

// ---- 3. graph drill-downs ---------------------------------------------------

const graphKey = [...recorded.keys()].find((key) =>
  key.startsWith("/api/v1/graph/investigation?"),
);
if (!graphKey) throw new Error("The graph page made no investigation request");
const template = new URL(graphKey, origin);
const ROOT_VIEW = /^(control|safeguard|framework|category|family):/;
const drilled = new Set();

function graphUrl(params) {
  return `${template.pathname}?${params}`;
}

async function graph(params) {
  const url = graphUrl(params);
  const key = snapshotKey(url, origin);
  const { status, body } = recorded.has(key)
    ? recorded.get(key)
    : await get(url);
  if (status !== 200) return null;
  return JSON.parse(body).data;
}

let level = [];
for (const view of ["controls", "environment", "investigation"]) {
  const params = new URLSearchParams(template.search);
  params.set("view", view);
  params.delete("root");
  params.delete("version");
  const data = await graph(params);
  if (!data) continue;
  // Focusing the current root keeps the query and only pins the version.
  if (data.version) {
    const pinned = new URLSearchParams(params);
    pinned.set("version", data.version);
    await graph(pinned);
  }
  for (const node of [...data.nodes, ...(data.roots ?? [])]) {
    level.push({ view, id: node.id, version: data.version ?? "" });
    // `/graph/?root=<id>` from another page: view follows the root's kind.
    const linked = new URLSearchParams(template.search);
    linked.set("view", ROOT_VIEW.test(node.id) ? "controls" : "investigation");
    linked.delete("framework");
    linked.delete("control_offset");
    linked.set("root", node.id);
    await graph(linked);
  }
}
for (let depth = 0; depth < 2 && level.length; depth += 1) {
  const next = [];
  const batch = level.filter(({ view, id }) => {
    const seen = drilled.has(`${view} ${id}`);
    drilled.add(`${view} ${id}`);
    return !seen && drilled.size <= maxDrills;
  });
  await pool(batch, 2, async ({ view, id, version }) => {
    // exploreNode(): keep the view, set the root, pin the graph version.
    const params = new URLSearchParams(template.search);
    params.set("view", view);
    params.delete("framework");
    params.delete("control_offset");
    params.set("root", id);
    if (version) params.set("version", version);
    const data = await graph(params);
    if (depth === 0 && data)
      for (const node of data.nodes)
        next.push({ view, id: node.id, version: data.version ?? version });
  });
  level = next;
}
if (drilled.size > maxDrills)
  warnings.push(`graph drill-downs capped at ${maxDrills}`);
console.log(`recorded ${drilled.size} graph drill-downs`);

// Depth and refresh change the query without changing the selected root. Record
// each supported hop count from the API, both pinned and current; never project
// a shallower graph from an already bounded response.
const graphQueries = [...recorded.keys()].filter((key) =>
  key.startsWith(`${template.pathname}?`),
);
await pool(graphQueries, 2, async (key) => {
  const params = new URL(key, origin).searchParams;
  const version = json(key)?.data?.version;
  for (const depth of [1, 2, 3]) {
    params.set("depth", String(depth));
    params.delete("version");
    await graph(params);
    if (version) {
      params.set("version", version);
      await graph(params);
    }
  }
});
console.log(`recorded hop and refresh variants for ${graphQueries.length} graph queries`);

// ---- write ------------------------------------------------------------------

await rm(outDir, { recursive: true, force: true });
await mkdir(path.join(outDir, "r"), { recursive: true });
const entries = {};
const written = new Set();
let bytes = 0;
for (const [key, { status, body }] of [...recorded].sort(([a], [b]) =>
  a < b ? -1 : 1,
)) {
  let clean = body;
  for (const [from, to] of scrub) clean = clean.split(from).join(to);
  const file = `${createHash("sha256").update(clean).digest("hex").slice(0, 20)}.json`;
  entries[key] = { status, file };
  if (written.has(file)) continue;
  written.add(file);
  bytes += Buffer.byteLength(clean);
  await writeFile(path.join(outDir, "r", file), clean);
}
await writeFile(
  path.join(outDir, "manifest.json"),
  `${JSON.stringify({ version: 1, recorded_at: new Date().toISOString(), entries }, null, 1)}\n`,
);
for (const warning of warnings) console.warn(`warning: ${warning}`);
console.log(
  `Snapshot: ${Object.keys(entries).length} responses, ${written.size} files, ${(bytes / 1e6).toFixed(1)} MB -> ${outDir}`,
);
