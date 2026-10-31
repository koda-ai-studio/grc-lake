import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

const require = createRequire(import.meta.url);
const dependency = createRequire(
  require.resolve("@typescript-eslint/typescript-estree"),
).resolve("minimatch");

test("lockfile contains only patched upstream minimatch engines", () => {
  const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
  const engines = Object.entries(lock.packages).filter(([, pkg]) =>
    pkg.resolved?.startsWith("https://registry.npmjs.org/minimatch/-/"),
  );
  assert.ok(engines.length > 0);
  for (const [path, pkg] of engines) {
    const [major, minor, patch] = pkg.version.split(".").map(Number);
    assert.ok(major > 11 || (major === 11 && (minor > 0 || patch >= 1)), `${path}: ${pkg.version}`);
  }
});

const nextRequire = createRequire(require.resolve("eslint-config-next"));
test("import rule keeps enforcing forbidden internal module patterns", () => {
  const { Linter } = require("eslint");
  const plugin = nextRequire("eslint-plugin-import");
  const messages = new Linter().verify(
    'import hidden from "./private/hidden.js"; import visible from "./public/visible.js";',
    {
      plugins: { import: plugin },
      rules: { "import/no-internal-modules": ["error", { forbid: ["private/**"] }] },
    },
  );
  assert.equal(messages.length, 1);
  assert.equal(messages[0].ruleId, "import/no-internal-modules");
  assert.match(messages[0].message, /private\/hidden/);
});

for (const consumer of ["eslint", "@eslint/config-array", "@eslint/eslintrc",
  "eslint-plugin-import", "eslint-plugin-react", "eslint-plugin-jsx-a11y"]) {
  test(`${consumer} retains callable matching and constructor helpers`, () => {
    const consumerRequire = createRequire(
      consumer.startsWith("eslint-plugin-") ? nextRequire.resolve(consumer) : require.resolve(consumer),
    );
    const match = consumerRequire("minimatch");
    assert.equal(typeof match, "function");
    assert.equal(match("src/example.ts", "src/**/*.{ts,tsx}"), true);
    assert.equal(match("src/example.js", "src/**/*.{ts,tsx}"), false);
    assert.equal(match(".config.js", "*.js", { dot: true }), true);
    assert.equal(match("src/example.test.ts", "!**/*.test.ts"), false);
    assert.equal(new match.Minimatch("src/**/*.ts").match("src/a/example.ts"), true);
    assert.deepEqual(match.match(["a.ts", "b.js"], "*.ts"), ["a.ts"]);
    assert.equal(match.defaults({ nocase: true })("A.TS", "*.ts"), true);
    assert.ok(new match.Minimatch("**/../a/b/".repeat(8) + "z", {
      optimizationLevel: 2, braceExpandMax: 32,
    }).globParts.length <= 32);
  });
}

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
