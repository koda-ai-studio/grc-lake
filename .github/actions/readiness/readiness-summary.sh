#!/usr/bin/env bash
# GRC Lake readiness summary: render /api/v1/posture/current as a framework table,
# run the posture gate, and optionally upsert one pull request comment.
set -euo pipefail

GRC_LAKE_URL="${GRC_LAKE_URL:-}"
GRC_LAKE_API_TOKEN="${GRC_LAKE_API_TOKEN:-}"
CORRELATION_ID="${CORRELATION_ID:-}"
FRAMEWORK="${FRAMEWORK:-}"
SUMMARY="${SUMMARY:-true}"
COMMENT_ON_PR="${COMMENT_ON_PR:-false}"
ENFORCE="${ENFORCE:-true}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_API_URL="${GITHUB_API_URL:-https://api.github.com}"
POSTURE_GATE_SCRIPT="${POSTURE_GATE_SCRIPT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../posture-gate" && pwd)/posture-gate.sh}"
MARKER="<!-- grc-lake-readiness -->"
TITLE="GRC Lake readiness"

fail() {
  echo "::error title=${TITLE}::$1"
  exit 1
}

for flag in SUMMARY COMMENT_ON_PR ENFORCE; do
  value="${!flag}"
  if [[ "${value}" != "true" && "${value}" != "false" ]]; then
    fail "$(echo "${flag}" | tr '[:upper:]_' '[:lower:]-') must be true or false, got '${value}'"
  fi
done
[[ -n "${GRC_LAKE_URL}" ]] || fail "grc-lake-url is required"
command -v jq >/dev/null 2>&1 || fail "jq is required on the runner"
command -v curl >/dev/null 2>&1 || fail "curl is required on the runner"

pr_number=""
if [[ "${COMMENT_ON_PR}" == "true" ]]; then
  case "${GITHUB_EVENT_NAME:-}" in
    pull_request | pull_request_target)
      pr_number="$(jq -r '.pull_request.number // empty' "${GITHUB_EVENT_PATH:-/dev/null}" 2>/dev/null || true)"
      ;;
  esac
  if [[ -z "${pr_number}" ]]; then
    echo "::notice title=${TITLE}::comment-on-pr is set, but this run is not for a pull request; skipping the comment"
  elif [[ -z "${GITHUB_TOKEN}" || -z "${GITHUB_REPOSITORY:-}" ]]; then
    fail "comment-on-pr needs github-token (with pull-requests: write) and GITHUB_REPOSITORY"
  fi
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT
summary_path="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/grc-lake-readiness.XXXXXX")/summary.md"

base="${GRC_LAKE_URL%/}"
curl_args=(-fsS --max-time 60 -H "Accept: application/json")
if [[ -n "${GRC_LAKE_API_TOKEN}" ]]; then
  curl_args+=(-H "Authorization: Bearer ${GRC_LAKE_API_TOKEN}")
fi
if [[ -n "${CORRELATION_ID}" ]]; then
  curl_args+=(-H "X-Correlation-ID: ${CORRELATION_ID}")
fi

posture_file="${work_dir}/posture.json"
if ! curl "${curl_args[@]}" -o "${posture_file}" "${base}/api/v1/posture/current"; then
  fail "Failed to reach ${base}/api/v1/posture/current"
fi
if ! jq -e '(.data.posture | type == "object") and (.data.frameworks | type == "array")' \
  "${posture_file}" >/dev/null 2>&1; then
  detail="$(jq -r '.errors[0].detail // "unexpected response"' "${posture_file}" 2>/dev/null || echo "unexpected response")"
  fail "Unusable posture response: ${detail}"
fi

# The gate re-reads posture and control tests and writes the posture_* outputs.
gate_log="${work_dir}/gate.log"
set +e
bash "${POSTURE_GATE_SCRIPT}" >"${gate_log}" 2>&1
gate_status=$?
set -e
if [[ "${ENFORCE}" == "true" ]]; then
  cat "${gate_log}"
else
  sed 's/^::error /::warning /' "${gate_log}"
fi
gate_reasons="$(sed -n 's/^::error title=GRC Lake posture gate:://p' "${gate_log}")"

# jq variables such as $filter are bound by jq --arg, not by the shell.
# shellcheck disable=SC2016
READY_FILTER='def n: . // 0;
def ready: .state == "ready" and (.control_count | n) > 0
  and (.passing_control_count | n) == (.control_count | n)
  and (.not_evaluated_control_count | n) == 0 and (.collection_gap_control_count | n) == 0;
def rows: [.data.frameworks[] | select($filter == "" or .framework == $filter)];'

jq -r \
  --arg marker "${MARKER}" \
  --arg filter "${FRAMEWORK}" \
  --arg enforce "${ENFORCE}" \
  --argjson gate_status "${gate_status}" \
  --arg gate_reasons "${gate_reasons}" \
  "${READY_FILTER}"'
def num: (. // 0) as $v | (($v * 100 | round) / 100) as $r
  | if ($r | floor) == $r then "\($r | floor).0" else ($r | tostring) end;
def cell: tostring | gsub("[\r\n]+"; " ") | gsub("\\|"; "\\|");
def plural($count; $word): "\($count) \($word)\(if $count == 1 then "" else "s" end)";
def state_label:
  if ready then "ready"
  elif .state == "ready" then
    [ (if (.not_evaluated_control_count | n) > 0 then "\(.not_evaluated_control_count) not evaluated" else empty end),
      (if (.collection_gap_control_count | n) > 0 then "\(.collection_gap_control_count) with collection gaps" else empty end) ]
    | if length > 0 then "not ready (\(join(", ")))" else "not ready" end
  else (.state // "unknown" | tostring | gsub("_"; " ")) end;

.data as $d
| $d.posture as $p
| rows as $rows
| ($gate_reasons | split("\n") | map(select(length > 0))) as $reasons
| [
    $marker,
    "### GRC Lake readiness",
    "",
    (if $d.synthetic_fixture == true then
       "> **Synthetic sample data.** These results come from bundled fixture evidence, not from your systems.\n"
     else empty end),
    "**Posture \($p.score | num)** (\($p.state // "unknown" | tostring | gsub("_"; " "))) · \([$rows[] | select(ready)] | length) of \(plural($rows | length; "framework")) ready · \(plural($p.open_violation_count | n; "open violation")) (\($p.critical_violation_count | n) critical) · \(plural($p.failed_control_test_count | n; "failing control test")) · \(plural($p.stale_evidence_count | n; "stale evidence row"))",
    "",
    (if ($rows | length) == 0 then
       (if $filter != "" then "No framework named `\($filter | cell)` is in this assessment."
        else "No frameworks were evaluated. Nothing here is ready." end)
     else
       "| Framework | Score | State | Passing / total controls | Failing | Not evaluated | Collection-gap controls |",
       "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
       ($rows[] | "| \(.framework | cell) | \(.score | num) | \(state_label | cell) | \(.passing_control_count | n) / \(.control_count | n) | \(.failing_control_count | n) | \(.not_evaluated_control_count | n) | \(.collection_gap_control_count | n) |")
     end),
    "",
    (if ($p.not_evaluated_control_count | n) > 0 then
       "**Not evaluated:** \(plural($p.not_evaluated_control_count; "control")) not evaluated. A control without a current result blocks readiness and is never counted as passing.\n"
     else empty end),
    (if (($d.collection_gaps.sources // []) | length) > 0 then
       "**Collection gaps:** \($d.collection_gaps.sources | map("`\(cell)`") | join(", ")) did not fully collect; \(plural(($d.collection_gaps.affected_control_ids // []) | length; "control")) affected. Their frameworks are not ready until collection completes.\n"
     else empty end),
    (if $gate_status == 0 then "**Gate: passed**"
     elif $enforce == "true" then "**Gate: failed**"
     else "**Gate: not enforced** (it would fail)" end),
    ($reasons[] | "- \(cell)"),
    (if $gate_status != 0 and ($reasons | length) == 0 then "- see the job log" else empty end),
    "",
    "<sub>A framework is ready only when every control passes with current evidence. Evaluated \($d.evaluated_at // "at an unknown time") from `GET /api/v1/posture/current`.</sub>"
  ]
| join("\n")' "${posture_file}" >"${summary_path}"

ready_count="$(jq --arg filter "${FRAMEWORK}" "${READY_FILTER}"' [rows[] | select(ready)] | length' "${posture_file}")"
evaluated_count="$(jq --arg filter "${FRAMEWORK}" "${READY_FILTER}"' rows | length' "${posture_file}")"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "summary-path=${summary_path}"
    echo "frameworks-ready-count=${ready_count}"
    echo "frameworks-evaluated-count=${evaluated_count}"
  } >>"${GITHUB_OUTPUT}"
fi
if [[ "${SUMMARY}" == "true" && -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat "${summary_path}" >>"${GITHUB_STEP_SUMMARY}"
fi
echo "Readiness summary: ${ready_count} of ${evaluated_count} framework(s) ready (${summary_path})"

github_api() {
  # The token goes through a curl config on stdin so it never appears in argv or logs.
  local method="$1" url="$2" out="$3"
  shift 3
  printf 'header = "Authorization: Bearer %s"\n' "${GITHUB_TOKEN}" |
    curl -sS --max-time 30 -K - -X "${method}" -o "${out}" -w '%{http_code}' \
      -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$@" "${url}" ||
    true
}

if [[ -n "${pr_number}" ]]; then
  repo_api="${GITHUB_API_URL%/}/repos/${GITHUB_REPOSITORY}"
  comment_id=""
  listed=true
  for page in 1 2 3 4 5 6 7 8 9 10; do
    status="$(github_api GET "${repo_api}/issues/${pr_number}/comments?per_page=100&page=${page}" "${work_dir}/comments.json")"
    if [[ "${status}" != "200" ]]; then
      echo "::warning title=${TITLE}::Could not list pull request comments (HTTP ${status:-000}); the job summary is unaffected"
      listed=false
      break
    fi
    comment_id="$(jq -r --arg marker "${MARKER}" \
      'first(.[]? | select((.body // "") | startswith($marker)) | .id) // empty' "${work_dir}/comments.json")"
    [[ -n "${comment_id}" ]] && break
    [[ "$(jq 'length' "${work_dir}/comments.json")" -lt 100 ]] && break
  done
  if [[ "${listed}" == "true" ]]; then
    jq -n --rawfile body "${summary_path}" '{body: $body}' >"${work_dir}/comment.json"
    if [[ -n "${comment_id}" ]]; then
      method=PATCH url="${repo_api}/issues/comments/${comment_id}" expected=200 verb=updated
    else
      method=POST url="${repo_api}/issues/${pr_number}/comments" expected=201 verb=created
    fi
    status="$(github_api "${method}" "${url}" "${work_dir}/response.json" \
      -H "Content-Type: application/json" --data-binary "@${work_dir}/comment.json")"
    if [[ "${status}" == "${expected}" ]]; then
      echo "Pull request comment ${verb}"
    else
      echo "::warning title=${TITLE}::Could not write the pull request comment (HTTP ${status:-000}); the job summary is unaffected"
    fi
  fi
fi

if [[ "${gate_status}" != "0" && "${ENFORCE}" == "true" ]]; then
  exit 1
fi
