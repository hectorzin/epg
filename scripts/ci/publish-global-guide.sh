#!/usr/bin/env bash
# Re-merge national guides from main on every attempt; validate before push (no artifacts).
# National guides stay plain XML. The global guide is merged to a temporary XML file,
# validated, packed as guide.xml.gz (level 9, mtime 0) and published without guide.xml.
set -euo pipefail

ROOT=${1:-.}
REQUESTED=${2:-guide.xml.gz}
MESSAGE=${3:-chore(epg): update global guide}
REQUESTED_NAME=$(basename "$REQUESTED")
if [[ "$REQUESTED_NAME" != "guide.xml.gz" && "$REQUESTED_NAME" != "guide.xml" ]]; then
  echo "::error::Global guide must be published as guide.xml.gz" >&2
  exit 2
fi
PUBLISHED="$ROOT/guide.xml.gz"
LEGACY="$ROOT/guide.xml"
TMP_XML=""

cleanup() {
  if [[ -n "$TMP_XML" ]]; then
    rm -f -- "$TMP_XML"
  fi
}
trap cleanup EXIT

git config user.name "epg-bot[bot]"
git config user.email "epg-bot[bot]@users.noreply.github.com"
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN:?GITHUB_TOKEN required}@github.com/${GITHUB_REPOSITORY}.git"

merge_and_validate() {
  if [[ -n "$TMP_XML" ]]; then
    rm -f -- "$TMP_XML"
  fi
  TMP_XML=$(mktemp)
  python3 scripts/merge-national-guides.py --root "$ROOT" --output "$TMP_XML"
  python3 scripts/xmltv_gzip.py validate "$TMP_XML"
  python3 scripts/xmltv_gzip.py pack "$TMP_XML" "$PUBLISHED"
}

for attempt in $(seq 1 8); do
  git fetch origin main
  git checkout -B main origin/main

  if ! merge_and_validate; then
    echo "::error::National guide validation or merge failed; refusing to publish guide.xml.gz" >&2
    exit 1
  fi

  if git ls-files --error-unmatch -- guide.xml >/dev/null 2>&1; then
    git rm -f -- guide.xml
  fi
  if [[ -f "$LEGACY" && "$LEGACY" != "$PUBLISHED" ]]; then
    rm -f -- "$LEGACY"
  fi
  git add -f -- "$PUBLISHED"
  if git diff --cached --quiet -- guide.xml "$PUBLISHED"; then
    echo "Global guide unchanged."
    exit 0
  fi

  git commit -m "$MESSAGE"
  if git push origin HEAD:refs/heads/main; then
    echo "Published global guide: $PUBLISHED"
    exit 0
  fi

  echo "Push rejected (attempt ${attempt}/8); refreshing national guides and re-merging..."
done

echo "::error::Failed to publish global guide after 8 attempts" >&2
exit 1
