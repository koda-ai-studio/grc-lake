#!/usr/bin/env node
/**
 * Assemble the GitHub Pages site for the live demo from a `build:demo` export
 * and a recorded snapshot (scripts/record_demo_snapshot.mjs):
 *
 *   demo-site/index.html      redirect to the console dashboard
 *   demo-site/404.html        the console's not-found page
 *   demo-site/console/...     the static export
 *   demo-site/console/demo-api/{manifest.json,r/*.json}
 *
 * demo-site/ is published at the site root (e.g. /grc-lake/), so the console
 * must have been built with CONSOLE_BASE_PATH=<site root>/console.
 */
import { access, cp, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findDemoChunk } from "./static_export_guard.mjs";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(webRoot, "out");
const snapshotDir = path.resolve(
  process.env.GRC_LAKE_DEMO_SNAPSHOT_DIR || path.join(webRoot, "demo-snapshot"),
);
const siteDir = path.resolve(
  process.env.GRC_LAKE_DEMO_SITE_DIR || path.join(webRoot, "demo-site"),
);
const basePath = process.env.CONSOLE_BASE_PATH || "";
if (!/^(\/[A-Za-z0-9._-]+)*\/console$/.test(basePath))
  throw new Error(
    `CONSOLE_BASE_PATH must be <site root>/console (e.g. /grc-lake/console), got "${basePath}"`,
  );

const index = await readFile(path.join(outDir, "index.html"), "utf8");
if (!index.includes(`"${basePath}/_next/`))
  throw new Error(`out/ was not built for ${basePath}; run npm run build:demo`);
if (!(await findDemoChunk(outDir)))
  throw new Error("out/ is not a live-demo build (NEXT_PUBLIC_DEMO_SNAPSHOT=1)");
await access(path.join(snapshotDir, "manifest.json")).catch(() => {
  throw new Error(
    `No snapshot at ${snapshotDir}; record one with tools/record_demo_snapshot.sh`,
  );
});

await rm(siteDir, { recursive: true, force: true });
const consoleDir = path.join(siteDir, "console");
await cp(outDir, consoleDir, { recursive: true });
await cp(snapshotDir, path.join(consoleDir, "demo-api"), { recursive: true });
await cp(path.join(outDir, "404.html"), path.join(siteDir, "404.html"));
const dashboard = `${basePath}/dashboard/`;
await writeFile(
  path.join(siteDir, "index.html"),
  `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>GRC Lake live demo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url=${dashboard}">
<link rel="canonical" href="${dashboard}">
</head>
<body>
<p><a href="${dashboard}">Open the GRC Lake live demo</a></p>
</body>
</html>
`,
);
console.log(`Live demo site assembled in ${siteDir}`);
