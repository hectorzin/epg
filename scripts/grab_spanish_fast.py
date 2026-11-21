#!/usr/bin/env python3
"""Merge Pluto TV, Samsung TV Plus (ES) and Rakuten FAST feeds into one XMLTV guide."""
from __future__ import annotations

import argparse
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from grab_epgshare import build_guide as build_epgshare  # noqa: E402
from grab_epgshare import parse_channels_file as parse_epgshare_channels  # noqa: E402
from npm_cmd import run_npm  # noqa: E402
from xmltv_channel import normalize_channels_in_tree  # noqa: E402

_MERGE_SPEC = importlib.util.spec_from_file_location("merge_guides", _SCRIPT_DIR / "merge-guides.py")
_merge = importlib.util.module_from_spec(_MERGE_SPEC)
_MERGE_SPEC.loader.exec_module(_merge)
load_guide = _merge.load


def run_npm_grab(channels: Path, output: Path, *, site: str | None = None) -> None:
    args = ["run", "grab", "--"]
    if site:
        args.append(f"--site={site}")
    args.extend(
        [
            f"--channels={channels}",
            "--days=2",
            "--timeout=20000",
            "--maxConnections=2",
            f"--output={output}",
        ]
    )
    run_npm(args, cwd=ROOT, check=True)


def merge_fast_feeds(sources: list[Path]) -> ET.Element:
    merged = ET.Element("tv")
    seen_channels: set[str] = set()
    for path in sources:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        root = load_guide(path)
        for channel in root.findall("channel"):
            cid = channel.get("id") or ""
            if not cid or cid in seen_channels:
                continue
            seen_channels.add(cid)
            merged.append(channel)
        for programme in root.findall("programme"):
            merged.append(programme)
    normalize_channels_in_tree(merged)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pluto-channels", type=Path, default=ROOT / "epg" / "es-pluto.channels.xml")
    parser.add_argument("--samsung-channels", type=Path, default=ROOT / "epg" / "es-samsung.channels.xml")
    parser.add_argument("--rakuten-channels", type=Path, default=ROOT / "epg" / "es-rakuten.channels.xml")
    parser.add_argument("--atrescine", action="store_true", help="Include Atrescine official grid")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "temp" / "fast-grab")
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    pluto_out = args.work_dir / "pluto.xml"
    samsung_out = args.work_dir / "samsung.xml"
    rakuten_out = args.work_dir / "rakuten.xml"

    if args.pluto_channels.is_file():
        run_npm_grab(args.pluto_channels, pluto_out)
    if args.samsung_channels.is_file():
        run_npm_grab(args.samsung_channels, samsung_out)
    if args.rakuten_channels.is_file():
        selected = parse_epgshare_channels(args.rakuten_channels)
        rakuten_root = build_epgshare(selected, days=2)
        ET.ElementTree(rakuten_root).write(rakuten_out, encoding="utf-8", xml_declaration=True)

    sources = [pluto_out, samsung_out, rakuten_out]
    if args.atrescine:
        atrescine_spec = importlib.util.spec_from_file_location(
            "grab_atrescine", _SCRIPT_DIR / "grab_atrescine.py"
        )
        atrescine = importlib.util.module_from_spec(atrescine_spec)
        atrescine_spec.loader.exec_module(atrescine)
        atrescine_out = args.work_dir / "atrescine.xml"
        guide = atrescine.build_guide(atrescine.download_page(), days=2)
        ET.ElementTree(guide).write(atrescine_out, encoding="utf-8", xml_declaration=True)
        sources.append(atrescine_out)

    merged = merge_fast_feeds(sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(merged).write(args.output, encoding="utf-8", xml_declaration=True)
    print(
        f"Wrote {args.output} ({len(merged.findall('channel'))} channels, "
        f"{len(merged.findall('programme'))} programmes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())