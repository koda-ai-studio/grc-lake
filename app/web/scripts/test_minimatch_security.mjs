import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import test from "node:test";

const require = createRequire(import.meta.url);
const dependency = createRequire(
  require.resolve("@typescript-eslint/typescript-estree"),
).resolve("minimatch");

test("TypeScript tooling bounds globstar parent expansion", () => {
  const child = spawnSync(process.execPath, ["--max-old-space-size=96", "-e", `
    const assert = require('node:assert/strict');
    const { Minimatch } = require(${JSON.stringify(dependency)});
    const pattern = '**/../a/b/'.repeat(8) + 'z';
    const matcher = new Minimatch(pattern, { optimizationLevel: 2, braceExpandMax: 32 });
    assert.ok(matcher.globParts.length <= 32,
      'expansion exceeded the requested bound: ' + matcher.globParts.length);
  `], { timeout: 5000, encoding: "utf8" });
  assert.equal(child.error, undefined, child.error?.message);
  assert.equal(child.status, 0, child.stderr);
});

test("TypeScript tooling retains ordinary file matching", () => {
  const { minimatch, Minimatch } = require(dependency);
  assert.equal(minimatch("src/example.ts", "src/**/*.{ts,tsx}"), true);
  assert.equal(minimatch("src/example.js", "src/**/*.{ts,tsx}"), false);
  const matcher = new Minimatch("src/**/*.ts", {
    optimizationLevel: 2,
    braceExpandMax: 32,
  });
  assert.equal(matcher.match("src/a/b/example.ts"), true);
});
