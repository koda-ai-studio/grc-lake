/**
 * Evidence outcomes as the evaluator reads them (`event_status.py`,
 * `evidence_freshness.py`), including the aliases it normalises.
 */
export const PASSING_STATUSES = new Set([
  "pass",
  "passed",
  "resolved",
  "closed",
  "compliant",
  "ok",
  "ready",
]);

export const FAILING_STATUSES = new Set([
  "open",
  "failed",
  "fail",
  "failing",
  "blocked",
  "noncompliant",
  "non-compliant",
]);

/** Freshness that cannot support a pass: aged out, or never recorded. */
export const STALE_FRESHNESS = new Set(["stale", "expired", "missing"]);
