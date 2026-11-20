#!/usr/bin/env bash
# Merge existing temp/nl-trial XMLTV captures into a Dutch national guide (no re-grab).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/temp}"
TRIAL="$ROOT/temp/nl-trial"
UP_ZIGGO="$ROOT/temp/iptv-org-epg-uk/sites/ziggogo.tv/ziggogo.tv.channels.xml"
UP_DELTA="$ROOT/temp/iptv-org-epg-uk/sites/webtv.delta.nl/webtv.delta.nl.channels.xml"
UP_TVGIDS="$ROOT/temp/iptv-org-epg-uk/sites/tvgids.nl/tvgids.nl.channels.xml"
occupied=()
for national in guide-es.xml guide-fr.xml guide-arabic.xml guide-gb.xml guide-pt.xml; do
  if [[ -f "$ROOT/guides/$national" ]]; then
    occupied+=(--occupied-guide "$ROOT/guides/$national")
  fi
done
python3 "$ROOT/scripts/nl-epg.py" merge \
  --output "$OUT_DIR/guide-nl.raw.xml" \
  --source "ziggo=$TRIAL/ziggo.xml,$UP_ZIGGO" \
  --source "delta=$TRIAL/delta.xml,$UP_DELTA" \
  --source "tvgids=$TRIAL/tvgids.xml,$UP_TVGIDS" \
  "${occupied[@]}"
python3 "$ROOT/scripts/build_nl_aliases.py" --guide "$OUT_DIR/guide-nl.raw.xml" \
  --aliases-out "$ROOT/epg/aliases-nl.json" \
  --clones-out "$ROOT/epg/xtream-aliases-nl.json"
python3 "$ROOT/scripts/process-epg.py" \
  --input "$OUT_DIR/guide-nl.raw.xml" \
  --output "$OUT_DIR/guide-nl.final.xml" \
  --profile nl \
  --aliases "$ROOT/epg/aliases-nl.json" \
  --xtream-aliases "$ROOT/epg/xtream-aliases-nl.json" \
  --min-channels 120 \
  --min-programmes 8000
python3 "$ROOT/scripts/build_nl_aliases.py" --guide "$OUT_DIR/guide-nl.final.xml"
python3 "$ROOT/scripts/nl_publish_validate.py" "$OUT_DIR/guide-nl.final.xml" --skip-real-coverage
python3 - "$OUT_DIR/guide-nl.final.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
programmed = {
    p.get("channel")
    for p in root.findall("programme")
    if (p.findtext("title") or "").strip()
}
channels = {c.get("id") for c in root.findall("channel")}
print(f"guide-nl.final: channels={len(channels)} programmed={len(programmed)} programmes={len(root.findall('programme'))}")
PY