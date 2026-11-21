#!/usr/bin/env python3
"""Merge independent XMLTV feeds while preserving Movistar as the authority."""

from __future__ import annotations

import argparse
import copy
import re
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from pathlib import Path

TIME_RE = re.compile(r"^(\d{14})(?:\s*([+-]\d{4}|Z))?")
SPECIAL_NAMES = {"Disney Channel": "Disney Junior"}
ORANGE_PROGRAMME_REMAP = {
    "Orange.11232": ("dazb2",),
    "Orange.11270": ("dazb3",),
    "Orange.11015": ("playdc",),
    "Orange.1054": ("chap5",),
    "Orange.1055": ("chap6",),
    "Orange.1056": ("chap7",),
    "Orange.11036": ("chap8",),
    "Orange.1096": ("chap9",),
    "Orange.1097": ("chap10",),
    "Orange.1098": ("chap11",),
    "Orange.1099": ("chap12",),
}
ORANGE_SKIP_CHANNEL_IDS = frozenset({
    "Orange.11232",
    "Orange.11270",
    "Orange.1054",
    "Orange.1055",
    "Orange.1056",
    "Orange.11036",
    "Orange.1096",
    "Orange.1097",
    "Orange.1098",
    "Orange.1099",
})
ORANGE_SUPPLEMENT_STEMS = frozenset({
    "dazb2",
    "dazb3",
    "chap5",
    "chap6",
    "chap7",
    "chap8",
    "chap9",
    "chap10",
    "chap11",
    "chap12",
})


def resolve_orange_target(channel_id: str, channels: dict[str, ET.Element]) -> str:
    stems = ORANGE_PROGRAMME_REMAP.get(channel_id)
    if not stems:
        return channel_id
    for stem in stems:
        for candidate in (f"MovistarPlus.{stem}", stem):
            if candidate in channels:
                return candidate
    return f"MovistarPlus.{stems[0]}"


def orange_shell_exists(channel_id: str, channels: dict[str, ET.Element]) -> bool:
    target = resolve_orange_target(channel_id, channels)
    return target in channels and target != channel_id


def is_orange_supplement(channel_id: str, label: str) -> bool:
    if label != "orange" or not channel_id:
        return False
    stem = channel_id.split(".", 1)[-1]
    return stem in ORANGE_SUPPLEMENT_STEMS


def load(path: Path) -> ET.Element:
    root = ET.parse(path).getroot()
    if root.tag != "tv":
        raise ValueError(f"{path}: root is not <tv>")
    return root


def interval(node: ET.Element) -> tuple[int, int] | None:
    start = TIME_RE.match(node.get("start", ""))
    stop = TIME_RE.match(node.get("stop", ""))
    if not start or not stop:
        return None
    def epoch(match):
        stamp = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        zone = match.group(2) or "+0000"
        if zone == "Z": zone = "+0000"
        return int(stamp.replace(tzinfo=timezone.utc).timestamp()) - (int(zone[1:3]) * 3600 + int(zone[3:5]) * 60) * (1 if zone[0] == "+" else -1)
    return epoch(start), epoch(stop)


def fingerprint(node: ET.Element) -> tuple:
    return (node.get("channel"), interval(node), tuple(
        (child.tag, (child.text or "").strip()) for child in node
    ))


def merge(
    primary: ET.Element,
    orange: ET.Element | None,
    elpais: ET.Element | None,
    epgshare: ET.Element | None = None,
    fast: ET.Element | None = None,
):
    result = copy.deepcopy(primary)
    channels = {node.get("id"): node for node in result.findall("channel")}
    programmes = list(result.findall("programme"))
    per_channel = {}
    for p in programmes:
        per_channel.setdefault(p.get("channel"), []).append(p)
    added_channels = {"orange": 0, "elpais": 0, "epgshare": 0, "fast": 0}
    added_programmes = {"orange": 0, "elpais": 0, "epgshare": 0, "fast": 0}
    completed = {"orange": set(), "elpais": set(), "epgshare": set(), "fast": set()}
    skipped = {"duplicate": 0, "overlap": 0, "unknown": 0}

    for label, source in (
        ("orange", orange),
        ("elpais", elpais),
        ("epgshare", epgshare),
        ("fast", fast),
    ):
        if source is None:
            print(f"WARNING: {label} feed unavailable; continuing with higher-priority feeds", file=sys.stderr)
            continue
        incoming_channels = {n.get("id"): n for n in source.findall("channel")}
        accepted_ids = set()
        if label == "orange":
            for primary_id in ("MovistarPlus.playdc", "playdc"):
                if primary_id in channels:
                    names = {n.text for n in channels[primary_id].findall("display-name")}
                    if "Disney Junior" in names and "Disney Channel" not in names:
                        ET.SubElement(channels[primary_id], "display-name").text = "Disney Channel"
        valid_incoming = {p.get("channel") for p in source.findall("programme") if interval(p)}
        for channel_id, channel in incoming_channels.items():
            if not channel_id or channel_id not in valid_incoming:
                continue
            if label == "orange" and channel_id in ORANGE_SKIP_CHANNEL_IDS and orange_shell_exists(channel_id, channels):
                continue
            if channel_id in channels:
                if channel_id in {"MovistarPlus.playdc", "playdc"} and label == "orange":
                    names = {n.text for n in channels[channel_id].findall("display-name")}
                    if "Disney Junior" in names and "Disney Channel" not in names:
                        ET.SubElement(channels[channel_id], "display-name").text = "Disney Channel"
                continue
            channels[channel_id] = copy.deepcopy(channel)
            result.append(channels[channel_id])
            accepted_ids.add(channel_id)
            added_channels[label] += 1
        for p in source.findall("programme"):
            channel_id = p.get("channel")
            if label == "orange" and channel_id in ORANGE_PROGRAMME_REMAP:
                channel_id = resolve_orange_target(channel_id, channels)
            if channel_id not in channels:
                skipped["unknown"] += 1
                continue
            # New secondary channels may be added. Existing IDs are always owned
            # by the higher-priority feed, except Orange supplements that fill
            # Movistar shells (DAZN basketball and M+ Liga de Campeones 6–13).
            supplement = is_orange_supplement(channel_id, label)
            if channel_id not in accepted_ids and not supplement:
                continue
            iv = interval(p)
            if not iv or iv[1] <= iv[0]:
                skipped["unknown"] += 1
                continue
            current = per_channel.setdefault(channel_id, [])
            fp = fingerprint(p)
            if any(fingerprint(old) == fp for old in current) or any(
                old.get("start") == p.get("start") and old.findtext("title") == p.findtext("title")
                for old in current
            ):
                skipped["duplicate"] += 1
                continue
            overlaps = False
            for old in current:
                old_iv = interval(old)
                if old_iv and iv[0] < old_iv[1] and old_iv[0] < iv[1]:
                    overlaps = True
                    break
            if overlaps:
                skipped["overlap"] += 1
                continue
            accepted = copy.deepcopy(p)
            accepted.set("channel", channel_id)
            result.append(accepted)
            current.append(p)
            added_programmes[label] += 1
            if supplement:
                completed[label].add(channel_id)
    return result, added_channels, added_programmes, completed, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--movistar", type=Path, required=True)
    ap.add_argument("--orange", type=Path)
    ap.add_argument("--elpais", type=Path)
    ap.add_argument("--epgshare", type=Path)
    ap.add_argument("--fast", type=Path, help="Pluto/Samsung/Rakuten FAST supplement (guide-es only)")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    primary = load(args.movistar)
    feeds = []
    for path in (args.orange, args.elpais, args.epgshare, args.fast):
        if not path or not path.exists() or path.stat().st_size == 0:
            feeds.append(None)
            continue
        try:
            feeds.append(load(path))
        except (OSError, ET.ParseError, ValueError) as exc:
            print(f"WARNING: ignoring invalid secondary guide {path}: {exc}", file=sys.stderr)
            feeds.append(None)
    result, ch, pg, completed, skipped = merge(primary, *feeds)
    _scripts = Path(__file__).resolve().parent
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    from xmltv_channel import normalize_channels_in_tree  # noqa: WPS433

    normalize_channels_in_tree(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(result).write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"Merged guide: channels={len(result.findall('channel'))}, programmes={len(result.findall('programme'))}")
    print(
        f"Added channels: Orange={ch['orange']}, El País={ch['elpais']}, "
        f"EPGShare={ch['epgshare']}, FAST={ch['fast']}; programmes={pg}"
    )
    print(f"Completed channels: { {k: sorted(v) for k, v in completed.items()} }; skipped={skipped}")


if __name__ == "__main__":
    main()
