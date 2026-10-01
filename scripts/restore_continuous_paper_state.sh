#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <artifact-id> <source-head-sha> <state-root>" >&2
  exit 2
fi

artifact_id="$1"
source_head_sha="$2"
state_root="$3"

if [[ ! "$artifact_id" =~ ^[0-9]+$ ]]; then
  echo "artifact id must be numeric" >&2
  exit 2
fi
if [[ ! "$source_head_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "source head sha must be a 40-character lowercase hex sha" >&2
  exit 2
fi
if [ -z "${GITHUB_REPOSITORY:-}" ]; then
  echo "GITHUB_REPOSITORY is required" >&2
  exit 2
fi
command -v gh >/dev/null
command -v tar >/dev/null

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

workflow_source="$tmp_root/source-workflow.yml"
gh api \
  "repos/$GITHUB_REPOSITORY/contents/.github/workflows/continuous-paper.yml?ref=$source_head_sha" \
  --jq '.content' \
  | base64 --decode > "$workflow_source"

restore_attempts="${COCOMELON_STATE_RESTORE_ATTEMPTS:-3}"
restore_retry_sleep_seconds="${COCOMELON_STATE_RESTORE_RETRY_SLEEP_SECONDS:-5}"
if [[ ! "$restore_attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "COCOMELON_STATE_RESTORE_ATTEMPTS must be a positive integer" >&2
  exit 2
fi
if [[ ! "$restore_retry_sleep_seconds" =~ ^[0-9]+$ ]]; then
  echo "COCOMELON_STATE_RESTORE_RETRY_SLEEP_SECONDS must be a non-negative integer" >&2
  exit 2
fi

rm -rf "$state_root"
mkdir -p "$state_root"

if grep -Fq -- "- name: Pack durable continuous paper state" "$workflow_source"; then
  restored=false
  for attempt in $(seq 1 "$restore_attempts"); do
    rm -rf "$state_root"
    mkdir -p "$state_root"
    echo "::notice::streaming packed continuous-paper artifact $artifact_id (attempt $attempt/$restore_attempts)"
    if gh api \
      "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" \
      | python scripts/stream_zip_member.py continuous-paper-state.tar \
      | tar -xf - -C "$state_root"; then
      restored=true
      break
    fi
    echo "::warning::packed continuous-paper restore attempt $attempt failed; discarding partial state"
    rm -rf "$state_root"
    mkdir -p "$state_root"
    if [ "$attempt" -lt "$restore_attempts" ] && [ "$restore_retry_sleep_seconds" -gt 0 ]; then
      sleep "$restore_retry_sleep_seconds"
    fi
  done
  if [ "$restored" != "true" ]; then
    echo "packed continuous-paper restore failed after $restore_attempts attempts" >&2
    exit 1
  fi
else
  command -v unzip >/dev/null
  artifact_root="$tmp_root/artifact"
  mkdir -p "$artifact_root"
  echo "::notice::restoring legacy multi-file continuous-paper artifact $artifact_id"
  gh api \
    "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" \
    > "$tmp_root/state.zip"
  unzip -q "$tmp_root/state.zip" -d "$artifact_root"
  cp -a "$artifact_root"/. "$state_root"/
fi

if ! find "$state_root" -mindepth 1 -print -quit | grep -q .; then
  echo "restored continuous-paper state is empty" >&2
  exit 1
fi
