#!/usr/bin/env python3
"""Compare XMLTV coverage before/after process-epg for one region."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "es": ("epg/aliases.json", "epg/xtream-aliases.json", "guide-es.xml"),
    "fr": ("epg/aliases-fr.json", "epg/xtream-aliases-fr.json", "guide-fr.xml"),
    "arabic": ("epg/aliases-arabic.json", "epg/xtream-aliases-arabic.json", "guide-arabic.xml"),
    "gb": ("epg/aliases-gb.json", "epg/xtream-aliases-gb.json", "guide-gb.xml"),
    "pt": ("epg/aliases-pt.json", "epg/xtream-aliases-pt.json", "guide-pt.xml"),
}


def stats(path: Path) -> dict:
    root = ET.parse(path).getroot()
    channels = root.findall("channel")
    programmed = {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip()
    }
    multi = sum(1 for c in channels if len(c.findall("display-name")) > 1)
    return {
        "channels": len(channels),
        "programmed_channels": len(programmed),
        "programmes": len(root.findall("programme")),
        "multi_display_name_channels": multi,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    aliases_rel, xtream_rel, guide_rel = PROFILES[args.profile]
    guide = ROOT / guide_rel
    if not guide.is_file():
        print(f"Missing guide: {guide}", file=sys.stderr)
        return 1
    before = stats(guide)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "process-epg.py"),
        "--input",
        str(guide),
        "--output",
        str(args.output),
        "--aliases",
        str(ROOT / aliases_rel),
        "--xtream-aliases",
        str(ROOT / xtream_rel),
        "--profile",
        args.profile,
    ]
    subprocess.run(cmd, check=True)
    after = stats(args.output)
    print(json.dumps({"before": before, "after": after}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())