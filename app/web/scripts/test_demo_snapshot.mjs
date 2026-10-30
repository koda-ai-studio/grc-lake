import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { loadTsModule } from "./load_ts_module.mjs";
import { DEMO_ROUTES } from "./demo_routes.mjs";
import { buildGraphNavigation } from "./demo_graph_navigation.mjs";

const demo = await loadTsModule(
  new URL("../src/lib/demo/snapshot.ts", import.meta.url),
);

const ORIGIN = "https://example.test";

function manifest(entries) {
  return { version: 1, recorded_at: "2026-10-23T00:00:00Z", entries };
}

function harness(entries = {}) {
  const calls = [];
  const blocked = [];
  const realFetch = async (input) => {
    const url = typeof input === "string" ? input : input.url;
    calls.push(url);
    if (url.endsWith("/demo-api/manifest.json"))
      return Response.json(manifest(entries));
    if (url.includes("/demo-api/r/"))
      return new Response(`{"data":"${url.split("/").pop()}"}`, {
        headers: { "content-type": "application/json" },
      });
    return new Response("passthrough");
  };
  const fetch = demo.createDemoFetch({
    realFetch,
    origin: ORIGIN,
    dataBase: "/grc-lake/console/demo-api",
    onBlockedMutation: (method, url) => blocked.push(`${method} ${url}`),
  });
  return { fetch, calls, blocked };
}

test("snapshot keys ignore query order and origin but keep the API path", () => {
  const a = demo.snapshotKey("/api/v1/controls?offset=0&limit=500", ORIGIN);
  const b = demo.snapshotKey(
    `${ORIGIN}/api/v1/controls?limit=500&offset=0`,
    ORIGIN,
  );
  assert.equal(a, b);
  assert.equal(a, "/api/v1/controls?limit=500&offset=0");
  assert.equal(
    demo.snapshotKey("/api/v1/healthz", ORIGIN),
    "/api/v1/healthz",
  );
  assert.notEqual(
    demo.snapshotKey("/api/v1/controls?limit=5", ORIGIN),
    demo.snapshotKey("/api/v1/controls?limit=50", ORIGIN),
  );
});

test("snapshot keys keep encoded path segments distinct from separators", () => {
  const encoded = demo.snapshotKey(
    "/api/v1/violations/NIST-AI-RMF-GOVERN-1.2%3Agolden-036/tracking",
    ORIGIN,
  );
  assert.equal(
    encoded,
    "/api/v1/violations/NIST-AI-RMF-GOVERN-1.2%3Agolden-036/tracking",
  );
  assert.equal(
    demo.snapshotKey("/api/v1/tags/for?entity_id=a%3Ab&entity_type=x", ORIGIN),
    demo.snapshotKey("/api/v1/tags/for?entity_type=x&entity_id=a:b", ORIGIN),
  );
});

test("a recorded GET is served from the static snapshot with its status", async () => {
  const { fetch, calls } = harness({
    "/api/v1/controls?limit=500&offset=0": { status: 200, file: "abc.json" },
  });
  const res = await fetch("/api/v1/controls?offset=0&limit=500", {
    cache: "no-store",
  });
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { data: "abc.json" });
  assert.ok(calls.includes("/grc-lake/console/demo-api/r/abc.json"));
  assert.ok(!calls.some((url) => url.startsWith("/api/")));
});

test("a recorded non-2xx status is replayed, not upgraded to success", async () => {
  const { fetch } = harness({
    "/api/v1/billing": { status: 501, file: "billing.json" },
  });
  const res = await fetch("/api/v1/billing");
  assert.equal(res.status, 501);
});

test("an unrecorded GET fails as unavailable in the demo, never as a live API call", async () => {
  const { fetch, calls } = harness({});
  const res = await fetch(new Request(`${ORIGIN}/api/v1/risks?limit=1`));
  assert.equal(res.status, demo.DEMO_UNRECORDED_STATUS);
  const body = await res.json();
  assert.equal(body.errors[0].detail, demo.DEMO_UNRECORDED_MESSAGE);
  assert.ok(!calls.some((url) => url.includes("/api/v1/risks")));
});

for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
  test(`${method} requests are blocked as read-only and never leave the page`, async () => {
    const { fetch, calls, blocked } = harness({
      "/api/v1/risks/r1": { status: 200, file: "r1.json" },
    });
    const res = await fetch("/api/v1/risks/r1", { method, body: "{}" });
    assert.equal(res.status, demo.DEMO_READ_ONLY_STATUS);
    const body = await res.json();
    assert.equal(body.reason, demo.DEMO_READ_ONLY_MESSAGE);
    assert.deepEqual(blocked, [`${method} /api/v1/risks/r1`]);
    assert.ok(!calls.some((url) => url.includes("/api/v1/risks")));
  });
}

test("a Request object's method is honoured when blocking mutations", async () => {
  const { fetch, blocked } = harness({});
  const res = await fetch(
    new Request(`${ORIGIN}/api/v1/snapshots`, { method: "POST", body: "{}" }),
  );
  assert.equal(res.status, demo.DEMO_READ_ONLY_STATUS);
  assert.equal(blocked.length, 1);
});

test("non-API requests pass through untouched", async () => {
  const { fetch, calls } = harness({});
  const res = await fetch("/grc-lake/console/frameworks/badges/soc2.svg");
  assert.equal(await res.text(), "passthrough");
  assert.deepEqual(calls, ["/grc-lake/console/frameworks/badges/soc2.svg"]);
});

test("the manifest is fetched once and shared across requests", async () => {
  const { fetch, calls } = harness({
    "/api/v1/tags": { status: 200, file: "t.json" },
  });
  await Promise.all([fetch("/api/v1/tags"), fetch("/api/v1/tags")]);
  await fetch("/api/v1/healthz");
  assert.equal(calls.filter((url) => url.endsWith("manifest.json")).length, 1);
});

test("the package copy refuses a demo build or a foreign base path", async () => {
  const { assertPackageBundle, DEMO_MARKER: GUARD_MARKER } = await import(
    "./static_export_guard.mjs"
  );
  const make = (html, chunk) => {
    const dir = mkdtempSync(path.join(tmpdir(), "grc-export-"));
    mkdirSync(path.join(dir, "_next/static/chunks"), { recursive: true });
    writeFileSync(path.join(dir, "index.html"), html);
    writeFileSync(path.join(dir, "_next/static/chunks/a.js"), chunk);
    return dir;
  };
  assert.equal(GUARD_MARKER, demo.DEMO_MARKER);
  const ok = '<script src="/console/_next/static/chunks/a.js"></script>';
  await assertPackageBundle(make(ok, "console.log(1)"));
  await assert.rejects(
    assertPackageBundle(make(ok, `x="${demo.DEMO_MARKER}"`)),
    /live-demo build/,
  );
  await assert.rejects(
    assertPackageBundle(
      make('<script src="/grc-lake/console/_next/a.js"></script>', "1"),
    ),
    /\/console/,
  );
});

test("the recorder crawls every static console route", () => {
  const appDir = fileURLToPath(new URL("../src/app/", import.meta.url));
  const routes = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name === "page.tsx") {
        const route = `/${path.relative(appDir, dir).split(path.sep).join("/")}`;
        if (route !== "/" && !route.includes("[")) routes.push(`${route}/`);
      }
    }
  };
  walk(appDir);
  const crawled = new Set(DEMO_ROUTES.map((r) => r.route.split("?")[0]));
  const missing = routes.filter((route) => !crawled.has(route));
  assert.deepEqual(missing, []);
});


test("recorded starting points require every exact depth and refresh variant without merging account identities", () => {
  const recorded = new Map();
  const layers = "account,asset,control,source";
  function add(id, options = {}) {
    for (const depth of [1, 2, 3]) for (const pinned of [false, true]) {
      if (options.incomplete && depth === 3 && !pinned) continue;
      const params = new URLSearchParams({
        view: "environment", root: id, depth: String(depth), limit: "150",
        layers, root_offset: "0", search: "", ...options.params,
      });
      if (pinned) params.set("version", options.stale ? "old" : "generation");
      const node = { id, label: "Shared display name", kind: "account" };
      recorded.set(`/api/v1/graph/investigation?${params}`, {
        status: options.status ?? 200,
        body: JSON.stringify({ data: { root: id, depth, version: "generation", nodes: [node] } }),
      });
    }
  }
  add("account:aws:one");
  add("account:aws:two");
  add("account:partial", { incomplete: true });
  add("account:stale", { stale: true });
  add("account:denied", { status: 403 });
  add("account:filtered", { params: { layers: "account" } });
  add("account:search", { params: { search: "needle" } });
  add("account:paged", { params: { root_offset: "50" } });
  add("account:unknown-parameter", { params: { unknown: "true" } });
  add("account:unknown-view", { params: { view: "__proto__" } });
  const navigation = buildGraphNavigation(recorded, ORIGIN, layers);
  assert.deepEqual(navigation.environment.map(node => node.id), ["account:aws:one", "account:aws:two"]);
  assert.deepEqual(navigation.controls, []);
  assert.deepEqual(navigation.investigation, []);
  assert.ok(navigation.environment.every(node => node.version === "generation"));
});
