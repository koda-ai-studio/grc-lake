import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import {
  FRAMEWORK_VISUALS,
  frameworkIdFromControlId,
  frameworkVisual,
} from "../src/lib/framework-visuals";

// Pure checks on framework visuals; no browser page needed.

const PUBLIC = path.resolve(__dirname, "..", "public");

function badgeLabel(badge: string): string {
  const file = path.join(PUBLIC, badge.replace(/^\/console\//, ""));
  const svg = readFileSync(file, "utf-8");
  const match = svg.match(/aria-label="([^"]+)"/);
  if (!match) throw new Error(`${badge} has no aria-label`);
  return match[1];
}

test("a framework badge never names a different framework", () => {
  for (const [id, visual] of Object.entries(FRAMEWORK_VISUALS)) {
    if (!visual.badge) continue;
    const own = `${visual.label} ${id}`.toLowerCase();
    for (const word of badgeLabel(visual.badge).toLowerCase().split(/\s+/)) {
      expect(own, `${id} uses ${visual.badge}`).toContain(word);
    }
  }
});

test("ISO management clauses retain a separate identity from Annex A", () => {
  for (const id of [
    "ISO27001-4.1",
    "ISO27001-6.3",
    "ISO27001-9.2.1",
    "ISO27001-10.2",
  ]) {
    expect(frameworkIdFromControlId(id)).toBe("iso-27001-isms-2022");
  }
  expect(frameworkIdFromControlId("ISO27001-A.5.1")).toBe("iso-27001-2022");
  expect(frameworkVisual("ISO 27001 ISMS clauses").frameworkId).toBe(
    "iso-27001-isms-2022",
  );
  expect(frameworkVisual("iso-27001-isms-2022").label).toContain(
    "management clauses",
  );
});
