#!/usr/bin/env python3
"""Select Turkish channels and merge XMLTV guides.

Priority: Digiturk, D-Smart, TV+, Türksat Kablo, then EPGShare TR1.
Programmes stay in their source language and timezone offset.
Published ids use the .tr TLD so a Turkish feed is not mixed into another country.
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
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
    "digiturk": 5,
    "dsmart": 4,
    "tvplus": 3,
    "turksat": 2,
    "epgshare": 1,
}
COLLISION_FEED = "Turkey"
ID_RE = re.compile(r"^[^\s<>\"']+$")
STRONG_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*\.tr@(?:SD|HD|FHD|UHD|4K)$")
PUBLISHED_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*\.tr@(?:SD|HD|FHD|UHD|4K|Turkey)$")
TIMESHIFT_RE = re.compile(r"(?:\+\s*1|plus\s*1)", re.IGNORECASE)
PREFIX_RE = re.compile(r"^\s*tr\s+", re.IGNORECASE)
STAR_TAIL_RE = re.compile(r"\s*[*@]+\s*[A-Za-z]?\s*$")
DASH_TAIL_RE = re.compile(r"\s*-\s*[A-Za-z]\s*$")
LETTER_STAR_RE = re.compile(r"\s+[HA]\*\s*$", re.IGNORECASE)
# Whole-station spelling fixes. Applied to the compact key, never as a substring.
EXACT_ALIASES = {
    "now": "fox",
    "nowtv": "fox",
    "foxtv": "fox",
    "ssportstv": "ssport",
    "ssporttv": "ssport",
    "natgeo": "nationalgeographic",
    "nationalgeo": "nationalgeographic",
    "natgeowild": "nationalgeographicwild",
    "discoverysience": "discoveryscience",
    "discoveryidx": "discoveryid",
    "discovery": "discoverychannel",
    "beiniztv": "beiniz",
    "trt3trtspor": "trt3spor",
    "ulusaltv": "ulusalkanal",
    "a2tv": "a2",
    "haberturktv": "haberturk",
    "minikagotv": "minikago",
    "fbtv": "fenerbahcetv",
    "24tv": "24",
    "360tv": "360",
    "eurosport2tr": "eurosport2",
    # EPGShare TR1 leaves beIN SPORTS 1 empty and puts that schedule on "Beinsports".
    "beinsports1": "beinsports",
    # Same station: D-Smart "Dream Tv" and TV+ "DREAM TÜRK" share DreamTurk.tr@SD.
    "dreamtv": "dreamturk",
    "ekoturktv": "ekoturk",
    "lalegultv": "lalegul",
    # TV+ names this station "TMB TV" with xmltv id TMB.tr@SD.
    "tmbtv": "tmb",
    # TV+ names the channel SEMERKAND and gives it the id SemerkandTV.tr@SD.
    "semerkandtv": "semerkand",
    # TV+ writes NR1 DAMAR as Number1Damar.tr@SD, so NR1 is that network's Number1.
    "nr1turktv": "number1turk",
    "nr1tv": "number1tv",
}
GLUED_SUFFIXES = ("1080p", "720p", "480p", "hevc265", "hevc", "fhd", "uhd", "h265", "h264", "4k", "hd", "sd")
TURKISH_ASCII = str.maketrans(
    {
        "İ": "I",
        "ı": "i",
        "Ş": "S",
        "ş": "s",
        "Ğ": "G",
        "ğ": "g",
        "Ç": "C",
        "ç": "c",
        "Ö": "O",
        "ö": "o",
        "Ü": "U",
        "ü": "u",
    }
)


def fold_letters(text: str) -> str:
    value = (text or "").replace("\u0130", "i").replace("\u0131", "i")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.casefold()


def presentation(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "").strip()
    text = PREFIX_RE.sub("", text).strip()
    while True:
        updated = LETTER_STAR_RE.sub("", text).strip()
        updated = STAR_TAIL_RE.sub("", updated).strip()
        updated = DASH_TAIL_RE.sub("", updated).strip()
        if updated == text:
            return text
        text = updated


def spell(key: str) -> str:
    key = re.sub(r"beinspor(?!t)", "beinsports", key)
    key = re.sub(r"beinsports?", "beinsports", key)
    if key in {"ssportstv", "ssporttv"}:
        key = "ssport"
    return key


def strip_glued_quality(key: str) -> str:
    for suffix in GLUED_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            return key[: -len(suffix)]
    return key


def compact_key(name: str) -> str:
    text = fold_letters(presentation(name))
    text = re.sub(r"(?:1080|720|480)\s*p", " ", text)
    text = re.sub(r"\b(?:full\s*hd|fhd|uhd|hevc265|hevc|h265|h264|4k)\b", " ", text)
    text = re.sub(r"\b(?:hd|sd)\b", " ", text)
    text = re.sub(r"\b(?:tr|turkey)\b", " ", text)
    text = re.sub(r"\blive\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return strip_glued_quality(text)


def station_key(name: str) -> str:
    key = spell(compact_key(name))
    return EXACT_ALIASES.get(key, key)


def is_timeshift(name: str) -> bool:
    return bool(TIMESHIFT_RE.search(presentation(name)))


def identity_key(name: str) -> tuple[str, int]:
    return (station_key(name), 1 if is_timeshift(name) else 0)


def is_separator(name: str) -> bool:
    raw = name or ""
    if raw.count("*") >= 3 or raw.count("-") >= 4:
        return True
    folded = fold_letters(PREFIX_RE.sub("", raw))
    parts = [part for part in re.split(r"\s+", folded) if part]
    if len(parts) >= 3 and sum(1 for part in parts if len(part) == 1) >= 3:
        return True
    return not re.sub(r"[^a-z0-9]+", "", folded)


def id_token(channel_id: str) -> str:
    return (channel_id or "").split("@", 1)[0]


def is_strong_tr_id(channel_id: str | None) -> bool:
    if not channel_id or not STRONG_ID_RE.fullmatch(channel_id):
        return False
    return not is_forbidden_channel_id(channel_id)


def is_published_id(channel_id: str | None) -> bool:
    if not channel_id or not PUBLISHED_ID_RE.fullmatch(channel_id):
        return False
    return not is_forbidden_channel_id(channel_id)


def tokens_match(epg_id: str, station: str) -> bool:
    token = station_key(id_token(epg_id))
    if not token or not station:
        return False
    if token == station:
        return True
    if len(token) >= 3 and (token + "tv" == station or station + "tv" == token):
        return True
    return False


def pretty_token(word: str) -> str:
    if any(ch.islower() for ch in word) and any(ch.isupper() for ch in word):
        return word
    if word.isupper() and 1 < len(word) <= 4:
        return word
    if word.isdigit():
        return word
    return word[:1].upper() + word[1:].lower()


def mint_id(name: str) -> str:
    text = presentation(name).translate(TURKISH_ASCII)
    text = TIMESHIFT_RE.sub(" ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"(?:1080|720|480)\s*[Pp]", " ", text)
    text = re.sub(
        r"\b(?:FULL\s*HD|FHD|UHD|HEVC265|HEVC|H265|H264|4K|HD|SD|TR|TURKEY|LIVE)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    pretty = "".join(pretty_token(word) for word in re.findall(r"[A-Za-z0-9]+", text))
    candidate = f"{pretty or 'Channel'}.tr@SD"
    if ID_RE.fullmatch(candidate) and not is_forbidden_channel_id(candidate):
        return candidate
    slug = station_key(name) or "channel"
    return f"Tr{slug[:40]}.tr@SD"


def vanished_title(title: str | None) -> bool:
    return (title or "").strip().casefold() in VANISHED_TITLES


def channel_name(channel: ET.Element) -> str:
    for node in channel.findall("display-name"):
        text = (node.text or "").strip()
        if text:
            return text
    return "".join(channel.itertext()).strip()


def parse_xmltv(path: Path) -> ET.Element:
    root = ET.parse(path).getroot()
    if root.tag != "tv":
        raise ValueError(f"{path}: expected <tv> root")
    return root


def id_score(channel_id: str, station: str) -> int:
    if not is_strong_tr_id(channel_id) or station_key(id_token(channel_id)) != station:
        return 0
    if compact_key(id_token(channel_id)) == station:
        return 3
    return 2


def avoid_collision(channel_id: str, occupied: set[str], used: set[str], name: str) -> str:
    def free(candidate: str) -> bool:
        return (
            candidate not in occupied
            and candidate not in used
            and is_published_id(candidate)
            and not is_forbidden_channel_id(candidate)
        )

    if free(channel_id) and (is_strong_tr_id(channel_id) or channel_id.endswith("@Turkey")):
        return channel_id
    if is_strong_tr_id(channel_id):
        rewritten = f"{channel_id.split('@', 1)[0]}@{COLLISION_FEED}"
        if free(rewritten):
            return rewritten
    minted = mint_id(name)
    if free(minted):
        return minted
    slug = station_key(name) or "channel"
    suffix = 2
    while True:
        candidate = f"Tr{slug[:36]}{suffix}.tr@SD"
        if free(candidate):
            return candidate
        suffix += 1


def programmed_channel_names(guide_paths: list[Path]) -> tuple[set[str], set[tuple[str, int]]]:
    ids: set[str] = set()
    identities: set[tuple[str, int]] = set()
    for path in guide_paths:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        root = parse_xmltv(path)
        programmed = {
            programme.get("channel")
            for programme in root.findall("programme")
            if (programme.findtext("title") or "").strip() and not vanished_title(programme.findtext("title"))
        }
        for channel in root.findall("channel"):
            channel_id = channel.get("id") or ""
            if channel_id not in programmed:
                continue
            ids.add(channel_id.casefold())
            key = identity_key(channel_name(channel) or channel_id)
            if key[0]:
                identities.add(key)
    return ids, identities


def select_channels(
    catalog: Path,
    output: Path,
    *,
    covered_guides: list[Path] | None = None,
) -> int:
    root = ET.parse(catalog).getroot()
    covered_ids, covered_identities = programmed_channel_names(covered_guides or [])
    selected = ET.Element("channels")
    seen_keys: set[tuple[str, int]] = set()
    seen_xmltv: dict[str, tuple[str, int]] = {}
    count = 0
    for channel in root.findall("channel"):
        name = channel_name(channel)
        key = identity_key(name)
        if not key[0] or is_separator(name) or key in seen_keys or key in covered_identities:
            continue
        xmltv_id = (channel.get("xmltv_id") or "").strip()
        site_id = (channel.get("site_id") or "").strip()
        if xmltv_id and xmltv_id.casefold() in covered_ids:
            continue
        attrib = dict(channel.attrib)
        if xmltv_id:
            owner = seen_xmltv.get(xmltv_id)
            if owner and owner != key:
                attrib.pop("xmltv_id", None)
            else:
                seen_xmltv[xmltv_id] = key
        if not (attrib.get("site_id") or attrib.get("xmltv_id") or site_id):
            continue
        seen_keys.add(key)
        node = ET.SubElement(selected, "channel", attrib)
        node.text = name
        count += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(selected, space="    ")
    ET.ElementTree(selected).write(output, encoding="utf-8", xml_declaration=True)
    return count


def usable_programmes(channel_id: str, programmes: list[ET.Element]) -> list[ET.Element]:
    kept = []
    for programme in programmes:
        title = (programme.findtext("title") or "").strip()
        if (
            programme.get("channel") == channel_id
            and programme.get("start")
            and programme.get("stop")
            and title
            and not vanished_title(title)
        ):
            kept.append(programme)
    return kept


def choose_id(rows: list[dict], station: str, occupied: set[str], used: set[str]) -> tuple[str, str]:
    best_id = ""
    best_rank: tuple[int, int, str] | None = None
    for row in rows:
        score = id_score(row["original_id"], station)
        if score <= 0:
            continue
        rank = (score, row["priority"], row["original_id"])
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_id = row["original_id"]
    original = best_id or mint_id(rows[0]["name"])
    return avoid_collision(original, occupied, used, rows[0]["name"]), original


def fill_programmes(rows: list[dict]) -> tuple[list[ET.Element], dict[str, int]]:
    ordered = sorted(rows, key=lambda row: (-row["priority"], row["source"]))
    by_start: dict[str, ET.Element] = {}
    contrib: Counter = Counter()
    for row in ordered:
        for programme in row["programmes"]:
            start = programme.get("start") or ""
            if not start or start in by_start:
                continue
            by_start[start] = programme
            contrib[row["source"]] += 1
    return [by_start[start] for start in sorted(by_start)], dict(contrib)


def catalog_identities(paths: list[Path | None]) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for path in paths:
        if path is None or not path.is_file():
            continue
        for channel in ET.parse(path).getroot().findall("channel"):
            key = identity_key(channel_name(channel))
            if key[0]:
                keys.add(key)
    return keys


def retain_previous(
    result: ET.Element,
    used: set[str],
    occupied: set[str],
    previous: list[Path],
    catalog_keys: set[tuple[str, int]],
) -> int:
    if not catalog_keys:
        return 0
    kept = 0
    seen: set[str] = set()
    for path in previous:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        root = parse_xmltv(path)
        for channel in root.findall("channel"):
            channel_id = channel.get("id") or ""
            if (
                not channel_id
                or channel_id in seen
                or channel_id in used
                or channel_id in occupied
                or not is_published_id(channel_id)
            ):
                continue
            seen.add(channel_id)
            name = channel_name(channel) or channel_id
            key = identity_key(name)
            if not key[0] or key not in catalog_keys:
                continue
            if any(identity_key(channel_name(node) or "") == key for node in result.findall("channel")):
                continue
            node = copy.deepcopy(channel)
            node.set("id", channel_id)
            result.append(node)
            used.add(channel_id)
            kept += 1
    return kept


def merge_guides(
    sources: list[tuple[str, Path, Path | None]],
    occupied: set[str],
    previous_guides: list[Path] | None = None,
) -> tuple[ET.Element, dict[str, dict], list[dict]]:
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for source_name, guide_path, _catalog in sources:
        if not guide_path.is_file() or guide_path.stat().st_size == 0:
            continue
        root = parse_xmltv(guide_path)
        programmes: dict[str, list[ET.Element]] = defaultdict(list)
        for programme in root.findall("programme"):
            channel_id = programme.get("channel") or ""
            if channel_id:
                programmes[channel_id].append(programme)
        for channel in root.findall("channel"):
            channel_id = channel.get("id") or ""
            name = channel_name(channel) or channel_id
            key = identity_key(name)
            if not channel_id or not key[0] or is_separator(name):
                continue
            usable = usable_programmes(channel_id, programmes.get(channel_id, []))
            if not usable:
                continue
            groups[key].append(
                {
                    "source": source_name,
                    "priority": SOURCE_PRIORITY.get(source_name, 0),
                    "channel": channel,
                    "name": name,
                    "original_id": channel_id,
                    "programmes": usable,
                }
            )

    result = ET.Element("tv")
    used: set[str] = set()
    choices: dict[str, dict] = {}
    collisions: list[dict] = []
    for key, rows in sorted(groups.items(), key=lambda item: item[0]):
        station = key[0]
        published, original = choose_id(rows, station, occupied, used)
        if published != original:
            collisions.append(
                {
                    "name": rows[0]["name"],
                    "original_id": original,
                    "rewritten_id": published,
                    "source": rows[0]["source"],
                }
            )
        if published in used or not is_published_id(published):
            raise ValueError(f"invalid TR channel id for {rows[0]['name']}: {published!r}")
        programmes, contrib = fill_programmes(rows)
        if not programmes:
            continue
        winner = max(rows, key=lambda row: (row["priority"], row["source"]))
        node = copy.deepcopy(winner["channel"])
        node.set("id", published)
        display = node.find("display-name")
        if display is None:
            display = ET.Element("display-name")
            node.insert(0, display)
        display.text = winner["name"]
        if not (display.get("lang") or "").strip():
            display.set("lang", "tr")
        result.append(node)
        for programme in programmes:
            cloned = copy.deepcopy(programme)
            cloned.set("channel", published)
            result.append(cloned)
        used.add(published)
        choices[published] = {
            "identity_source": winner["source"],
            "contrib": contrib,
            "name": winner["name"],
            "original_id": original,
            "station": station,
        }
    retain_previous(
        result,
        used,
        occupied,
        previous_guides or [],
        catalog_identities([catalog for _name, _guide, catalog in sources]),
    )
    if not result.findall("programme"):
        raise ValueError("no Turkish programmes were generated")
    normalize_channels_in_tree(result)
    return result, choices, collisions


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
    return occupied


def write_merged(
    sources: list[tuple[str, Path, Path | None]],
    output: Path,
    occupied: set[str],
    previous_guides: list[Path] | None = None,
) -> tuple[int, int, dict[str, dict], list[dict]]:
    merged, choices, collisions = merge_guides(sources, occupied, previous_guides)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space="  ")
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    checked = parse_xmltv(output)
    channels = [channel.get("id") for channel in checked.findall("channel")]
    if any(not channel_id for channel_id in channels) or len(channels) != len(set(channels)):
        raise ValueError("merged TR guide contains empty or duplicate channel ids")
    known = set(channels)
    if any(programme.get("channel") not in known for programme in checked.findall("programme")):
        raise ValueError("merged TR guide has invalid programme references")
    if any(not is_published_id(channel_id) for channel_id in channels if channel_id):
        raise ValueError("merged TR guide contains a non-Turkish channel id")
    return len(channels), len(checked.findall("programme")), choices, collisions


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
    merge.add_argument("--source", action="append", required=True, metavar="NAME=GUIDE[,CATALOG]")
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--occupied-guide", action="append", type=Path, default=[])
    merge.add_argument("--canonical-guide", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command == "select":
        print(select_channels(args.catalog, args.output, covered_guides=args.covered_guide))
        return 0
    sources = [parse_source(value) for value in args.source]
    occupied = collect_occupied(args.occupied_guide)
    previous = [path for path in args.canonical_guide if path.is_file()]
    channels, programmes, choices, collisions = write_merged(sources, args.output, occupied, previous)
    by_source: dict[str, int] = defaultdict(int)
    for meta in choices.values():
        by_source[meta["identity_source"]] += 1
    print(
        f"Turkish guide: {channels} channels, {programmes} programmes; "
        f"sources {dict(by_source)}; collisions rewritten {len(collisions)}"
    )
    for row in collisions:
        print(f"collision: {row['original_id']} -> {row['rewritten_id']} ({row['name']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"Turkish EPG failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
