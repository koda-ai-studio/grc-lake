#!/usr/bin/env bash
# Record the read-only live demo snapshot: load the golden fixture, serve it
# with auth and rate limiting off on loopback, and crawl the console.
# Output: app/web/demo-snapshot/ (consumed by `npm --prefix app/web run build:demo`).
# Needs the packaged console (`make web-build`) and Playwright Chromium.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${GRC_LAKE_DEMO_PORT:-8790}"
BASE="http://127.0.0.1:${PORT}"
LAKE="$(mktemp -d "${TMPDIR:-/tmp}/grc-lake-demo.XXXXXX")"

echo "==> Load golden fixture into ${LAKE}"
uv run grc-lake fixtures load --company golden --out "$LAKE" --rebase-times
uv run grc-lake db upgrade --lake "$LAKE"

echo "==> Start server on ${BASE}"
export GRC_LAKE_COOKIE_SIGNING_KEY="${GRC_LAKE_COOKIE_SIGNING_KEY:-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx}"
# The crawl replays every record's detail view; the default per-client rate
# limit is sized for interactive use, not a recorder on loopback.
GRC_LAKE_API_RATE_LIMIT_RPS=0 uv run grc-lake serve \
  --lake "$LAKE" \
  --server \
  --allow-insecure-no-auth \
  --port "$PORT" \
  --host 127.0.0.1 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  rm -rf "$LAKE"
}
trap cleanup EXIT

deadline=$((SECONDS + 45))
until curl -sf "${BASE}/api/v1/healthz" >/dev/null 2>&1; do
  if (( SECONDS > deadline )); then
    echo "Server failed to start on ${BASE}" >&2
    exit 1
  fi
  sleep 0.5
done

echo "==> Record console API responses"
GRC_LAKE_DEMO_SOURCE_URL="$BASE" GRC_LAKE_DEMO_LAKE="$LAKE" \
  npm --prefix app/web run record:demo
