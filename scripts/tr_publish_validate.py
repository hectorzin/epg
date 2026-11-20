#!/usr/bin/env python3
"""Structural checks for guide-tr.xml before publication. No private catalog."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from tr_catalog_match import structural_problems  # noqa: E402


def _load_tr_epg():
    spec = importlib.util.spec_from_file_location("tr_epg_validate", _SCRIPT_DIR / "tr-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tr_epg = _load_tr_epg()

MIN_CHANNELS = 70
MIN_PROGRAMMES = 1500
ISTANBUL = timezone(timedelta(hours=3))


def _parse_start(value: str) -> datetime | None:
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


def validate(generated: Path, previous: Path | None, aliases: Path, xtream_aliases: Path) -> list[str]:
    problems: list[str] = []
    root = ET.parse(generated).getroot()
    if root.tag != "tv":
        return [f"{generated}: expected <tv> root"]
    problems.extend(structural_problems(root))
    channel_ids = {channel.get("id") for channel in root.findall("channel")}
    programmes = [
        programme
        for programme in root.findall("programme")
        if (programme.findtext("title") or "").strip()
    ]
    if len(channel_ids) < MIN_CHANNELS:
        problems.append(f"only {len(channel_ids)} channels (minimum {MIN_CHANNELS})")
    if len(programmes) < MIN_PROGRAMMES:
        problems.append(f"only {len(programmes)} programmes (minimum {MIN_PROGRAMMES})")
    now = datetime.now(ISTANBUL)
    window_start = now - timedelta(days=1)
    window_end = now + timedelta(days=2)
    current = 0
    for programme in programmes:
        stamp = _parse_start(programme.get("start") or "")
        if stamp is not None and window_start <= stamp.astimezone(ISTANBUL) <= window_end:
            current += 1
    if current < MIN_PROGRAMMES:
        problems.append(f"only {current} programmes fall on the current Istanbul window")
    if aliases.is_file():
        alias_map = json.loads(aliases.read_text(encoding="utf-8"))
        seen: dict[str, str] = {}
        for channel_id, names in alias_map.items():
            if not tr_epg.is_published_id(channel_id):
                problems.append(f"alias channel id is unsafe: {channel_id}")
            for name in names:
                if name in seen and seen[name] != channel_id:
                    problems.append(f"display name {name!r} is assigned to {seen[name]} and {channel_id}")
                seen[name] = channel_id
    if xtream_aliases.is_file():
        clones = json.loads(xtream_aliases.read_text(encoding="utf-8"))
        for alias_id, original_id in clones.items():
            if (
                alias_id.strip().casefold() in {"", "null", "none", "undefined"}
                or alias_id.isdigit()
                or not tr_epg.ID_RE.fullmatch(alias_id)
            ):
                problems.append(f"unsafe Xtream clone id {alias_id}")
            if alias_id in channel_ids and original_id not in channel_ids:
                problems.append(f"clone {alias_id} is present but {original_id} is missing")
    if previous and previous.is_file() and previous.stat().st_size:
        previous_root = ET.parse(previous).getroot()
        old_ids = {channel.get("id") for channel in previous_root.findall("channel")}
        missing = sorted(channel_id for channel_id in old_ids if channel_id and channel_id not in channel_ids)
        if missing:
            problems.append(f"previous channels missing: {', '.join(missing[:8])}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    parser.add_argument("previous", nargs="?", type=Path, default=Path("guide-tr.xml"))
    parser.add_argument("--aliases", type=Path, default=_ROOT / "epg" / "aliases-tr.json")
    parser.add_argument("--xtream-aliases", type=Path, default=_ROOT / "epg" / "xtream-aliases-tr.json")
    args = parser.parse_args()
    problems = validate(args.generated, args.previous, args.aliases, args.xtream_aliases)
    if problems:
        for problem in problems:
            print(f"TR guide rejected: {problem}", file=sys.stderr)
        return 1
    root = ET.parse(args.generated).getroot()
    print(
        f"TR guide ok: {len(root.findall('channel'))} channels, "
        f"{len(root.findall('programme'))} programmes"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"TR guide validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
