#!/usr/bin/env bash
set -euo pipefail

GH_BIN="${GH_BIN:-/usr/bin/gh}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

if ! RUNS_JSON="$(
  "$GH_BIN" api --paginate \
    "/repos/$GITHUB_REPOSITORY/actions/workflows/evidence-campaign-v4-scheduled.yml/runs?per_page=100"
)"; then
  echo "unable to query V4 workflow metadata" >&2
  exit 79
fi

RUN_ROWS="$(
  printf '%s' "$RUNS_JSON" \
    | /usr/bin/jq -r '
        .workflow_runs[]
        | select(.head_branch == "main")
        | select(.event == "schedule" or .event == "workflow_dispatch")
        | select(.status != "completed")
        | [.id, (.run_attempt // 1), .status, .event, .created_at]
        | @tsv
      '
)"

while IFS=$'\t' read -r RUN_ID RUN_ATTEMPT RUN_STATUS RUN_EVENT CREATED_AT; do
  if [ -z "$RUN_ID" ]; then
    continue
  fi
  if ! JOBS_JSON="$(
    "$GH_BIN" api \
      "/repos/$GITHUB_REPOSITORY/actions/runs/$RUN_ID/attempts/$RUN_ATTEMPT/jobs?per_page=100"
  )"; then
    echo "unable to query V4 acquisition job metadata for run $RUN_ID" >&2
    exit 79
  fi
  ACQUIRE_COUNT="$(
    printf '%s' "$JOBS_JSON" \
      | /usr/bin/jq '[.jobs[] | select(.name == "acquire-evidence")] | length'
  )"
  if [ "$ACQUIRE_COUNT" -ne 1 ]; then
    printf '%s\t%s\t%s\t%s\tambiguous_acquire_job\n' \
      "$RUN_ID" "$RUN_STATUS" "$RUN_EVENT" "$CREATED_AT"
    continue
  fi
  ACQUIRE_STATUS="$(
    printf '%s' "$JOBS_JSON" \
      | /usr/bin/jq -r '.jobs[] | select(.name == "acquire-evidence") | .status'
  )"
  if [ "$ACQUIRE_STATUS" != "completed" ]; then
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "$RUN_ID" "$RUN_STATUS" "$RUN_EVENT" "$CREATED_AT" "$ACQUIRE_STATUS"
  fi
done <<< "$RUN_ROWS"
