#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo "usage: $0 <artifact-id> <source-head-sha> <state-root> [member-name]" >&2
  exit 2
fi

artifact_id="$1"
source_head_sha="$2"
state_root="$3"
member_name="${4:-}"

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

restore_stream_with_retries() {
  local mode="$1"
  local member="$2"
  local attempt
  for attempt in 1 2 3; do
    rm -rf "$state_root"
    mkdir -p "$state_root"
    echo "::notice::continuous-paper restore attempt $attempt/3 via $mode"
    if [ "$mode" = "zstd" ]; then
      if gh api \
        "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" \
        | python scripts/stream_zip_member.py "$member" \
        | zstd -d -c --no-progress \
        | tar -xf - -C "$state_root"; then
        return 0
      fi
    elif gh api \
      "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" \
      | python scripts/stream_zip_member.py "$member" \
      | tar -xf - -C "$state_root"; then
      return 0
    fi
    rm -rf "$state_root"
    if [ "$attempt" -lt 3 ]; then
      echo "::warning::continuous-paper restore attempt $attempt failed; retrying"
      sleep 5
    fi
  done
  echo "continuous-paper packed restore failed after 3 attempts" >&2
  return 1
}

rm -rf "$state_root"
mkdir -p "$state_root"

if [ "$member_name" = "continuous-paper-resume.tar.zst" ]; then
  command -v zstd >/dev/null
  echo "::notice::streaming fast continuous-paper resume artifact $artifact_id"
  restore_stream_with_retries "zstd" "$member_name"
elif [ -n "$member_name" ]; then
  echo "unsupported packed state member: $member_name" >&2
  exit 2
elif grep -Fq -- "- name: Pack durable continuous paper state" "$workflow_source"; then
  echo "::notice::streaming packed continuous-paper artifact $artifact_id"
  restore_stream_with_retries "tar" "continuous-paper-state.tar"
else
  command -v unzip >/dev/null
  artifact_root="$tmp_root/artifact"
  mkdir -p "$artifact_root"
  echo "::notice::restoring legacy multi-file continuous-paper artifact $artifact_id"
  for attempt in 1 2 3; do
    if gh api \
      "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" \
      > "$tmp_root/state.zip"; then
      break
    fi
    rm -f "$tmp_root/state.zip"
    if [ "$attempt" -eq 3 ]; then
      echo "legacy continuous-paper restore download failed after 3 attempts" >&2
      exit 1
    fi
    echo "::warning::legacy continuous-paper restore attempt $attempt failed; retrying"
    sleep 5
  done
  unzip -q "$tmp_root/state.zip" -d "$artifact_root"
  cp -a "$artifact_root"/. "$state_root"/
fi

if ! find "$state_root" -mindepth 1 -print -quit | grep -q .; then
  echo "restored continuous-paper state is empty" >&2
  exit 1
fi
