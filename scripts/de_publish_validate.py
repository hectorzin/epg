#!/usr/bin/env python3
"""Structural checks for guide-de.xml before publication. No private catalog."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from de_catalog_match import structural_problems  # noqa: E402
from xmltv_gzip import parse_xmltv  # noqa: E402


def _load_de_epg():
    spec = importlib.util.spec_from_file_location("de_epg_validate", _SCRIPT_DIR / "de-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


de_epg = _load_de_epg()

MIN_CHANNELS = 60
MIN_PROGRAMMES = 2000


def _first_names(root: ET.Element) -> dict[str, str]:
    names = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if channel_id:
            names[channel_id] = de_epg.channel_name(channel)
    return names


def _programmed_channels(root: ET.Element) -> set[str]:
    programmed = set()
    for programme in root.findall("programme"):
        title = (programme.findtext("title") or "").strip()
        if title and not de_epg.vanished_title(title):
            programmed.add(programme.get("channel") or "")
    return programmed


def missing_channel_problems(
    previous: ET.Element,
    generated: ET.Element,
    missing: set[str],
    migrations: dict[str, str] | None = None,
) -> list[str]:
    """Allow only an explicit rename onto the same station with real programmes."""
    migrations = de_epg.CANONICAL_ID_MIGRATIONS if migrations is None else migrations
    if not missing:
        return []
    previous_names = _first_names(previous)
    generated_names = _first_names(generated)
    programmed = _programmed_channels(generated)
    problems: list[str] = []
    unexplained: list[str] = []
    grouped: dict[str, list[str]] = {}
    for old_id in missing:
        destination = migrations.get(old_id)
        if destination:
            grouped.setdefault(destination, []).append(old_id)
    skipped = set()
    for destination, old_ids in sorted(grouped.items()):
        if len(old_ids) > 1:
            claimed = ", ".join(sorted(old_ids))
            problems.append(f"{destination} is claimed by {claimed}")
            skipped.update(old_ids)
    for old_id in sorted(missing):
        if old_id in skipped:
            continue
        destination = migrations.get(old_id)
        if not destination:
            unexplained.append(old_id)
            continue
        if de_epg.is_incorrect_panel_id(old_id) or de_epg.is_incorrect_panel_id(destination):
            problems.append(f"refusing to migrate incorrect id {old_id}")
            continue
        if not de_epg.is_strong_id(destination):
            problems.append(f"{old_id} does not migrate to a canonical id")
            continue
        if destination not in generated_names:
            problems.append(f"{old_id} migrates to missing channel {destination}")
            continue
        if destination not in programmed:
            problems.append(f"{destination} has no real programmes for {old_id}")
            continue
        old_name = previous_names.get(old_id, "")
        new_name = generated_names.get(destination, "")
        old_key = de_epg.identity_key(old_name)
        new_key = de_epg.identity_key(new_name)
        if not old_key[0] or old_key != new_key:
            problems.append(
                f"{old_id} ({old_name}) is not the same station as {destination} ({new_name})"
            )
    if unexplained:
        problems.append(f"previous channels missing: {', '.join(unexplained[:8])}")
    return problems


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
    if aliases.is_file():
        alias_map = json.loads(aliases.read_text(encoding="utf-8"))
        seen: dict[str, str] = {}
        for channel_id, names in alias_map.items():
            if de_epg.is_incorrect_panel_id(channel_id) or de_epg.NUMERIC_ID_RE.fullmatch(channel_id):
                problems.append(f"alias channel id is unsafe: {channel_id}")
            for name in names:
                if name in seen and seen[name] != channel_id:
                    problems.append(f"display name {name!r} is assigned to {seen[name]} and {channel_id}")
                seen[name] = channel_id
    if xtream_aliases.is_file():
        clones = json.loads(xtream_aliases.read_text(encoding="utf-8"))
        for alias_id, original_id in clones.items():
            if (
                not de_epg.ID_RE.fullmatch(alias_id)
                or de_epg.is_incorrect_panel_id(alias_id)
                or de_epg.NUMERIC_ID_RE.fullmatch(alias_id)
                or alias_id.strip().casefold() in {"", "null", "none", "undefined"}
            ):
                problems.append(f"unsafe Xtream clone id {alias_id}")
            if alias_id in channel_ids and original_id not in channel_ids:
                problems.append(f"clone {alias_id} is present but {original_id} is missing")
    if previous and previous.is_file() and previous.stat().st_size:
        previous_root = parse_xmltv(previous)
        old_ids = {channel.get("id") for channel in previous_root.findall("channel")}
        missing = {channel_id for channel_id in old_ids if channel_id and channel_id not in channel_ids}
        problems.extend(missing_channel_problems(previous_root, root, missing))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    parser.add_argument("previous", nargs="?", type=Path, default=Path("guides/guide-de.xml"))
    parser.add_argument("--aliases", type=Path, default=_ROOT / "epg" / "aliases-de.json")
    parser.add_argument("--xtream-aliases", type=Path, default=_ROOT / "epg" / "xtream-aliases-de.json")
    args = parser.parse_args()
    problems = validate(args.generated, args.previous, args.aliases, args.xtream_aliases)
    if problems:
        for problem in problems:
            print(f"DE guide rejected: {problem}", file=sys.stderr)
        return 1
    root = ET.parse(args.generated).getroot()
    print(
        f"DE guide ok: {len(root.findall('channel'))} channels, "
        f"{len(root.findall('programme'))} programmes"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"DE guide validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
