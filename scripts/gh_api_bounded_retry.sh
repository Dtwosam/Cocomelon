#!/usr/bin/env bash
# Fetch GitHub API evidence with finite retries for transient service errors.
# Emit only a complete successful response: never concatenate failed JSON/ZIP bytes.
# Exhaustion and permanent errors remain failures; never silently reset a ledger.
gh_api_bounded_retry() {
  local attempt=1
  local max_attempts=4
  local response_file error_file output_status
  response_file="$(mktemp)" || return 1
  error_file="$(mktemp)" || { rm -f "$response_file"; return 1; }

  while (( attempt <= max_attempts )); do
    if gh api "$@" >"$response_file" 2>"$error_file"; then
      cat "$response_file"
      output_status=$?
      rm -f "$response_file" "$error_file"
      return "$output_status"
    fi

    if (( attempt == max_attempts )) || \
       ! grep -Eq 'HTTP (429|500|502|503|504)([^[:digit:]]|$)' "$error_file"; then
      cat "$error_file" >&2
      rm -f "$response_file" "$error_file"
      return 1
    fi

    printf 'Transient GitHub API failure (attempt %s/%s); retrying.\n' \
      "$attempt" "$max_attempts" >&2
    sleep "$attempt"
    attempt=$(( attempt + 1 ))
  done
  rm -f "$response_file" "$error_file"
  return 1
}
