/**
 * Rasterize the deterministic Open Graph SVG into the 1200x630 PNG that chat
 * and social unfurlers accept (they do not render SVG previews).
 *
 * Usage: node scripts/render_og_png.mjs   (needs `npx playwright install chromium`)
 */
import { chromium } from "playwright";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const svgPath = path.join(webRoot, "public", "og", "grc-lake-share.svg");
const pngPath = path.join(webRoot, "public", "og", "grc-lake-share.png");
const WIDTH = 1200;
const HEIGHT = 630;

const svg = await readFile(svgPath, "utf8");
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
  await page.setContent(
    `<!doctype html><html><body style="margin:0;width:${WIDTH}px;height:${HEIGHT}px;overflow:hidden">${svg}</body></html>`,
    { waitUntil: "load" },
  );
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: pngPath, type: "png", clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT } });
} finally {
  await browser.close();
}
console.log(`wrote ${path.relative(process.cwd(), pngPath)}`);
