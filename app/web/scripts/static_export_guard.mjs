import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

// Kept literal (not imported from src/lib/demo/snapshot.ts) so this guard has
// no build-time dependency; test_demo_snapshot.mjs pins the two together.
export const DEMO_MARKER = "grc-lake-demo-snapshot";

async function* files(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* files(full);
    else yield full;
  }
}

/** The first bundle chunk carrying the live-demo replay code, or null. */
export async function findDemoChunk(outDir) {
  for await (const file of files(path.join(outDir, "_next"))) {
    if (file.endsWith(".js") && (await readFile(file, "utf8")).includes(DEMO_MARKER))
      return path.relative(outDir, file);
  }
  return null;
}

/**
 * The Python package serves the console at /console with a live API. A
 * live-demo build replays a snapshot under another path; shipping it would
 * break the wheel, so the package copy refuses one.
 */
export async function assertPackageBundle(outDir) {
  const index = await readFile(path.join(outDir, "index.html"), "utf8");
  if (!index.includes('"/console/_next/'))
    throw new Error(
      "Static export is not built for /console; refusing to copy it into the Python package.",
    );
  const demoChunk = await findDemoChunk(outDir);
  if (demoChunk)
    throw new Error(
      `${demoChunk} is from a live-demo build; refusing to copy it into the Python package.`,
    );
}
