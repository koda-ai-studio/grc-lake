#!/usr/bin/env node
/**
 * Serve demo-site/ under its Pages path (default /grc-lake) the way GitHub
 * Pages does: directory index.html, 404.html for misses, and no API. Used by
 * playwright.demo.config.ts; not a production server.
 */
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const siteDir = path.resolve(
  process.env.GRC_LAKE_DEMO_SITE_DIR || path.join(webRoot, "demo-site"),
);
const sitePath = (process.env.DEMO_SITE_PATH || "/grc-lake").replace(/\/$/, "");
const port = Number(process.env.DEMO_SITE_PORT || 4173);
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".woff2": "font/woff2",
};

async function resolve(urlPath) {
  if (!urlPath.startsWith(`${sitePath}/`) && urlPath !== sitePath) return null;
  const relative = decodeURIComponent(urlPath.slice(sitePath.length));
  const file = path.join(siteDir, relative);
  if (file !== siteDir && !file.startsWith(`${siteDir}${path.sep}`)) return null;
  const info = await stat(file).catch(() => null);
  if (info?.isFile()) return file;
  if (info?.isDirectory()) {
    const index = path.join(file, "index.html");
    if ((await stat(index).catch(() => null))?.isFile()) return index;
  }
  return null;
}

createServer(async (req, res) => {
  const { pathname } = new URL(req.url, "http://localhost");
  const file = await resolve(pathname);
  const target = file ?? path.join(siteDir, "404.html");
  res.writeHead(file ? 200 : 404, {
    "content-type": TYPES[path.extname(target)] ?? "application/octet-stream",
  });
  createReadStream(target).pipe(res);
}).listen(port, "127.0.0.1", () =>
  console.log(`Live demo at http://127.0.0.1:${port}${sitePath}/`),
);
