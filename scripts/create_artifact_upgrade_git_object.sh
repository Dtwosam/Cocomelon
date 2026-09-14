#!/usr/bin/env bash
set -euo pipefail

mapfile -t changed < <(git diff --name-only HEAD^ HEAD)
: > /tmp/artifact-upgrade-tree.jsonl
for path in "${changed[@]}"; do
  if [[ "$path" == ".github/workflows/_artifact_action_upgrade_patch.yml" ]]; then
    continue
  fi
  content="$(base64 -w0 "$path")"
  blob_sha="$(jq -n --arg content "$content" '{content:$content,encoding:"base64"}' | gh api --method POST "/repos/$GITHUB_REPOSITORY/git/blobs" --input - --jq .sha)"
  jq -n --arg path "$path" --arg sha "$blob_sha" '{path:$path,mode:"100644",type:"blob",sha:$sha}' >> /tmp/artifact-upgrade-tree.jsonl
done
base_tree="$(git rev-parse 'HEAD^^{tree}')"
tree_sha="$(jq -s --arg base_tree "$base_tree" '{base_tree:$base_tree,tree:.}' /tmp/artifact-upgrade-tree.jsonl | gh api --method POST "/repos/$GITHUB_REPOSITORY/git/trees" --input - --jq .sha)"
parent="$(git rev-parse HEAD^^)"
commit_sha="$(jq -n --arg message 'ci: upgrade artifact action runtime majors' --arg tree "$tree_sha" --arg parent "$parent" '{message:$message,tree:$tree,parents:[$parent]}' | gh api --method POST "/repos/$GITHUB_REPOSITORY/git/commits" --input - --jq .sha)"
printf 'REMOTE_PATCH_COMMIT_SHA=%s\n' "$commit_sha"
