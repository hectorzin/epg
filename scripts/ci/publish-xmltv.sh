#!/usr/bin/env bash
# Commit and push XMLTV paths already written in the repo (pull/rebase retries, no artifacts).
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: publish-xmltv.sh <commit message> <file> [file...]" >&2
  exit 2
fi

MESSAGE=$1
shift
FILES=("$@")

for file in "${FILES[@]}"; do
  if [[ ! -s "$file" ]]; then
    echo "::error::Refusing to publish missing or empty file: $file" >&2
    exit 1
  fi
done

BACKUP_DIR=$(mktemp -d)
trap 'rm -rf "$BACKUP_DIR"' EXIT
for file in "${FILES[@]}"; do
  cp -- "$file" "$BACKUP_DIR/$(basename "$file")"
done

git config user.name "epg-bot[bot]"
git config user.email "epg-bot[bot]@users.noreply.github.com"
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN:?GITHUB_TOKEN required}@github.com/${GITHUB_REPOSITORY}.git"

for attempt in $(seq 1 8); do
  git fetch origin main
  git checkout -B main origin/main

  for file in "${FILES[@]}"; do
    mkdir -p -- "$(dirname "$file")"
    cp -- "$BACKUP_DIR/$(basename "$file")" "$file"
  done

  git add -f -- "${FILES[@]}"
  if git diff --cached --quiet -- "${FILES[@]}"; then
    echo "No changes for: ${FILES[*]}"
    exit 0
  fi

  git commit -m "$MESSAGE"
  if git push origin HEAD:refs/heads/main; then
    echo "Published: ${FILES[*]}"
    exit 0
  fi

  echo "Push rejected (attempt ${attempt}/8); retrying after fetch..."
done

echo "::error::Failed to push after 8 attempts: ${FILES[*]}" >&2
exit 1