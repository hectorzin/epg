#!/usr/bin/env python3
"""Select Italian channels and merge XMLTV (Sky > Mediaset > Rai > tivu)."""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from es_xtream_policy import denied_xtream_clone_ids, is_forbidden_channel_id  # noqa: E402

VANISHED_TITLES = {
    "channel no longer available",
    "this channel is no longer available",
    "channel no longer exists",
}
PLUS1_RE = re.compile(r"(?:\+\s*1|plus\s*1)", re.IGNORECASE)
PLUS24_RE = re.compile(r"(?:\+\s*24|plus\s*24)", re.IGNORECASE)
TIMESHIFT_RE = re.compile(r"\+\s*(\d+)\b")
HD_RE = re.compile(r"\b(uhd|4k|fhd|full\s*hd|\bhd\b)", re.IGNORECASE)
TECHNICAL_RE = re.compile(
    r"(?:[\s._()\[\]-]*)(?:FULL[\s._-]*HD|FHD|UHD|HD|SD|4K|HEVC|H265|H264)[\s)\]]*$",
    re.IGNORECASE,
)
WEAK_ID_RE = re.compile(r"^(?:[0-9]+$|[a-z0-9]+(?:-[a-z0-9]+)+)$")
NUMERIC_ID_RE = re.compile(r"^[0-9]+$")
ID_RE = re.compile(r"^[^\s<>\"']+$")
IT_PREFIX = re.compile(r"^\s*(?:\[IT\]|IT)\s*[:|/_-]?\s*", re.IGNORECASE)
SOURCE_PRIORITY = {"sky": 4, "mediaset": 3, "rai": 2, "tivu": 1}
COLLISION_FEED = "Italy"
DAZN_RE = re.compile(r"\bdazn\s*a?\s*(\d+)\b", re.IGNORECASE)
SKY_SPORT_NUM_RE = re.compile(r"\bsky\s*sport\s*(\d+)\b", re.IGNORECASE)
SKY_SPORT_UNO_RE = re.compile(r"\bsky\s*sport\s*uno\b", re.IGNORECASE)
RADIO_ITALIA_RE = re.compile(r"\bradio\s*italia\b", re.I)
TRT_WORLD_RE = re.compile(r"\btrt\s*world\b", re.I)

BRAND_REWRITE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bla\s*7\s*d\b", re.I), "LA7d"),
    (re.compile(r"\bsky\s*documentari\b", re.I), "Sky Documentaries"),
    (re.compile(r"\bsky\s*documentaries\b", re.I), "Sky Documentaries"),
    (re.compile(r"\bsky\s*serie\b", re.I), "Sky Series"),
    (re.compile(r"\bsky\s*series\b", re.I), "Sky Series"),
]

# Verified tivu numeric id -> canonical XMLTV (same signal only).
TIVU_CANONICAL: dict[str, str] = {
    "5": "Canale5.it@SD",
    "6": "Italia1.it@SD",
    "11": "Iris.it@SD",
    "18": "La5.it@HD",
    "19": "RealTime.it@SD",
    "23": "Italia2.it@SD",
    "24": "MediasetExtra.it@SD",
    "29": "Boing.it@SD",
    "42": "Rai1.it@SD",
    "43": "Rai2.it@SD",
    "44": "Rai3.it@HD",
    "88": "RaiSport.it@SD",
    "89": "Rai4.it@SD",
    "107": "RaiPremium.it@SD",
    "118": "TGCom24.it@SD",
    "259": "Giallo.it@SD",
}


def expand_name(name: str) -> str:
    original = unicodedata.normalize("NFKC", name or "")
    original = IT_PREFIX.sub("", original).strip()
    value = re.sub(r"(?i)([A-Z0-9])(HD|SD|UHD|FHD|4K)$", r"\1 \2", original)
    value = value.replace(".", " ")
    value = re.sub(r"\s+", " ", value).strip()
    for pattern, replacement in BRAND_REWRITE:
        if pattern.search(value):
            value = pattern.sub(replacement, value)
            break
    return re.sub(r"\s+", " ", value).strip()


def normalise_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).casefold().strip()
    while True:
        stripped = TECHNICAL_RE.sub("", value).strip()
        if stripped == value:
            break
        value = stripped
    return re.sub(r"[^0-9a-z]+", "", value)


def parse_flags(name: str) -> dict[str, object]:
    raw = expand_name(name)
    plus1 = bool(PLUS1_RE.search(raw))
    plus24 = bool(PLUS24_RE.search(raw))
    timeshift = 24 if plus24 else (1 if plus1 else 0)
    if not plus1 and not plus24:
        shift = TIMESHIFT_RE.search(raw)
        if shift:
            timeshift = int(shift.group(1))
    dazn = DAZN_RE.search(raw)
    sky_n = SKY_SPORT_NUM_RE.search(raw)
    sky_uno = bool(SKY_SPORT_UNO_RE.search(raw))
    if sky_uno:
        sports_family, sports_number = "skysportuno", ""
    elif sky_n:
        sports_family, sports_number = "skysport", sky_n.group(1)
    elif dazn:
        sports_family, sports_number = "dazn", dazn.group(1)
    else:
        sports_family, sports_number = "", ""
    stem_source = PLUS1_RE.sub(" ", raw)
    stem_source = PLUS24_RE.sub(" ", stem_source)
    stem_source = TIMESHIFT_RE.sub(" ", stem_source)
    stem_source = DAZN_RE.sub("dazn", stem_source)
    stem_source = SKY_SPORT_NUM_RE.sub("skysport", stem_source)
    stem_source = SKY_SPORT_UNO_RE.sub("skysportuno", stem_source)
    stem = normalise_text(stem_source)
    return {
        "stem": stem,
        "plus1": plus1,
        "plus24": plus24,
        "timeshift": timeshift,
        "sports_family": sports_family,
        "sports_number": sports_number,
        "hd": bool(HD_RE.search(raw)),
        "expanded": raw,
    }


def identity_key(name: str) -> tuple:
    flags = parse_flags(name)
    return (
        flags["stem"],
        flags["timeshift"],
        flags["sports_family"],
        flags["sports_number"],
    )


def extra_titles(name: str) -> list[str]:
    titles = [name, IT_PREFIX.sub("", name).strip(), expand_name(name)]
    out: list[str] = []
    for title in titles:
        if title and title not in out:
            out.append(title)
    return out


def xmltv_agrees(xmltv_id: str, name: str) -> bool:
    if not xmltv_id or not ID_RE.fullmatch(xmltv_id):
        return False
    flags = parse_flags(name)
    core = normalise_text(re.sub(r"[@.].*$", "", xmltv_id.split("@", 1)[0]))
    if not core or not flags["stem"]:
        return False
    return core in flags["stem"] or flags["stem"] in core


def is_strong_id(channel_id: str) -> bool:
    if not channel_id or not ID_RE.fullmatch(channel_id) or is_forbidden_channel_id(channel_id):
        return False
    if NUMERIC_ID_RE.fullmatch(channel_id) or WEAK_ID_RE.fullmatch(channel_id):
        return False
    return "." in channel_id


def canonical_channel_id(channel_id: str) -> str:
    return TIVU_CANONICAL.get(channel_id, channel_id)


def resolve_published_id(raw_id: str, name: str, source: str, catalog: dict[str, str]) -> str:
    """Pick XMLTV id; reject tivu.gr wrong channel id / xmltv_id pairings."""
    canon = canonical_channel_id(raw_id)
    catalog_id = catalog.get(raw_id) or catalog.get(f"name:{identity_key(name)}")
    if catalog_id and xmltv_agrees(catalog_id, name):
        return catalog_id
    if RADIO_ITALIA_RE.search(name) and "radioitalia" not in normalise_text(canon):
        return "RadioItaliaTV.it@HD"
    if TRT_WORLD_RE.search(name) and "trtworld" not in normalise_text(canon):
        return "TRTWorld.it@HD"
    if is_strong_id(canon) and xmltv_agrees(canon, name):
        return canon
    if is_strong_id(canon) and source == "tivu" and not xmltv_agrees(canon, name):
        return mint_id(name)
    if is_strong_id(canon):
        return canon
    return mint_id(name)


def mint_id(name: str) -> str:
    flags = parse_flags(name)
    cleaned = flags["expanded"]
    for pattern in (PLUS1_RE, PLUS24_RE, TIMESHIFT_RE, HD_RE, TECHNICAL_RE):
        cleaned = pattern.sub(" ", cleaned)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", cleaned) if w.casefold() not in {"sd", "hd"}]
    pretty = "".join(w if w.isupper() and len(w) > 1 else w.title() for w in words) or "Unknown"
    feed = "HD" if flags["hd"] else "SD"
    candidate = f"{pretty}.it@{feed}"
    return candidate if ID_RE.fullmatch(candidate) else f"it.{flags['stem'] or 'channel'}"


def vanished_title(title: str | None) -> bool:
    return (title or "").strip().casefold() in VANISHED_TITLES


def accepts_channel(channel_id: str, _source: str) -> bool:
    cid = canonical_channel_id(channel_id)
    if not cid:
        return False
    if NUMERIC_ID_RE.fullmatch(channel_id) and channel_id not in TIVU_CANONICAL:
        return False
    return True


def parse_xmltv(path: Path) -> ET.Element:
    root = ET.parse(path).getroot()
    if root.tag != "tv":
        raise ValueError(f"{path}: expected <tv> root")
    return root


def load_catalog(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not path or not path.is_file():
        return mapping
    for channel in ET.parse(path).getroot().findall("channel"):
        site_id = (channel.get("site_id") or "").strip()
        xmltv_id = (channel.get("xmltv_id") or "").strip()
        name = "".join(channel.itertext()).strip()
        if site_id and xmltv_id and xmltv_agrees(xmltv_id, name):
            mapping[site_id] = xmltv_id
        if xmltv_id and name and xmltv_agrees(xmltv_id, name):
            mapping[f"name:{identity_key(name)}"] = xmltv_id
    return mapping


def programme_richness(programme: ET.Element) -> int:
    score = 0
    if (programme.findtext("title") or "").strip():
        score += 1
    if (programme.findtext("desc") or "").strip():
        score += 3
    if programme.find("icon") is not None or programme.find("image") is not None:
        score += 1
    return score


def score_channel(programmes: list[ET.Element], source: str) -> tuple[int, int, int]:
    titled = [p for p in programmes if (p.findtext("title") or "").strip() and not vanished_title(p.findtext("title"))]
    if not titled:
        return (0, 0, SOURCE_PRIORITY.get(source, 0))
    days = {((p.get("start") or "")[:8]) for p in titled if p.get("start")}
    starts = [p.get("start") for p in titled]
    duplicates = len(starts) - len(set(starts))
    richness = sum(programme_richness(p) for p in titled)
    score = len(titled) * 4 + len(days) * 80 + richness - duplicates * 6
    return (score, SOURCE_PRIORITY.get(source, 0), len(titled))


def avoid_collision(channel_id: str, occupied: set[str], name: str) -> str:
    if channel_id not in occupied:
        return channel_id
    if "@" in channel_id:
        base, _feed = channel_id.split("@", 1)
        rewritten = f"{base}@{COLLISION_FEED}"
        if rewritten not in occupied and rewritten != channel_id:
            return rewritten
    minted = mint_id(name)
    if minted not in occupied:
        return minted
    slug = normalise_text(name) or "channel"
    fallback = f"it.{slug}"
    suffix = 2
    while fallback in occupied or not ID_RE.fullmatch(fallback):
        fallback = f"it.{slug}{suffix}"
        suffix += 1
    return fallback


def fill_programmes(entries: list[dict]) -> tuple[list[ET.Element], dict[str, int]]:
    ordered = sorted(entries, key=lambda e: SOURCE_PRIORITY.get(e["source"], 0), reverse=True)
    by_start: dict[str, tuple[ET.Element, str]] = {}
    contrib: Counter = Counter()
    for entry in ordered:
        for programme in entry["programmes"]:
            start = programme.get("start") or ""
            if not start or start in by_start:
                continue
            by_start[start] = (programme, entry["source"])
            contrib[entry["source"]] += 1
    programmes = [item[0] for item in sorted(by_start.values(), key=lambda pair: pair[0].get("start") or "")]
    return programmes, dict(contrib)


def group_key(published_id: str, name: str) -> tuple:
    if is_strong_id(published_id):
        return ("id", published_id)
    return ("identity", identity_key(name))


def programmed_channel_names(guide_paths: list[Path]) -> tuple[set[str], set[str], set[tuple]]:
    ids: set[str] = set()
    names: set[str] = set()
    identities: set[tuple] = set()
    for path in guide_paths:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        root = parse_xmltv(path)
        programmed = {p.get("channel") for p in root.findall("programme") if (p.findtext("title") or "").strip()}
        for channel in root.findall("channel"):
            channel_id = channel.get("id") or ""
            canon = canonical_channel_id(channel_id)
            if canon not in programmed and channel_id not in programmed:
                continue
            if is_strong_id(canon):
                ids.add(canon.casefold())
            display_names = [n.text.strip() for n in channel.findall("display-name") if (n.text or "").strip()]
            label = display_names[0] if display_names else canon
            identities.add(identity_key(label))
            for display_name in display_names:
                names.add(normalise_text(display_name))
    return ids, names, identities


def canonical_hints_from_guide(path: Path) -> dict[tuple, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    root = parse_xmltv(path)
    programmed = {p.get("channel") for p in root.findall("programme") if (p.findtext("title") or "").strip()}
    hints: dict[tuple, str] = {}
    for channel in root.findall("channel"):
        channel_id = canonical_channel_id(channel.get("id") or "")
        if channel_id not in programmed:
            continue
        names = [n.text.strip() for n in channel.findall("display-name") if (n.text or "").strip()]
        label = names[0] if names else channel_id
        key = identity_key(label)
        if key[0]:
            hints.setdefault(key, channel_id)
    return hints


def collect_occupied(paths: list[Path]) -> set[str]:
    occupied: set[str] = set()
    for path in paths:
        if not path or not path.is_file() or path.stat().st_size == 0:
            continue
        root = parse_xmltv(path)
        for channel in root.findall("channel"):
            channel_id = channel.get("id")
            if channel_id:
                occupied.add(channel_id)
    occupied |= set(denied_xtream_clone_ids())
    return occupied


def select_channels(
    catalog: Path,
    output: Path,
    *,
    covered_guides: list[Path] | None = None,
) -> int:
    root = ET.parse(catalog).getroot()
    covered_ids, covered_names, covered_identities = programmed_channel_names(covered_guides or [])
    selected = ET.Element("channels")
    seen: set[str] = set()
    for channel in root.findall("channel"):
        xmltv_id = (channel.get("xmltv_id") or "").strip().casefold()
        name_key = normalise_text("".join(channel.itertext()))
        logical_key = identity_key(name_key) if name_key else tuple()
        if (xmltv_id and xmltv_id in covered_ids) or (
            logical_key[0] and logical_key in covered_identities
        ) or (name_key and name_key in covered_names):
            continue
        identity = (channel.get("site_id") or "") or (channel.get("xmltv_id") or "") or "".join(channel.itertext())
        if not identity or identity in seen:
            continue
        seen.add(identity)
        node = ET.SubElement(selected, "channel", channel.attrib)
        node.text = channel.text
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(selected, space="    ")
    ET.ElementTree(selected).write(output, encoding="utf-8", xml_declaration=True)
    return len(seen)


def merge_guides(
    sources: list[tuple[str, Path, Path | None]],
    occupied: set[str],
    canonical_hints: dict[tuple, str] | None = None,
) -> tuple[ET.Element, dict[str, dict], list[dict]]:
    canonical_hints = canonical_hints or {}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    collisions: list[dict] = []

    for source_name, guide_path, catalog_path in sources:
        if not guide_path.is_file() or guide_path.stat().st_size == 0:
            continue
        catalog = load_catalog(catalog_path) if catalog_path else {}
        root = parse_xmltv(guide_path)
        for channel in root.findall("channel"):
            raw_id = channel.get("id") or ""
            canon = canonical_channel_id(raw_id)
            if not accepts_channel(raw_id, source_name):
                continue
            progs: list[ET.Element] = []
            for programme in root.findall("programme"):
                pid = programme.get("channel") or ""
                if canonical_channel_id(pid) != canon and pid != raw_id:
                    continue
                title = (programme.findtext("title") or "").strip()
                if title and not vanished_title(title):
                    progs.append(programme)
            if not progs:
                continue
            names = [n.text.strip() for n in channel.findall("display-name") if (n.text or "").strip()]
            name = names[0] if names else canon
            published_id = resolve_published_id(raw_id, name, source_name, catalog)
            groups[group_key(published_id, name)].append(
                {
                    "source": source_name,
                    "channel": channel,
                    "name": name,
                    "published_id": published_id,
                    "programmes": progs,
                    "hd": parse_flags(name)["hd"],
                }
            )

    result = ET.Element("tv")
    used_ids: set[str] = set()
    source_choice: dict[str, dict] = {}
    for _key, entries in sorted(groups.items(), key=lambda item: str(item[0])):
        viable = [entry for entry in entries if score_channel(entry["programmes"], entry["source"])[0] > 0]
        if not viable:
            continue
        viable.sort(
            key=lambda entry: (
                SOURCE_PRIORITY.get(entry["source"], 0),
                score_channel(entry["programmes"], entry["source"])[0],
            ),
            reverse=True,
        )
        winner = viable[0]
        programmes, contrib = fill_programmes(viable)
        if not programmes:
            continue
        channel_id = winner["published_id"]
        if not is_strong_id(channel_id):
            channel_id = mint_id(winner["name"])
        hinted = None
        if isinstance(_key, tuple) and _key[0] == "identity":
            hinted = canonical_hints.get(_key[1])
        if hinted and hinted not in used_ids and is_strong_id(hinted):
            channel_id = hinted
        original_id = channel_id
        channel_id = avoid_collision(channel_id, occupied | used_ids, winner["name"])
        if original_id in occupied:
            collisions.append(
                {
                    "name": winner["name"],
                    "original_id": original_id,
                    "rewritten_id": channel_id,
                    "source": winner["source"],
                }
            )
        if not channel_id or channel_id in used_ids or is_forbidden_channel_id(channel_id):
            continue
        if NUMERIC_ID_RE.fullmatch(channel_id):
            continue
        used_ids.add(channel_id)
        source_choice[channel_id] = {
            "identity_source": winner["source"],
            "contrib": contrib,
            "name": winner["name"],
            "original_id": original_id,
        }
        node = copy.deepcopy(winner["channel"])
        node.set("id", channel_id)
        display = node.find("display-name")
        if display is None:
            display = ET.SubElement(node, "display-name")
        display.text = winner["name"]
        result.append(node)
        for programme in programmes:
            cloned = copy.deepcopy(programme)
            cloned.set("channel", channel_id)
            result.append(cloned)
    if not result.findall("programme"):
        raise ValueError("no Italy programmes were generated")
    return result, source_choice, collisions


def write_merged(
    sources: list[tuple[str, Path, Path | None]],
    output: Path,
    occupied: set[str],
    canonical_hints: dict[tuple, str] | None = None,
) -> tuple[int, int, dict[str, dict], list[dict]]:
    merged, source_choice, collisions = merge_guides(sources, occupied, canonical_hints)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space="  ")
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    checked = parse_xmltv(output)
    channels = {c.get("id") for c in checked.findall("channel")}
    if None in channels or "" in channels:
        raise ValueError("merged Italy guide contains empty channel ids")
    programmes = checked.findall("programme")
    if any(p.get("channel") not in channels for p in programmes):
        raise ValueError("merged Italy guide has invalid programme references")
    if any(NUMERIC_ID_RE.fullmatch(cid or "") for cid in channels):
        raise ValueError("merged Italy guide contains numeric-only channel ids")
    return len(channels), len(programmes), source_choice, collisions


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
    select.add_argument("--covered-guide", action="append", type=Path, default=[])
    merge = sub.add_parser("merge")
    merge.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="NAME=GUIDE[,CATALOG]",
    )
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--occupied-guide", action="append", type=Path, default=[])
    merge.add_argument("--canonical-guide", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command == "select":
        count = select_channels(args.catalog, args.output, covered_guides=args.covered_guide)
        print(count)
        return 0
    sources = [parse_source(value) for value in args.source]
    occupied = collect_occupied(args.occupied_guide)
    hints: dict[tuple, str] = {}
    for guide in args.canonical_guide:
        for key, channel_id in canonical_hints_from_guide(guide).items():
            hints.setdefault(key, channel_id)
    channels, programmes, choices, collisions = write_merged(sources, args.output, occupied, hints or None)
    by_source: dict[str, int] = defaultdict(int)
    for meta in choices.values():
        by_source[meta["identity_source"]] += 1
    print(
        f"Italy guide: {channels} channels, {programmes} programmes; "
        f"sources {dict(by_source)}; collisions rewritten {len(collisions)}"
    )
    for row in collisions:
        print(f"collision: {row['original_id']} -> {row['rewritten_id']} ({row['name']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"Italy EPG failed: {exc}", file=sys.stderr)
        raise SystemExit(1)