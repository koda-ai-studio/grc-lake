import { expect, test } from "@playwright/test";

// The findings page offers the portable grc-lake.findings.v1 export through the
// live API. The download must carry the server's filename and the documented
// header row, never a JSON envelope.

const COLUMNS = [
  "export_schema_version",
  "finding_id",
  "tenant_id",
  "source_account_id",
  "control_id",
  "framework_ids",
  "asset_id",
  "severity",
  "state",
  "detected_at",
  "evaluated_at",
  "snapshot_id",
  "assessment_hash",
  "source",
  "event_type",
  "evidence_ref",
];

test("findings export downloads a CSV with the v1 header", async ({ page }) => {
  await page.goto("/console/violations/");
  const button = page.getByRole("button", { name: "Export findings as CSV" });
  await expect(button).toBeEnabled({ timeout: 20_000 });
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    button.click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^grc-lake-findings-.*\.csv$/);
  const path = await download.path();
  expect(path).not.toBeNull();
  const { readFileSync } = await import("node:fs");
  const text = readFileSync(path!, "utf8");
  const [header, firstRow] = text.split("\r\n");
  expect(header).toBe(COLUMNS.join(","));
  expect(firstRow).toContain("grc-lake.findings.v1");
});

test("findings export downloads JSONL rows", async ({ page }) => {
  await page.goto("/console/violations/");
  const button = page.getByRole("button", { name: "Export findings as JSONL" });
  await expect(button).toBeEnabled({ timeout: 20_000 });
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    button.click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.jsonl$/);
  const { readFileSync } = await import("node:fs");
  const lines = readFileSync((await download.path())!, "utf8")
    .trim()
    .split("\n");
  expect(lines.length).toBeGreaterThan(0);
  const row = JSON.parse(lines[0]);
  expect(Object.keys(row)).toEqual(COLUMNS);
  expect(row.export_schema_version).toBe("grc-lake.findings.v1");
  expect(row).not.toHaveProperty("raw_sha256");
});
