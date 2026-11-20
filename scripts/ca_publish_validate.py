#!/usr/bin/env python3
"""Structural checks for guide-ca.xml before publication. No private catalog."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from guide_layout import national_guide_dir  # noqa: E402
from xmltv_gzip import parse_xmltv  # noqa: E402


def _load_ca_epg():
    spec = importlib.util.spec_from_file_location("ca_epg_validate", _SCRIPT_DIR / "ca-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ca_epg = _load_ca_epg()

MIN_CHANNELS = 80
MIN_PROGRAMMES = 1000
NATIONAL_GUIDE = re.compile(r"^(?:guide-[a-z]{2}|guide-arabic)\.xml$", re.IGNORECASE)


def programme_counts(root: ET.Element) -> Counter:
    counts: Counter = Counter()
    for programme in root.findall("programme"):
        if ca_epg.usable(programme):
            counts[programme.get("channel") or ""] += 1
    return counts


def parse_start(value: str) -> datetime | None:
    raw = (value or "").strip()
    if len(raw) < 14 or not raw[:14].isdigit():
        return None
    when = datetime.strptime(raw[:14], "%Y%m%d%H%M%S")
    tail = raw[14:].strip()
    if len(tail) >= 5 and tail[0] in "+-" and tail[1:3].isdigit():
        sign = 1 if tail[0] == "+" else -1
        hours = int(tail[1:3])
        minutes = int(tail[3:5]) if len(tail) >= 5 else 0
        return when.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
    return when.replace(tzinfo=timezone.utc)


def occupied_guides(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    search = national_guide_dir(root)
    return sorted(
        path
        for path in search.glob("guide-*.xml")
        if NATIONAL_GUIDE.match(path.name) and path.name != "guide-ca.xml" and path.stat().st_size > 0
    )


def validate(
    generated: Path,
    previous: Path | None,
    stations_path: Path,
    aliases_path: Path,
    xtream_path: Path,
    occupied_root: Path,
) -> list[str]:
    problems: list[str] = []
    stations, unmatched = ca_epg.load_table(stations_path)
    root = ET.parse(generated).getroot()
    if root.tag != "tv":
        return [f"{generated}: expected <tv> root"]
    channel_ids = [channel.get("id") or "" for channel in root.findall("channel")]
    known = set(channel_ids)
    if any(not channel_id for channel_id in channel_ids) or len(channel_ids) != len(known):
        problems.append("duplicate or empty channel ids")
    programmes = [programme for programme in root.findall("programme") if ca_epg.usable(programme)]
    invalid = [
        programme
        for programme in root.findall("programme")
        if not programme.get("start") or not programme.get("stop") or programme.get("channel") not in known
    ]
    if invalid:
        problems.append(f"{len(invalid)} programmes have an invalid channel reference")
    foreign = sorted(known - ca_epg.allowed_ids(stations))
    if foreign:
        problems.append("channel outside the Canadian table: " + ", ".join(foreign[:8]))
    if len(known) < MIN_CHANNELS:
        problems.append(f"only {len(known)} channels (minimum {MIN_CHANNELS})")
    if len(programmes) < MIN_PROGRAMMES:
        problems.append(f"only {len(programmes)} programmes (minimum {MIN_PROGRAMMES})")
    now = datetime.now(timezone.utc)
    current = 0
    for programme in programmes:
        stamp = parse_start(programme.get("start") or "")
        if stamp is not None and now - timedelta(days=1) <= stamp.astimezone(timezone.utc) <= now + timedelta(days=3):
            current += 1
    if current < MIN_PROGRAMMES:
        problems.append(f"only {current} programmes fall on the current window")

    counts = programme_counts(root)
    occupied = ca_epg.programmed_ids(occupied_guides(occupied_root))
    for channel_id, count in counts.items():
        if channel_id in occupied and count:
            problems.append(f"{channel_id} duplicates programmes already published in another national guide")
    for station in stations:
        channel_id = station["id"]
        panels = list(station.get("panel_ids") or [])
        if channel_id in occupied:
            if channel_id not in known:
                problems.append(f"shared station missing from the Canadian guide: {channel_id}")
            for panel in panels:
                if counts[panel] == 0:
                    problems.append(f"Xtream id {panel} has no programmes")
            continue
        if channel_id in known:
            for panel in panels:
                if panel not in known:
                    problems.append(f"missing Xtream id {panel}")
                elif counts[panel] != counts[channel_id]:
                    problems.append(f"{panel} programme count does not match {channel_id}")
        elif station.get("required"):
            problems.append(f"missing programmes for {channel_id}")

    expected = ca_epg.display_aliases(stations)
    if aliases_path.is_file():
        aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
        if aliases != expected:
            problems.append("aliases-ca.json does not match ca-stations.json")
        seen: dict[str, str] = {}
        for channel_id, names in aliases.items():
            for name in names:
                if name in seen and seen[name] != channel_id:
                    problems.append(f"display name {name!r} is assigned to {seen[name]} and {channel_id}")
                seen[name] = channel_id
        for row in unmatched:
            if row["name"] in seen:
                problems.append(f"unmatched playlist name was aliased: {row['name']}")
    if xtream_path.is_file():
        clones = json.loads(xtream_path.read_text(encoding="utf-8"))
        for alias_id, original_id in clones.items():
            if original_id not in known or alias_id not in known:
                problems.append(f"Xtream clone {alias_id} -> {original_id} is not in the guide")
            if counts[alias_id] != counts[original_id]:
                problems.append(f"Xtream clone {alias_id} does not repeat {original_id}")
    if previous and previous.is_file() and previous.stat().st_size and previous.resolve() != generated.resolve():
        previous_root = parse_xmltv(previous)
        old_ids = {channel.get("id") for channel in previous_root.findall("channel") if channel.get("id")}
        missing = sorted(channel_id for channel_id in old_ids if channel_id not in known)
        if missing:
            problems.append("previous channels missing: " + ", ".join(missing[:8]))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    parser.add_argument("previous", nargs="?", type=Path, default=Path("guides/guide-ca.xml"))
    parser.add_argument("--stations", type=Path, default=_ROOT / "epg" / "ca-stations.json")
    parser.add_argument("--aliases", type=Path, default=_ROOT / "epg" / "aliases-ca.json")
    parser.add_argument("--xtream-aliases", type=Path, default=_ROOT / "epg" / "xtream-aliases-ca.json")
    parser.add_argument("--occupied-root", type=Path, default=_ROOT)
    args = parser.parse_args()
    problems = validate(
        args.generated,
        args.previous,
        args.stations,
        args.aliases,
        args.xtream_aliases,
        args.occupied_root,
    )
    if problems:
        for problem in problems:
            print(f"CA guide rejected: {problem}", file=sys.stderr)
        return 1
    root = ET.parse(args.generated).getroot()
    print(
        f"CA guide ok: {len(root.findall('channel'))} channels, "
        f"{len(root.findall('programme'))} programmes"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"CA guide validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
