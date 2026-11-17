#!/usr/bin/env bash
# Re-merge national guides from main on every attempt; validate before push (no artifacts).
set -euo pipefail

ROOT=${1:-.}
OUTPUT=${2:-guide.xml}
MESSAGE=${3:-chore(epg): update global guide}

git config user.name "epg-bot[bot]"
git config user.email "epg-bot[bot]@users.noreply.github.com"
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN:?GITHUB_TOKEN required}@github.com/${GITHUB_REPOSITORY}.git"

merge_and_validate() {
  python3 scripts/merge-national-guides.py --root "$ROOT" --output "$OUTPUT"
  python3 - "$OUTPUT" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
programmes = root.findall('programme')
if not programmes:
    raise SystemExit('Global guide has no programmes')
print(
    f"Validated global guide: {len(root.findall('channel'))} channels, "
    f"{len(programmes)} programmes"
)
PY
}

for attempt in $(seq 1 8); do
  git fetch origin main
  git checkout -B main origin/main

  if ! merge_and_validate; then
    echo "::error::National guide validation or merge failed; refusing to publish guide.xml" >&2
    exit 1
  fi

  git add -f -- "$OUTPUT"
  if git diff --cached --quiet -- "$OUTPUT"; then
    echo "Global guide unchanged."
    exit 0
  fi

  git commit -m "$MESSAGE"
  if git push origin HEAD:refs/heads/main; then
    echo "Published global guide: $OUTPUT"
    exit 0
  fi

  echo "Push rejected (attempt ${attempt}/8); refreshing national guides and re-merging..."
done

echo "::error::Failed to publish global guide after 8 attempts" >&2
exit 1