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


def merge(primary: ET.Element, orange: ET.Element | None, elpais: ET.Element | None):
    result = copy.deepcopy(primary)
    channels = {node.get("id"): node for node in result.findall("channel")}
    programmes = list(result.findall("programme"))
    per_channel = {}
    for p in programmes:
        per_channel.setdefault(p.get("channel"), []).append(p)
    added_channels = {"orange": 0, "elpais": 0}
    added_programmes = {"orange": 0, "elpais": 0}
    completed = {"orange": set(), "elpais": set()}
    skipped = {"duplicate": 0, "overlap": 0, "unknown": 0}

    for label, source in (("orange", orange), ("elpais", elpais)):
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
            if not channel_id or channel_id not in valid_incoming or channel_id in {"Orange.11232", "Orange.11270"}:
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
            if label == "orange" and channel_id in {"Orange.11232", "Orange.11270"}:
                target = "dazb2" if channel_id.endswith("11232") else "dazb3"
                channel_id = next((candidate for candidate in (f"MovistarPlus.{target}", target)
                                   if candidate in channels), f"MovistarPlus.{target}")
            if label == "orange" and channel_id == "Orange.11015":
                channel_id = next((candidate for candidate in ("MovistarPlus.playdc", "playdc")
                                   if candidate in channels), "MovistarPlus.playdc")
            if channel_id not in channels:
                skipped["unknown"] += 1
                continue
            # New secondary channels may be added. Existing IDs are always owned
            # by the higher-priority feed, except the two specifically requested completions.
            supplement = channel_id in {"MovistarPlus.dazb2", "MovistarPlus.dazb3", "dazb2", "dazb3"} and label == "orange"
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
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    primary = load(args.movistar)
    feeds = []
    for path in (args.orange, args.elpais):
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
    print(f"Added channels: Orange={ch['orange']}, El País={ch['elpais']}; programmes={pg}")
    print(f"Completed channels: { {k: sorted(v) for k, v in completed.items()} }; skipped={skipped}")


if __name__ == "__main__":
    main()
