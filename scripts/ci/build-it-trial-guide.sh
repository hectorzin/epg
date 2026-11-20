#!/usr/bin/env bash
# Merge temp/it-trial XMLTV captures into an Italian national guide (no re-grab).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/temp}"
TRIAL="$ROOT/temp/it-trial"
UP_SKY="$ROOT/temp/it-trial/upstream/sites/guidatv.sky.it/guidatv.sky.it.channels.xml"
UP_MED="$ROOT/temp/it-trial/upstream/sites/mediasetinfinity.mediaset.it/mediasetinfinity.mediaset.it.channels.xml"
UP_RAI="$ROOT/temp/it-trial/upstream/sites/raiplay.it/raiplay.it.channels.xml"
UP_TIVU="$ROOT/temp/it-trial/upstream/sites/tivu.tv/tivu.tv.channels.xml"
occupied=()
for national in guide-es.xml guide-fr.xml guide-arabic.xml guide-gb.xml guide-pt.xml guide-nl.xml; do
  if [[ -f "$ROOT/guides/$national" ]]; then
    occupied+=(--occupied-guide "$ROOT/guides/$national")
  fi
done
python3 "$ROOT/scripts/it-epg.py" merge \
  --output "$OUT_DIR/guide-it.raw.xml" \
  --source "sky=$TRIAL/sky-guida.xml,$UP_SKY" \
  --source "mediaset=$TRIAL/mediaset.xml,$UP_MED" \
  --source "rai=$TRIAL/raiplay.xml,$UP_RAI" \
  --source "tivu=$TRIAL/tivu.xml,$UP_TIVU" \
  "${occupied[@]}"
python3 "$ROOT/scripts/process-epg.py" \
  --input "$OUT_DIR/guide-it.raw.xml" \
  --output "$OUT_DIR/guide-it.final.xml" \
  --profile it \
  --aliases "$ROOT/epg/aliases-it.json" \
  --xtream-aliases "$ROOT/epg/xtream-aliases-it.json" \
  --min-channels 80 \
  --min-programmes 5000
python3 "$ROOT/scripts/it_publish_validate.py" "$OUT_DIR/guide-it.final.xml" --skip-coverage
python3 "$ROOT/scripts/it_catalog_match.py" "$OUT_DIR/guide-it.final.xml"