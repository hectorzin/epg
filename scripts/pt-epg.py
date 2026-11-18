#!/usr/bin/env python3
"""Select Portuguese channels and merge XMLTV guides by quality, not first-source-wins."""
from __future__ import annotations

import argparse
import copy
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from pt_catalog_match import is_portuguese_market  # noqa: E402

VANISHED_TITLES = {
    "channel no longer available",
    "this channel is no longer available",
    "channel no longer exists",
}
PLUS1_RE = re.compile(r"(?:\+\s*1|plus\s*1|\bjavu\b|\bja\s*vu\b)", re.IGNORECASE)
TIMESHIFT_RE = re.compile(r"\+\s*(\d+)\b")
HD_RE = re.compile(r"\b(uhd|4k|fhd|full\s*hd|\bhd\b)", re.IGNORECASE)
TECHNICAL_RE = re.compile(
    r"(?:[\s._()\[\]-]*)(?:FULL[\s._-]*HD|FHD|UHD|HD|SD|4K|HEVC|H265|H264)[\s)\]]*$",
    re.IGNORECASE,
)
DAZN_NUM_RE = re.compile(r"\bdazn\s*(\d+)\b", re.IGNORECASE)
SPORTTV_NUM_RE = re.compile(r"\bsport\s*tv\s*(\+|\d+)\b", re.IGNORECASE)
SPORTS_NUM_RE = DAZN_NUM_RE
REGION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("acores", re.compile(r"\ba[cç]ores\b", re.IGNORECASE)),
    ("madeira", re.compile(r"\bmadeira\b", re.IGNORECASE)),
]
REGIONAL_HOST_RE = re.compile(r"\b(rtp|sic|tv)\b", re.IGNORECASE)
PLACEHOLDER_TITLES = {"sem emissão", "sem emissao"}
WEAK_ID_RE = re.compile(r"^[0-9]+$|[a-z0-9]+(?:-[a-z0-9]+)+$")
ID_RE = re.compile(r"^[^\s<>\"']+$")
SOURCE_PRIORITY = {"nostv": 4, "meo": 3, "vodafone": 2, "tvi": 1}
COLLISION_FEED = "Portugal"
GENERIC_SUFFIXES = {"news", "tv", "hd", "channel"}
FIVE_NOT_RE = re.compile(r"\b5\s*(usa|star|action|select)\b", re.IGNORECASE)
FIVE_BRAND_RE = re.compile(r"^(?:channel\s*)?5\b", re.IGNORECASE)
ABBREVIATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsky\s*sp(?:orts)?\b", re.IGNORECASE), "sky sports"),
    (re.compile(r"\bf['’]?ball\b", re.IGNORECASE), "football"),
    (re.compile(r"\bbox\s*off(?:ice)?\b", re.IGNORECASE), "box office"),
    (re.compile(r"\bmain\s*ev(?:ent)?\b", re.IGNORECASE), "main event"),
    (re.compile(r"\bdocmntrs\b", re.IGNORECASE), "documentaries"),
    (re.compile(r"\bdocumntrs\b", re.IGNORECASE), "documentaries"),
    (re.compile(r"\bcomedy\s*cent(?:ral)?\b", re.IGNORECASE), "comedy central"),
    (re.compile(r"\bdisc(?:overy)?\s+(history|science|sci|turbo)\b", re.IGNORECASE), r"discovery \1"),
    (re.compile(r"\bnetwrk\b", re.IGNORECASE), "network"),
    (re.compile(r"\bplnt\b", re.IGNORECASE), "planet"),
    (re.compile(r"\bnick\s*jr\b", re.IGNORECASE), "nick jr"),
    (re.compile(r"\bnat(?:ional)?\s*geo(?:graphic)?\b", re.IGNORECASE), "national geographic"),
    (re.compile(r"\ba\s*bola(?:\s*tv)?\b", re.IGNORECASE), "a bola"),
    (re.compile(r"^cn(?=\s*\+1|\s*$)", re.IGNORECASE), "cartoon network"),
    (re.compile(r"^nick(?!\s*jr|\s*toon)(?=\s|\+|hd|$)", re.IGNORECASE), "nickelodeon"),
    (re.compile(r"\brb\b", re.IGNORECASE), "red button"),
    (re.compile(r"\bu\s*and\s*gold\b", re.IGNORECASE), "gold"),
    (re.compile(r"\bsky sports\s+me\b", re.IGNORECASE), "sky sports main event"),
    (re.compile(r"^g(?:reat)?!(?=\s|$)", re.IGNORECASE), "great"),
]


def expand_name(name: str) -> str:
    original = unicodedata.normalize("NFKC", name or "")
    compact = re.sub(r"[^a-z0-9+]+", "", original.casefold())
    plus = " +1" if compact.endswith("+1") or compact.endswith("plus1") else ""
    if compact in {"id", "id+1"} or compact.startswith("id+"):
        return "Investigation Discovery" + plus
    value = re.sub(r"(?i)([A-Z0-9])(HD|SD|UHD|FHD|4K)$", r"\1 \2", original)
    value = re.sub(r"(?i)\bskysp", "Sky Sports ", value)
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    value = value.replace(".", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if FIVE_BRAND_RE.match(value) and not FIVE_NOT_RE.search(value):
        value = FIVE_BRAND_RE.sub("Channel 5", value, count=1)
    for pattern, replacement in ABBREVIATIONS:
        value = pattern.sub(replacement, value)
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
    region = ""
    if REGIONAL_HOST_RE.search(raw):
        for label, pattern in REGION_PATTERNS:
            if pattern.search(raw):
                region = label
                break
    sports = SPORTS_NUM_RE.search(raw)
    sporttv = SPORTTV_NUM_RE.search(raw)
    if sporttv:
        sports_family = "sporttv"
        sports_number = sporttv.group(1)
    else:
        sports_family = "dazn" if sports else ""
        sports_number = sports.group(1) if sports else ""
    stem_source = PLUS1_RE.sub(" ", raw)
    stem_source = TIMESHIFT_RE.sub(" ", stem_source)
    if region:
        stem_source = REGION_PATTERNS[[label for label, _ in REGION_PATTERNS].index(region)][1].sub(
            " ", stem_source
        )
    if sporttv:
        stem_source = SPORTTV_NUM_RE.sub(" ", stem_source)
    elif sports:
        stem_source = SPORTS_NUM_RE.sub(" ", stem_source)
    stem = normalise_text(stem_source)
    if not stem and sports_family == "dazn" and sports_number:
        stem = normalise_text(f"dazn{sports_number}")
    if not stem and sports_family == "sporttv" and sports_number:
        stem = normalise_text(f"sporttv{sports_number}")
    return {
        "stem": stem,
        "plus1": plus1 or timeshift == 1,
        "timeshift": timeshift,
        "region": region,
        "sports_family": sports_family,
        "sports_number": sports_number,
        "hd": bool(HD_RE.search(raw)),
    }


def identity_key(name: str) -> tuple:
    flags = parse_flags(name)
    return (
        flags["stem"],
        flags["timeshift"],
        flags["region"],
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
    if flags["plus1"] or flags["timeshift"] > 1:
        if "plus" not in xmltv_id.casefold() and "+1" not in xmltv_id.casefold():
            if flags["timeshift"] and str(flags["timeshift"]) not in xmltv_id:
                return False
    if flags["region"] and flags["region"] not in xmltv_id.casefold():
        return False
    return core in flags["stem"] or flags["stem"] in core


def is_strong_id(channel_id: str) -> bool:
    if not channel_id or not ID_RE.fullmatch(channel_id):
        return False
    if channel_id.startswith("UK1#") or channel_id.isdigit() or WEAK_ID_RE.fullmatch(channel_id):
        return False
    return "." in channel_id


def mint_id(name: str) -> str:
    flags = parse_flags(name)
    expanded = expand_name(name)
    cleaned = PLUS1_RE.sub(" ", expanded)
    cleaned = TIMESHIFT_RE.sub(" ", cleaned)
    cleaned = HD_RE.sub(" ", cleaned)
    cleaned = TECHNICAL_RE.sub(" ", cleaned)
    words = [word for word in re.findall(r"[A-Za-z0-9]+", cleaned) if word.casefold() not in {"sd", "hd"}]
    pretty = "".join(word if word.isupper() and len(word) > 1 else word.title() for word in words)
    if flags["sports_number"] and flags["sports_number"] not in pretty:
        pretty = f"{pretty}{flags['sports_number']}"
    feed: list[str] = []
    if flags["region"]:
        feed.append(str(flags["region"]).title())
    if flags["timeshift"] == 1:
        feed.append("Plus1")
    elif flags["timeshift"] > 1:
        feed.append(f"Plus{flags['timeshift']}")
    elif flags["hd"]:
        feed.append("HD")
    else:
        feed.append("SD")
    stem = flags["stem"] or "unknown"
    candidate = f"{pretty}.pt@{''.join(feed)}" if pretty else f"pt.{stem}"
    return candidate if ID_RE.fullmatch(candidate) else f"pt.{stem}"


def vanished_title(title: str | None) -> bool:
    return (title or "").strip().casefold() in VANISHED_TITLES


def placeholder_title(title: str | None) -> bool:
    value = (title or "").strip().casefold()
    if value in PLACEHOLDER_TITLES:
        return True
    return bool(re.fullmatch(r"dazn \d+", value))


BOUQUET_RELAY_STEMS = (
    "tveinternacional",
    "motorvision",
    "lollykids",
    "zapviva",
    "euronewsportuguese",
    "euronewspt",
    "bbcworld",
    "bbcn",
    "fashiontv",
)


def accepts_channel(channel_id: str, source: str) -> bool:
    if not channel_id:
        return False
    stem = channel_id.split("@", 1)[0]
    if stem.casefold().endswith(".br") or ".br@" in channel_id.casefold():
        return False
    if is_portuguese_market(channel_id):
        return True
    if source == "tvi":
        return ".pt" in channel_id.casefold()
    stem_fold = stem.casefold()
    if source in {"meo", "nostv", "vodafone", "tvi"}:
        if any(stem_fold.startswith(relay) for relay in BOUQUET_RELAY_STEMS):
            return True
    return False


def parse_xmltv(path: Path) -> ET.Element:
    root = ET.parse(path).getroot()
    if root.tag != "tv":
        raise ValueError(f"{path}: expected <tv> root")
    return root


def load_catalog(path: Path) -> dict[str, str]:
    """Map site_id and xmltv_id to display name, and site_id to xmltv_id."""
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
    real = [
        p
        for p in programmes
        if (p.findtext("title") or "").strip()
        and not vanished_title(p.findtext("title"))
        and not placeholder_title(p.findtext("title"))
    ]
    titled = real or [
        p
        for p in programmes
        if (p.findtext("title") or "").strip() and not vanished_title(p.findtext("title"))
    ]
    if not titled:
        return (0, 0, SOURCE_PRIORITY.get(source, 0))
    placeholder_penalty = 0 if real else len(titled) * 120
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
        - placeholder_penalty
    )
    return (score, SOURCE_PRIORITY.get(source, 0), len(real) or len(titled))


def preferred_id(candidates: list[tuple[str, str, dict]]) -> str:
    """candidates: (channel_id, source, flags-like dict with hd/name)."""
    strong = [
        item
        for item in candidates
        if is_strong_id(item[0]) and xmltv_agrees(item[0], item[2]["name"])
    ]
    if strong:
        strong.sort(key=lambda item: (not item[2].get("hd"), -SOURCE_PRIORITY.get(item[1], 0), item[0]))
        return strong[0][0]
    return mint_id(max(candidates, key=lambda item: SOURCE_PRIORITY.get(item[1], 0))[2]["name"])


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
    fallback = f"pt.{slug}"
    suffix = 2
    while fallback in occupied or not ID_RE.fullmatch(fallback):
        fallback = f"pt.{slug}{suffix}"
        suffix += 1
    return fallback


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
    return occupied


def select_channels(
    catalog: Path,
    output: Path,
    *,
    lang: str | None = None,
    site_id_prefix: str | None = None,
    covered_guides: list[Path] | None = None,
) -> int:
    root = ET.parse(catalog).getroot()
    covered_ids, covered_names, covered_identities = programmed_channel_names(covered_guides or [])
    selected = ET.Element("channels")
    seen: set[str] = set()
    for channel in root.findall("channel"):
        if lang and (channel.get("lang") or "").casefold() != lang.casefold():
            continue
        site_id = channel.get("site_id") or ""
        if site_id_prefix and not site_id.startswith(site_id_prefix):
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
) -> tuple[ET.Element, dict[str, str], list[dict[str, str]]]:
    canonical_hints = canonical_hints or {}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    collisions: list[dict[str, str]] = []

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
    source_choice: dict[str, str] = {}
    for key, entries in sorted(groups.items(), key=lambda item: item[0][0]):
        viable = [entry for entry in entries if score_channel(entry["programmes"], entry["source"])[0] > 0]
        if not viable:
            continue
        viable.sort(key=lambda entry: score_channel(entry["programmes"], entry["source"]), reverse=True)
        winner = viable[0]
        candidate_ids = [
            (entry["published_id"], entry["source"], {"name": entry["name"], "hd": entry["hd"]})
            for entry in viable
        ]
        channel_id = preferred_id(candidate_ids)
        hinted = canonical_hints.get(key)
        if hinted and hinted not in used_ids and ID_RE.fullmatch(hinted):
            hinted_allowed = hinted not in occupied or hinted == channel_id
            if hinted_allowed:
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
        if not channel_id or not ID_RE.fullmatch(channel_id) or channel_id in used_ids:
            raise ValueError(f"refusing empty, invalid or duplicate PT channel id for {winner['name']}")
        used_ids.add(channel_id)
        source_choice[channel_id] = winner["source"]
        node = copy.deepcopy(winner["channel"])
        node.set("id", channel_id)
        display = node.find("display-name")
        if display is None:
            display = ET.SubElement(node, "display-name")
        display.text = winner["name"]
        result.append(node)
        winner_programmes = [
            programme
            for programme in winner["programmes"]
            if not placeholder_title(programme.findtext("title"))
        ]
        if not winner_programmes:
            for entry in viable[1:]:
                winner_programmes = [
                    programme
                    for programme in entry["programmes"]
                    if not placeholder_title(programme.findtext("title"))
                ]
                if winner_programmes:
                    winner = entry
                    break
        for programme in winner_programmes:
            cloned = copy.deepcopy(programme)
            cloned.set("channel", channel_id)
            result.append(cloned)
    if not result.findall("programme"):
        raise ValueError("no Portuguese programmes were generated")
    return result, source_choice, collisions


def write_merged(
    sources: list[tuple[str, Path, Path | None]],
    output: Path,
    occupied: set[str],
    canonical_hints: dict[tuple, str] | None = None,
) -> tuple[int, int, dict[str, str], list[dict[str, str]]]:
    merged, source_choice, collisions = merge_guides(sources, occupied, canonical_hints)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space="  ")
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    checked = parse_xmltv(output)
    channels = {c.get("id") for c in checked.findall("channel")}
    if None in channels or "" in channels:
        raise ValueError("merged PT guide contains empty channel ids")
    programmes = checked.findall("programme")
    if any(p.get("channel") not in channels for p in programmes):
        raise ValueError("merged PT guide has invalid programme references")
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
    select.add_argument("--lang")
    select.add_argument("--site-id-prefix")
    select.add_argument("--covered-guide", action="append", type=Path, default=[])
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
    merge.add_argument(
        "--canonical-guide",
        action="append",
        type=Path,
        default=[],
        help="Reuse published channel IDs for matching logical channels",
    )
    args = parser.parse_args()
    if args.command == "select":
        count = select_channels(
            args.catalog,
            args.output,
            lang=args.lang,
            site_id_prefix=args.site_id_prefix,
            covered_guides=args.covered_guide,
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
    for source in choices.values():
        by_source[source] += 1
    print(
        f"Portuguese guide: {channels} channels, {programmes} programmes; "
        f"sources {dict(by_source)}; collisions rewritten {len(collisions)}"
    )
    for row in collisions:
        print(f"collision: {row['original_id']} -> {row['rewritten_id']} ({row['name']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"Portuguese EPG failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
