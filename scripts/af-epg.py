#!/usr/bin/env python3
"""Select African channels and merge XMLTV guides.

Priority: Canal+ Afrique, then the TMA Caraïbes feed. Stations already
programmed in another national guide keep that XMLTV id and are not grabbed
again, so the global merge does not stack a second schedule on the same
channel. A regional variant with a different schedule keeps its own id.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from es_xtream_policy import is_forbidden_channel_id  # noqa: E402
from xmltv_channel import normalize_channels_in_tree  # noqa: E402

VANISHED_TITLES = {
    "channel no longer available",
    "this channel is no longer available",
    "channel no longer exists",
}
SOURCE_PRIORITY = {
    "canalplus": 2,
    "tmacaraibes": 1,
}


def load_table(path: Path) -> tuple[list[dict], list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    stations = data.get("stations")
    unmatched = data.get("unmatched") or []
    if not isinstance(stations, list) or not stations:
        raise ValueError(f"{path}: stations must be a non-empty list")
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_panels: set[str] = set()
    seen_sources: set[tuple[str, str]] = set()
    for station in stations:
        channel_id = str(station.get("id") or "")
        names = station.get("names") or []
        panels = station.get("panel_ids") or []
        sources = station.get("sources") or []
        if not channel_id or is_forbidden_channel_id(channel_id):
            raise ValueError(f"unsafe African channel id {channel_id!r}")
        if channel_id in seen_ids:
            raise ValueError(f"duplicate African channel id {channel_id}")
        seen_ids.add(channel_id)
        if not names or any(not str(name).strip() for name in names):
            raise ValueError(f"{channel_id}: display names are required")
        for name in names:
            if name in seen_names:
                raise ValueError(f"playlist name {name!r} is assigned twice")
            seen_names.add(name)
        for panel in panels:
            if is_forbidden_channel_id(panel) or panel in seen_ids or panel in seen_panels:
                raise ValueError(f"unsafe or duplicate Xtream id {panel!r}")
            seen_panels.add(panel)
        for source in sources:
            key = (str(source.get("site") or ""), str(source.get("site_id") or ""))
            if not key[0] or not key[1] or key in seen_sources:
                raise ValueError(f"invalid source for {channel_id}: {key}")
            seen_sources.add(key)
    for row in unmatched:
        name = str(row.get("name") or "")
        if not name or name in seen_names:
            raise ValueError(f"invalid unmatched row {row!r}")
        seen_names.add(name)
    return stations, unmatched


def source_index(stations: list[dict]) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for station in stations:
        for source in station.get("sources") or []:
            index[(source["site"], source["site_id"])] = station
    return index


def allowed_ids(stations: list[dict]) -> set[str]:
    allowed = {station["id"] for station in stations}
    for station in stations:
        allowed.update(station.get("panel_ids") or [])
    return allowed


def display_aliases(stations: list[dict]) -> dict[str, list[str]]:
    return {station["id"]: list(station["names"]) for station in stations}


def vanished_title(title: str | None) -> bool:
    return (title or "").strip().casefold() in VANISHED_TITLES


def usable(programme: ET.Element) -> bool:
    title = (programme.findtext("title") or "").strip()
    return bool(
        programme.get("channel")
        and programme.get("start")
        and programme.get("stop")
        and title
        and not vanished_title(title)
    )


def parse_xmltv(path: Path) -> ET.Element:
    root = ET.parse(path).getroot()
    if root.tag != "tv":
        raise ValueError(f"{path}: expected <tv> root")
    return root


def programmed_ids(paths: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        if not path or not path.is_file() or path.stat().st_size == 0:
            continue
        for _event, elem in ET.iterparse(path, events=("end",)):
            if elem.tag == "programme" and usable(elem):
                found.add(elem.get("channel") or "")
            if elem.tag in {"programme", "channel"}:
                elem.clear()
    found.discard("")
    return found


def station_covered(station: dict, covered: set[str]) -> bool:
    if station["id"] in covered:
        return True
    return any(source["site_id"] in covered for source in station.get("sources") or [])


def channel_text(channel: ET.Element) -> str:
    for node in channel.findall("display-name"):
        text = (node.text or "").strip()
        if text:
            return text
    return "".join(channel.itertext()).strip()


def append_names(channel: ET.Element, names: list[str]) -> None:
    existing = {(node.text or "").strip() for node in channel.findall("display-name")}
    for name in names:
        if name and name not in existing:
            ET.SubElement(channel, "display-name").text = name
            existing.add(name)
    if channel.find("display-name") is None:
        ET.SubElement(channel, "display-name").text = channel.get("id") or "Channel"


def select_channels(
    catalog: Path,
    output: Path,
    stations_path: Path,
    covered_guides: list[Path],
) -> int:
    stations, _unmatched = load_table(stations_path)
    index = source_index(stations)
    covered = programmed_ids(covered_guides)
    selected = ET.Element("channels")
    seen: set[str] = set()
    count = 0
    for channel in ET.parse(catalog).getroot().findall("channel"):
        station = index.get(((channel.get("site") or ""), (channel.get("site_id") or "")))
        if station is None or station["id"] in seen or station_covered(station, covered):
            continue
        seen.add(station["id"])
        node = ET.SubElement(selected, "channel", dict(channel.attrib))
        node.text = "".join(channel.itertext()).strip()
        count += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(selected, space="  ")
    ET.ElementTree(selected).write(output, encoding="utf-8", xml_declaration=True)
    return count


def index_catalog(path: Path | None) -> dict[tuple[str, str], ET.Element]:
    indexed: dict[tuple[str, str], ET.Element] = {}
    if path is None or not path.is_file() or path.stat().st_size == 0:
        return indexed
    for channel in ET.parse(path).getroot().findall("channel"):
        site = channel.get("site") or ""
        site_id = channel.get("site_id") or ""
        xmltv_id = (channel.get("xmltv_id") or "").strip()
        if site and site_id:
            indexed[("source", f"{site}\n{site_id}")] = channel
        if site_id:
            indexed[("site_id", site_id)] = channel
        if xmltv_id:
            indexed[("xmltv", xmltv_id)] = channel
    return indexed


def match_station(
    guide_id: str,
    catalog: dict[tuple[str, str], ET.Element],
    sources: dict[tuple[str, str], dict],
) -> dict | None:
    # Channel elements with no children are falsy; do not combine the lookups with `or`.
    catalog_channel = catalog.get(("xmltv", guide_id))
    if catalog_channel is None:
        catalog_channel = catalog.get(("site_id", guide_id))
    if catalog_channel is None:
        return None
    return sources.get(((catalog_channel.get("site") or ""), (catalog_channel.get("site_id") or "")))


def read_shared(
    paths: list[Path],
    stations: list[dict],
) -> tuple[set[str], dict[str, ET.Element], dict[str, list[ET.Element]]]:
    wanted = {station["id"] for station in stations}
    wanted_programmes = {station["id"] for station in stations if station.get("panel_ids")}
    programmed: set[str] = set()
    channels: dict[str, ET.Element] = {}
    programmes: dict[str, list[ET.Element]] = defaultdict(list)
    for path in paths:
        if not path or not path.is_file() or path.stat().st_size == 0:
            continue
        root = parse_xmltv(path)
        programmed_here = {
            programme.get("channel") or ""
            for programme in root.findall("programme")
            if usable(programme)
        }
        programmed |= programmed_here
        claimed: list[str] = []
        for channel in root.findall("channel"):
            channel_id = channel.get("id") or ""
            if channel_id in wanted and channel_id not in channels and channel_id in programmed_here:
                channels[channel_id] = copy.deepcopy(channel)
                claimed.append(channel_id)
        claimed_set = set(claimed)
        for programme in root.findall("programme"):
            channel_id = programme.get("channel") or ""
            if channel_id in claimed_set and channel_id in wanted_programmes and usable(programme):
                programmes[channel_id].append(copy.deepcopy(programme))
    return programmed, channels, programmes


def fill_programmes(rows: list[dict]) -> list[ET.Element]:
    ordered = sorted(rows, key=lambda row: (-row["priority"], row["source"]))
    by_start: dict[str, ET.Element] = {}
    for row in ordered:
        for programme in row["programmes"]:
            start = programme.get("start") or ""
            if start and start not in by_start:
                by_start[start] = programme
    return [by_start[start] for start in sorted(by_start)]


def emit_programmes(result: ET.Element, programmes: list[ET.Element], channel_id: str) -> None:
    for programme in programmes:
        cloned = copy.deepcopy(programme)
        cloned.set("channel", channel_id)
        result.append(cloned)


def emit_channel(
    result: ET.Element,
    used: set[str],
    station: dict,
    template: ET.Element,
    programmes: list[ET.Element],
    *,
    programmes_on_canonical: bool,
    blocked: set[str],
) -> None:
    channel_id = station["id"]
    if channel_id in used:
        raise ValueError(f"duplicate African channel {channel_id}")
    node = copy.deepcopy(template)
    node.set("id", channel_id)
    append_names(node, station["names"])
    result.append(node)
    used.add(channel_id)
    if programmes_on_canonical:
        emit_programmes(result, programmes, channel_id)
    if not programmes:
        return
    for panel in station.get("panel_ids") or []:
        if panel in used or panel in blocked:
            raise ValueError(f"Xtream id {panel} collides with an existing channel")
        panel_node = copy.deepcopy(node)
        panel_node.set("id", panel)
        result.append(panel_node)
        used.add(panel)
        emit_programmes(result, programmes, panel)


def regroup(result: ET.Element) -> None:
    channels = list(result.findall("channel"))
    programmes = list(result.findall("programme"))
    for child in list(result):
        result.remove(child)
    programmes.sort(key=lambda programme: (programme.get("start") or "", programme.get("channel") or ""))
    for channel in channels:
        result.append(channel)
    for programme in programmes:
        result.append(programme)


def retain_previous(
    result: ET.Element,
    used: set[str],
    stations: list[dict],
    previous: list[Path],
    blocked: set[str],
) -> int:
    allowed = allowed_ids(stations)
    kept = 0
    for path in previous:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        for channel in parse_xmltv(path).findall("channel"):
            channel_id = channel.get("id") or ""
            if not channel_id or channel_id in used or channel_id not in allowed or channel_id in blocked:
                continue
            result.append(copy.deepcopy(channel))
            used.add(channel_id)
            kept += 1
    return kept


def merge_guides(
    sources: list[tuple[str, Path, Path | None]],
    stations_path: Path,
    occupied: list[Path],
    previous: list[Path],
) -> tuple[ET.Element, dict[str, int]]:
    stations, _unmatched = load_table(stations_path)
    by_id = {station["id"]: station for station in stations}
    sources_by_key = source_index(stations)
    shared_programmed, shared_channels, shared_programmes = read_shared(occupied, stations)
    groups: dict[str, list[dict]] = defaultdict(list)
    for source_name, guide_path, catalog_path in sources:
        if not guide_path.is_file() or guide_path.stat().st_size == 0:
            continue
        try:
            root = parse_xmltv(guide_path)
        except (ET.ParseError, ValueError):
            continue
        catalog = index_catalog(catalog_path)
        bucket: dict[str, list[ET.Element]] = defaultdict(list)
        for programme in root.findall("programme"):
            if usable(programme):
                bucket[programme.get("channel") or ""].append(programme)
        for channel in root.findall("channel"):
            guide_id = channel.get("id") or ""
            station = match_station(guide_id, catalog, sources_by_key)
            if station is None or station["id"] in shared_programmed:
                continue
            programmes = [programme for programme in bucket.get(guide_id, []) if usable(programme)]
            if not programmes:
                continue
            groups[station["id"]].append(
                {
                    "source": source_name,
                    "priority": SOURCE_PRIORITY.get(source_name, 0),
                    "channel": channel,
                    "programmes": programmes,
                }
            )

    result = ET.Element("tv")
    used: set[str] = set()
    grabbed = 0
    for station_id, rows in sorted(groups.items()):
        programmes = fill_programmes(rows)
        if not programmes:
            continue
        winner = max(rows, key=lambda row: (row["priority"], row["source"]))
        emit_channel(
            result,
            used,
            by_id[station_id],
            winner["channel"],
            programmes,
            programmes_on_canonical=True,
            blocked=shared_programmed,
        )
        grabbed += 1

    shared = 0
    for station in stations:
        channel_id = station["id"]
        if channel_id not in shared_programmed or channel_id in used:
            continue
        template = shared_channels.get(channel_id)
        if template is None:
            continue
        emit_channel(
            result,
            used,
            station,
            template,
            shared_programmes.get(channel_id, []),
            programmes_on_canonical=False,
            blocked=shared_programmed,
        )
        shared += 1

    retained = retain_previous(result, used, stations, previous, shared_programmed)
    if not result.findall("programme"):
        raise ValueError("no African programmes were generated")
    regroup(result)
    normalize_channels_in_tree(result)
    return result, {"grabbed": grabbed, "shared": shared, "retained": retained}


def write_merged(
    sources: list[tuple[str, Path, Path | None]],
    output: Path,
    stations_path: Path,
    occupied: list[Path],
    previous: list[Path],
) -> tuple[int, int, dict[str, int]]:
    merged, stats = merge_guides(sources, stations_path, occupied, previous)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space="  ")
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    checked = parse_xmltv(output)
    stations, _unmatched = load_table(stations_path)
    allowed = allowed_ids(stations)
    channel_ids = [channel.get("id") or "" for channel in checked.findall("channel")]
    if any(not channel_id for channel_id in channel_ids) or len(channel_ids) != len(set(channel_ids)):
        raise ValueError("merged AF guide contains empty or duplicate channel ids")
    foreign = sorted(set(channel_ids) - allowed)
    if foreign:
        raise ValueError("merged AF guide contains a channel outside the African table: " + ", ".join(foreign[:8]))
    known = set(channel_ids)
    if any(programme.get("channel") not in known for programme in checked.findall("programme")):
        raise ValueError("merged AF guide has invalid programme references")
    shared_programmed = programmed_ids(occupied)
    for programme in checked.findall("programme"):
        channel_id = programme.get("channel") or ""
        if channel_id in shared_programmed:
            raise ValueError(f"{channel_id} repeats programmes already published in another national guide")
    return len(channel_ids), len(checked.findall("programme")), stats


def parse_source(value: str) -> tuple[str, Path, Path | None]:
    name, sep, rest = value.partition("=")
    if not sep or not name:
        raise ValueError(f"invalid --source value: {value}")
    if "," in rest:
        guide, catalog = rest.split(",", 1)
        return name, Path(guide), Path(catalog) if catalog else None
    return name, Path(rest), None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select")
    select.add_argument("--catalog", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("--stations", type=Path, required=True)
    select.add_argument("--covered-guide", action="append", type=Path, default=[])
    merge = sub.add_parser("merge")
    merge.add_argument("--stations", type=Path, required=True)
    merge.add_argument("--source", action="append", required=True, metavar="NAME=GUIDE[,CATALOG]")
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--occupied-guide", action="append", type=Path, default=[])
    merge.add_argument("--canonical-guide", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command == "select":
        print(
            select_channels(
                args.catalog,
                args.output,
                args.stations,
                args.covered_guide,
            )
        )
        return 0
    sources = [parse_source(value) for value in args.source]
    previous = [path for path in args.canonical_guide if path.is_file()]
    channels, programmes, stats = write_merged(
        sources,
        args.output,
        args.stations,
        args.occupied_guide,
        previous,
    )
    print(
        f"African guide: {channels} channels, {programmes} programmes; "
        f"grabbed {stats['grabbed']}; shared {stats['shared']}; retained {stats['retained']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"African EPG failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
