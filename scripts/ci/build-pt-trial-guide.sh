#!/usr/bin/env bash
# Merge existing temp/pt-trial XMLTV captures into a Portuguese national guide (no re-grab).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TRIAL="$ROOT/temp/pt-trial"
OUT_DIR="$ROOT/temp"
HELPER="$ROOT/scripts/pt-epg.py"
occupied=()
for national in guide-es.xml guide-fr.xml guide-arabic.xml guide-gb.xml; do
  if [[ -f "$ROOT/guides/$national" ]]; then
    occupied+=(--occupied-guide "$ROOT/guides/$national")
  fi
done
python3 "$HELPER" merge \
  --output "$OUT_DIR/guide-pt.raw.xml" \
  --source "meo=$TRIAL/meo.pt.xml" \
  --source "nostv=$TRIAL/nostv.pt.xml" \
  --source "vodafone=$TRIAL/vodafone.pt.xml" \
  --source "tvi=$TRIAL/tvi.iol.pt.xml" \
  "${occupied[@]}"
python3 "$ROOT/scripts/build_pt_aliases.py" --guide "$OUT_DIR/guide-pt.raw.xml"
python3 "$ROOT/scripts/process-epg.py" \
  --input "$OUT_DIR/guide-pt.raw.xml" \
  --output "$OUT_DIR/guide-pt.final.xml" \
  --profile pt \
  --aliases "$ROOT/epg/aliases-pt.json" \
  --xtream-aliases "$ROOT/epg/xtream-aliases-pt.json" \
  --min-channels 80 \
  --min-programmes 800
python3 "$ROOT/scripts/build_pt_aliases.py" --guide "$OUT_DIR/guide-pt.raw.xml"
python3 "$ROOT/scripts/process-epg.py" \
  --input "$OUT_DIR/guide-pt.raw.xml" \
  --output "$OUT_DIR/guide-pt.final.xml" \
  --profile pt \
  --aliases "$ROOT/epg/aliases-pt.json" \
  --xtream-aliases "$ROOT/epg/xtream-aliases-pt.json" \
  --min-channels 80 \
  --min-programmes 800
python3 - "$OUT_DIR/guide-pt.final.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
root = ET.parse(sys.argv[1]).getroot()
channels = root.findall("channel")
programmes = root.findall("programme")
programmed = {p.get("channel") for p in programmes if (p.findtext("title") or "").strip()}
real_titles = [
    p for p in programmes
    if (p.findtext("title") or "").strip()
    and (p.findtext("title") or "").strip().casefold() not in {"sem emissão", "sem emissao"}
]
size = Path(sys.argv[1]).stat().st_size
print(
    f"guide-pt.final: channels={len(channels)} programmed={len(programmed)} "
    f"programmes={len(programmes)} real_titles={len(real_titles)} bytes={size}"
)
PY