import type { ConnectorView } from "./api/types";

export interface ConnectionReadiness {
  label: string;
  detail: string;
  action: string;
  tone: "ready" | "attention" | "critical" | "default";
  attention: boolean;
  evidenceReady: boolean;
}

/** Collection progress, never a control result or provider qualification. */
export function connectionReadiness(
  connector: ConnectorView,
  now = Date.now(),
): ConnectionReadiness {
  const state = (
    label: string,
    detail: string,
    action: string,
    tone: ConnectionReadiness["tone"] = "default",
    evidenceReady = false,
  ): ConnectionReadiness => ({
    label,
    detail,
    action,
    tone,
    evidenceReady,
    attention: tone === "critical" || tone === "attention",
  });
  if (!connector.is_implemented) {
    return state(
      "Collection unavailable",
      "An access contract exists; evidence collection is not implemented.",
      "Review contract",
    );
  }
  const probe = connector.last_probe;
  const sync = connector.last_sync;
  if (probe?.result === "error") {
    return state(
      "Access check failed",
      "Review permissions and configuration, then test access again.",
      "Review access",
      "critical",
    );
  }
  if (connector.state !== "enabled") {
    if (probe?.result === "ok" && probe.metadata?.probe_mode === "live") {
      return state(
        "Read access verified",
        "Enable this source to allow evidence collection.",
        "Enable source",
      );
    }
    if (probe?.result === "skipped" || probe?.result === "ok") {
      return state(
        "Configuration checked",
        "A configuration check does not verify provider read access. Review the scope before enabling.",
        "Review and enable",
      );
    }
    return state(
      "Set up a source",
      "Configure read-only access, then test the connection.",
      "Set up connection",
    );
  }
  if (sync?.result === "error") {
    return state(
      "Latest sync failed",
      "Older evidence may remain available. Review the run error and retry collection.",
      "Review failed sync",
      "critical",
    );
  }
  if (!sync) {
    return state(
      "Awaiting first evidence",
      "This source is enabled. Run its first sync to collect evidence.",
      "Run first sync",
      "attention",
    );
  }
  if (sync.result !== "ok") {
    return state(
      "Sync did not collect",
      "The latest sync was skipped. Review the run before retrying.",
      "Review sync",
      "attention",
    );
  }
  if (
    sync.metadata?.partial === true ||
    (Array.isArray(sync.metadata?.coverage_gaps) &&
      sync.metadata.coverage_gaps.length > 0)
  ) {
    return state(
      "Partial evidence collected",
      "Some source data could not be collected. Review the recorded gaps and retry before relying on coverage.",
      "Review collection gaps",
      "attention",
    );
  }
  if (sync.evidence_count === 0) {
    return state(
      "No evidence returned",
      "The sync completed with zero rows. Check the selected scope and source data.",
      "Review collection scope",
      "attention",
    );
  }
  if (
    typeof sync.evidence_count !== "number" ||
    !Number.isFinite(sync.evidence_count) ||
    sync.evidence_count < 0
  ) {
    return state(
      "Evidence count unknown",
      "The run does not record a valid evidence count.",
      "Review sync",
      "attention",
    );
  }
  const ageMinutes = (now - Date.parse(sync.occurred_at)) / 60000;
  if (!Number.isFinite(ageMinutes) || ageMinutes < 0) {
    return state(
      "Sync time needs review",
      "The collection timestamp is missing, invalid, or in the future.",
      "Review sync",
      "attention",
    );
  }
  const slo =
    connector.freshness_slo_minutes > 0
      ? connector.freshness_slo_minutes
      : 1440;
  if (connector.freshness_state === "stale" || ageMinutes > slo) {
    return state(
      "Evidence is stale",
      "Collect again to refresh evidence within this source's freshness window.",
      "Refresh evidence",
      "attention",
    );
  }
  if (connector.freshness_state && connector.freshness_state !== "fresh") {
    return state(
      "Freshness unconfirmed",
      "The server has not confirmed a fresh collection.",
      "Review sync",
      "attention",
    );
  }
  return state(
    "Recent evidence collected",
    `${sync.evidence_count} raw rows in the latest sync. Evaluate controls to inspect results and gaps.`,
    "Review evidence",
    "ready",
    true,
  );
}
