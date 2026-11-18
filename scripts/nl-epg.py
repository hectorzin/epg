#!/usr/bin/env python3
"""Select Dutch channels and merge XMLTV guides (Ziggo > Delta > tvgids)."""
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
TIMESHIFT_RE = re.compile(r"\+\s*(\d+)\b")
HD_RE = re.compile(r"\b(uhd|4k|fhd|full\s*hd|\bhd\b)", re.IGNORECASE)
TECHNICAL_RE = re.compile(
    r"(?:[\s._()\[\]-]*)(?:FULL[\s._-]*HD|FHD|UHD|HD|SD|4K|HEVC|H265|H264)[\s)\]]*$",
    re.IGNORECASE,
)
ESPN_RE = re.compile(r"\bespn\s*(\d+)\b", re.IGNORECASE)
ZIGGO_SPORT_NUM_RE = re.compile(r"\bziggo\s*sport\s*(\d+)\b", re.IGNORECASE)
WEAK_ID_RE = re.compile(r"^(?:NL1#|[0-9]+$|[a-z0-9]+(?:-[a-z0-9]+)+)$")
ID_RE = re.compile(r"^[^\s<>\"']+$")
NL_PREFIX = re.compile(r"^\s*(?:\[NL\]|NL)\s*[:|/_-]?\s*", re.IGNORECASE)
NUMERIC_ID_RE = re.compile(r"^\d+$")
SOURCE_PRIORITY = {"ziggo": 4, "delta": 3, "tvgids": 2}
COLLISION_FEED = "Netherlands"
NH_RE = re.compile(r"\bnh\s*nieuws\b", re.I)

BRAND_REWRITE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bfox\b", re.I), "STAR Channel"),
    (re.compile(r"\bboomerang\b", re.I), "Cartoonito"),
    (re.compile(r"\bspike\b", re.I), "Paramount Network"),
    (re.compile(r"\bnat(?:ional)?\s*geo(?:graphic)?\s+wild\b", re.I), "National Geographic Wild"),
    (re.compile(r"\bnat(?:ional)?\s*geo(?:graphic)?\b", re.I), "National Geographic"),
    (re.compile(r"\bnpo\s*politiek(?:\s+en\s+nieuws)?\b", re.I), "NPO Politiek en Nieuws"),
    (re.compile(r"\bnpo\s*nieuws?\b", re.I), "NPO Politiek en Nieuws"),
    (re.compile(r"\btv\s*gelderland\b", re.I), "Omroep Gelderland"),
    (re.compile(r"\btv\s*oost\b", re.I), "RTV Oost"),
    (re.compile(r"\btv\s*rijnmond\b", re.I), "RTV Rijnmond"),
    (re.compile(r"\btv\s*west\b", re.I), "RTV West"),
    (re.compile(r"\bhorse\s*(?:and|&)\s*country(?:\s+tv)?\b", re.I), "Horse & Country TV"),
    (re.compile(r"\bmezzo\s*llive\b", re.I), "Mezzo"),
    (re.compile(r"\be!?\s*entertainment\b", re.I), "E!"),
    (re.compile(r"\bdance\s*trippin\b", re.I), "DanceTelevision"),
    (re.compile(r"\bdisney\s*xd\s*/\s*veronica\b", re.I), "Veronica Disney XD"),
    (re.compile(r"\bveronica\s*/\s*disney\s*xd\b", re.I), "Veronica Disney XD"),
    (re.compile(r"\bal\s*jazeera\s+engels\b", re.I), "Al Jazeera English"),
    (re.compile(r"\bl1murg\b", re.I), "L1"),
    (re.compile(r"\bl1\s*tv\b", re.I), "L1"),
]
STEM_ALIASES = {
    "npopolitiek": "npopolitiekennieuws",
    "npopolitiekennieuwsennieuws": "npopolitiekennieuws",
    "nponieuws": "npopolitiekennieuws",
    "l1tv": "l1",
    "l1murg": "l1",
    "horseandcountrytvtv": "horsecountrytv",
    "horseandcountrytv": "horsecountrytv",
    "horsecountry": "horsecountrytv",
    "aljazeeraengels": "aljazeeraenglish",
    "aljazeerainternational": "aljazeeraenglish",
    "cnbceurope": "cnbc",
}


def expand_name(name: str) -> str:
    original = unicodedata.normalize("NFKC", name or "")
    original = NL_PREFIX.sub("", original).strip()
    value = re.sub(r"(?i)([A-Z0-9])(HD|SD|UHD|FHD|4K)$", r"\1 \2", original)
    value = value.replace(".", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if NH_RE.search(value):
        value = NH_RE.sub("NH", value)
    else:
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
    timeshift = 1 if plus1 else 0
    if not plus1:
        shift = TIMESHIFT_RE.search(raw)
        if shift:
            timeshift = int(shift.group(1))
    espn = ESPN_RE.search(raw)
    ziggo_n = ZIGGO_SPORT_NUM_RE.search(raw)
    if espn:
        sports_family, sports_number = "espn", espn.group(1)
    elif ziggo_n:
        sports_family, sports_number = "ziggosport", ziggo_n.group(1)
    elif re.search(r"\bespn\b", raw, re.I) and not re.search(r"compleet|uhd", raw, re.I):
        sports_family, sports_number = "espn", "1"
    else:
        sports_family, sports_number = "", ""
    stem_source = PLUS1_RE.sub(" ", raw)
    stem_source = TIMESHIFT_RE.sub(" ", stem_source)
    if espn or sports_family == "espn":
        stem_source = ESPN_RE.sub("espn", stem_source)
        stem_source = re.sub(r"\bespn\b", "espn", stem_source, flags=re.I)
    if ziggo_n:
        stem_source = ZIGGO_SPORT_NUM_RE.sub("ziggo sport", stem_source)
    stem = STEM_ALIASES.get(normalise_text(stem_source), normalise_text(stem_source))
    return {
        "stem": stem,
        "plus1": plus1,
        "timeshift": timeshift,
        "region": "",
        "sports_family": sports_family,
        "sports_number": sports_number,
        "hd": bool(HD_RE.search(raw)),
        "expanded": raw,
    }


def extra_titles(name: str) -> list[str]:
    titles = [name, NL_PREFIX.sub("", name).strip(), expand_name(name)]
    flags = parse_flags(name)
    if flags["sports_family"] == "espn" and flags["sports_number"] == "1":
        titles.append("ESPN")
    if "horse" in (name or "").casefold() and "country" in (name or "").casefold():
        titles.append("Horse & Country TV")
    out: list[str] = []
    for title in titles:
        if title and title not in out:
            out.append(title)
    return out


def identity_key(name: str) -> tuple:
    flags = parse_flags(name)
    return (
        flags["stem"],
        flags["timeshift"],
        flags["sports_family"],
        flags["sports_number"],
    )


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
    if channel_id.startswith("NL1#") or NUMERIC_ID_RE.fullmatch(channel_id):
        return False
    if WEAK_ID_RE.fullmatch(channel_id):
        return False
    return "." in channel_id


def mint_id(name: str) -> str:
    flags = parse_flags(name)
    expanded = str(flags["expanded"])
    cleaned = PLUS1_RE.sub(" ", expanded)
    cleaned = TIMESHIFT_RE.sub(" ", cleaned)
    cleaned = HD_RE.sub(" ", cleaned)
    cleaned = TECHNICAL_RE.sub(" ", cleaned)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", cleaned) if w.casefold() not in {"sd", "hd"}]
    pretty = "".join(w if w.isupper() and len(w) > 1 else w.title() for w in words) or "Unknown"
    if flags["sports_number"] and str(flags["sports_number"]) not in pretty:
        pretty = f"{pretty}{flags['sports_number']}"
    feed = "HD" if flags["hd"] else "SD"
    candidate = f"{pretty}.nl@{feed}"
    return candidate if ID_RE.fullmatch(candidate) else f"nl.{flags['stem'] or 'channel'}"


def vanished_title(title: str | None) -> bool:
    return (title or "").strip().casefold() in VANISHED_TITLES


def accepts_channel(channel_id: str, source: str) -> bool:
    if not channel_id:
        return False
    stem = channel_id.split("@", 1)[0]
    if stem.casefold().endswith(".br"):
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
    if (programme.findtext("sub-title") or "").strip():
        score += 1
    if any((node.text or "").strip() for node in programme.findall("category")):
        score += 1
    if programme.find("icon") is not None or programme.find("image") is not None:
        score += 1
    if programme.find("episode-num") is not None:
        score += 1
    if programme.find("credits") is not None:
        score += 2
    return score


def score_channel(programmes: list[ET.Element], source: str) -> tuple[int, int, int]:
    titled = [
        p
        for p in programmes
        if (p.findtext("title") or "").strip() and not vanished_title(p.findtext("title"))
    ]
    if not titled:
        return (0, 0, SOURCE_PRIORITY.get(source, 0))
    days = {((p.get("start") or "")[:8]) for p in titled if p.get("start")}
    starts = [p.get("start") for p in titled]
    duplicates = len(starts) - len(set(starts))
    richness = sum(programme_richness(p) for p in titled)
    score = (
        len(titled) * 4
        + len(days) * 80
        + richness
        + sum(1 for p in titled if (p.findtext("desc") or "").strip()) * 2
        - duplicates * 6
    )
    return (score, SOURCE_PRIORITY.get(source, 0), len(titled))


def preferred_id(candidates: list[tuple[str, str, dict]]) -> str:
    strong = [
        item
        for item in candidates
        if is_strong_id(item[0]) and xmltv_agrees(item[0], item[2]["name"])
    ]
    if strong:
        strong.sort(
            key=lambda item: (-SOURCE_PRIORITY.get(item[1], 0), not item[2].get("hd"), item[0])
        )
        return strong[0][0]
    by_prio = max(candidates, key=lambda item: SOURCE_PRIORITY.get(item[1], 0))
    return mint_id(by_prio[2]["name"])


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
    fallback = f"nl.{slug}"
    suffix = 2
    while fallback in occupied or not ID_RE.fullmatch(fallback):
        fallback = f"nl.{slug}{suffix}"
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
    programmes = [
        item[0] for item in sorted(by_start.values(), key=lambda pair: pair[0].get("start") or "")
    ]
    return programmes, dict(contrib)


def programmed_channel_names(guide_paths: list[Path]) -> tuple[set[str], set[str], set[tuple]]:
    ids: set[str] = set()
    names: set[str] = set()
    identities: set[tuple] = set()
    for path in guide_paths:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        root = parse_xmltv(path)
        programmed = {
            p.get("channel")
            for p in root.findall("programme")
            if (p.findtext("title") or "").strip()
        }
        for channel in root.findall("channel"):
            channel_id = channel.get("id") or ""
            if channel_id not in programmed:
                continue
            ids.add(channel_id.casefold())
            display_names = [
                (node.text or "").strip()
                for node in channel.findall("display-name")
                if (node.text or "").strip()
            ]
            label = display_names[0] if display_names else channel_id
            identities.add(identity_key(label))
            for display_name in display_names:
                names.add(normalise_text(display_name))
                identities.add(identity_key(display_name))
    return ids, names, identities


def canonical_hints_from_guide(path: Path) -> dict[tuple, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    root = parse_xmltv(path)
    programmed = {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip()
    }
    hints: dict[tuple, str] = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if channel_id not in programmed:
            continue
        names = [node.text.strip() for node in channel.findall("display-name") if (node.text or "").strip()]
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


def load_grab_excludes(path: Path | None) -> set[str]:
    if not path or not path.is_file():
        return set()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {str(row.get("site_id", "")).strip() for row in raw if isinstance(row, dict) and row.get("site_id")}
    return set()


def select_channels(
    catalog: Path,
    output: Path,
    *,
    covered_guides: list[Path] | None = None,
    exclude_site_ids: set[str] | None = None,
) -> int:
    root = ET.parse(catalog).getroot()
    covered_ids, covered_names, covered_identities = programmed_channel_names(covered_guides or [])
    exclude = exclude_site_ids or set()
    selected = ET.Element("channels")
    seen: set[str] = set()
    for channel in root.findall("channel"):
        site_id = (channel.get("site_id") or "").strip()
        if site_id in exclude:
            continue
        xmltv_id = (channel.get("xmltv_id") or "").strip().casefold()
        name_key = normalise_text("".join(channel.itertext()))
        logical_key = identity_key(name_key) if name_key else tuple()
        if (xmltv_id and xmltv_id in covered_ids) or (
            logical_key[0] and logical_key in covered_identities
        ) or (name_key and name_key in covered_names):
            continue
        identity = site_id or (channel.get("xmltv_id") or "") or "".join(channel.itertext())
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
        channels = {c.get("id"): c for c in root.findall("channel") if c.get("id")}
        programmes: dict[str, list[ET.Element]] = defaultdict(list)
        for programme in root.findall("programme"):
            channel_id = programme.get("channel") or ""
            title = (programme.findtext("title") or "").strip()
            if not channel_id or not title or vanished_title(title):
                continue
            if not programme.get("start") or not programme.get("stop"):
                continue
            programmes[channel_id].append(programme)
        for channel_id, channel in channels.items():
            if not accepts_channel(channel_id, source_name):
                continue
            names = [n.text.strip() for n in channel.findall("display-name") if (n.text or "").strip()]
            name = names[0] if names else channel_id
            catalog_id = catalog.get(channel_id) or catalog.get(f"name:{identity_key(name)}")
            published_id = channel_id
            if catalog_id and xmltv_agrees(catalog_id, name):
                published_id = catalog_id
            elif is_strong_id(channel_id) and xmltv_agrees(channel_id, name):
                published_id = channel_id
            key = identity_key(name)
            if not key[0]:
                continue
            groups[key].append(
                {
                    "source": source_name,
                    "channel": channel,
                    "name": name,
                    "published_id": published_id,
                    "programmes": programmes.get(channel_id, []),
                    "hd": parse_flags(name)["hd"],
                }
            )

    result = ET.Element("tv")
    used_ids: set[str] = set()
    source_choice: dict[str, dict] = {}
    for key, entries in sorted(groups.items(), key=lambda item: item[0][0]):
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
        candidates = [
            (entry["published_id"], entry["source"], {"name": entry["name"], "hd": entry["hd"]})
            for entry in viable
        ]
        channel_id = preferred_id(candidates)
        hinted = canonical_hints.get(key)
        if hinted and hinted not in used_ids and ID_RE.fullmatch(hinted):
            if hinted not in occupied or hinted == channel_id:
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
        if (
            not channel_id
            or not ID_RE.fullmatch(channel_id)
            or channel_id in used_ids
            or NUMERIC_ID_RE.fullmatch(channel_id)
            or is_forbidden_channel_id(channel_id)
        ):
            raise ValueError(f"invalid NL channel id for {winner['name']}: {channel_id!r}")
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
        raise ValueError("no Netherlands programmes were generated")
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
        raise ValueError("merged NL guide contains empty channel ids")
    programmes = checked.findall("programme")
    if any(p.get("channel") not in channels for p in programmes):
        raise ValueError("merged NL guide has invalid programme references")
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
    select.add_argument("--exclude-site-id", action="append", default=[])
    select.add_argument(
        "--exclude-site-ids-file",
        type=Path,
        help="JSON list of {site_id,...} entries never present on Delta",
    )
    merge = sub.add_parser("merge")
    merge.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="NAME=GUIDE[,CATALOG]",
        help="Named XMLTV source, optionally with a channels.xml catalog",
    )
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--occupied-guide", action="append", type=Path, default=[])
    merge.add_argument("--canonical-guide", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command == "select":
        excludes = load_grab_excludes(args.exclude_site_ids_file)
        excludes.update(str(v).strip() for v in args.exclude_site_id if str(v).strip())
        count = select_channels(
            args.catalog,
            args.output,
            covered_guides=args.covered_guide,
            exclude_site_ids=excludes,
        )
        print(count)
        return 0
    sources = [parse_source(value) for value in args.source]
    occupied = collect_occupied(args.occupied_guide)
    hints: dict[tuple, str] = {}
    for guide in args.canonical_guide:
        for key, channel_id in canonical_hints_from_guide(guide).items():
            hints.setdefault(key, channel_id)
    channels, programmes, choices, collisions = write_merged(
        sources, args.output, occupied, hints or None
    )
    by_source: dict[str, int] = defaultdict(int)
    for meta in choices.values():
        by_source[meta["identity_source"]] += 1
    print(
        f"Netherlands guide: {channels} channels, {programmes} programmes; "
        f"sources {dict(by_source)}; collisions rewritten {len(collisions)}"
    )
    for row in collisions:
        print(f"collision: {row['original_id']} -> {row['rewritten_id']} ({row['name']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"Netherlands EPG failed: {exc}", file=sys.stderr)
        raise SystemExit(1)