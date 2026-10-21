import { expect, test } from "@playwright/test";
import type { ConnectorRun, ConnectorView } from "../src/lib/api/types";
import { connectionReadiness } from "../src/lib/connection-readiness";
const now = Date.parse("2026-10-21T12:00:00Z");
const run = (overrides: Partial<ConnectorRun> = {}): ConnectorRun => ({
  connector_id: "github-repo",
  kind: "sync",
  result: "ok",
  actor: "test",
  duration_ms: 10,
  evidence_count: 4,
  error: null,
  access_fingerprint: null,
  occurred_at: "2026-10-21T11:00:00Z",
  ...overrides,
});
const source = (overrides: Partial<ConnectorView> = {}) =>
  ({
    connector_id: "github-repo",
    name: "GitHub",
    is_implemented: true,
    state: "enabled",
    freshness_state: "fresh",
    freshness_slo_minutes: 240,
    last_sync: run(),
    last_successful_sync: run(),
    last_probe: null,
    ...overrides,
  }) as ConnectorView;

test("a failed latest collection cannot be hidden by older fresh evidence", () => {
  const result = connectionReadiness(
    source({ last_sync: run({ result: "error", evidence_count: 0 }) }),
    now,
  );
  expect(result.label).toBe("Latest sync failed");
  expect(result.attention).toBe(true);
  expect(result.tone).not.toBe("ready");
});
test("empty, skipped, and missing counts are not evidence-ready", () => {
  for (const last_sync of [
    run({ evidence_count: 0 }),
    run({ evidence_count: null }),
    run({ result: "skipped" }),
  ]) {
    expect(connectionReadiness(source({ last_sync }), now).evidenceReady).toBe(
      false,
    );
  }
});
test("freshness must be known and timestamps valid, including legacy responses", () => {
  for (const occurred_at of ["bad", "2026-10-22T00:00:00Z"]) {
    expect(
      connectionReadiness(source({ last_sync: run({ occurred_at }) }), now)
        .evidenceReady,
    ).toBe(false);
  }
  expect(
    connectionReadiness(source({ freshness_state: "stale" }), now).label,
  ).toBe("Evidence is stale");
  expect(
    connectionReadiness(source({ freshness_state: undefined }), now)
      .evidenceReady,
  ).toBe(true);
  expect(
    connectionReadiness(source({ freshness_state: "unrecognized" }), now)
      .evidenceReady,
  ).toBe(false);
});
test("configuration-only and skipped probes never claim read access", () => {
  for (const last_probe of [
    run({ kind: "probe", result: "skipped" }),
    run({ kind: "probe", metadata: { probe_mode: "config_only" } }),
  ]) {
    expect(
      connectionReadiness(
        source({
          state: "disabled",
          configured_at: "2026-10-21T10:00:00Z",
          last_probe,
        }),
        now,
      ).label,
    ).toBe("Configuration checked");
  }
  expect(
    connectionReadiness(
      source({
        state: "disabled",
        last_probe: run({ kind: "probe", metadata: { probe_mode: "live" } }),
      }),
      now,
    ).label,
  ).toBe("Read access verified");
});
test("enabled and contract-only sources are not automatically ready", () => {
  expect(connectionReadiness(source({ last_sync: null }), now).action).toBe(
    "Run first sync",
  );
  expect(
    connectionReadiness(source({ is_implemented: false }), now).evidenceReady,
  ).toBe(false);
  expect(
    connectionReadiness(source({ last_probe: run({ result: "error" }) }), now)
      .attention,
  ).toBe(true);
  expect(connectionReadiness(source(), now).label).toBe(
    "Recent evidence collected",
  );
});
