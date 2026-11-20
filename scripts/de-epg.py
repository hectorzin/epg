#!/usr/bin/env python3
"""Select German channels and merge XMLTV guides (Magenta TV > Magenta web > TV Heute > EPGShare extras)."""
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
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from es_xtream_policy import denied_xtream_clone_ids, is_forbidden_channel_id  # noqa: E402
from xmltv_channel import normalize_channels_in_tree  # noqa: E402
from xtream_matching import normalize_channel_name  # noqa: E402

IDENTITIES_PATH = _ROOT / "epg" / "de-magenta-identities.json"
VANISHED_TITLES = {
    "channel no longer available",
    "this channel is no longer available",
    "channel no longer exists",
    "sendepause",
}
TIMESHIFT_RE = re.compile(r"(?:\+\s*1|plus\s*1|\+1)", re.IGNORECASE)
QUALITY_WORDS = re.compile(
    r"\b(?:full\s*hd|fhd|uhd|4k|hd|sd|hevc|h265|h264|1080p|720p)\b",
    re.IGNORECASE,
)
TRAILING_MARK = re.compile(r"(?:\s*\*+\s*[A-Za-z]?)+\s*$")
ID_RE = re.compile(r"^[^\s<>\"']+$")
NUMERIC_ID_RE = re.compile(r"^\d+$")
SOURCE_PRIORITY = {"magenta": 4, "magentaweb": 3, "tvheute": 2, "epgshare": 1}
COLLISION_FEED = "Germany"
# Same physical station published in another national guide (currently ES).
SHARED_XMLTV_IDS = frozenset({"Rally.TV.de"})
# Panel ids that the German bouquet attaches to a different station.
INCORRECT_IDS = frozenset(
    {
        "deutschewelle.de",
        "rheinneckarfernsehen.de",
        "kabeleinsclassic.de",
        "skycinemapremieren.de",
        "skysport3.de",
        "vox.de",
        "n24doku.de",
        "ardalpha.de",
        "rbb.de",
        "universal.de",
    }
)
# Same Magenta station, published under a collision suffix while tvheute held the
# canonical id. Super RTL's canonical id is occupied, so its mint SuperRTL.de@SD
# moves to RTLSuper.de@Germany. A pair is accepted only when both names are the
# same station and the destination has real programmes.
CANONICAL_ID_MIGRATIONS = {
    "DisneyChannel.de@Germany": "DisneyChannel.de@SD",
    "SWRFernsehenBadenWurttemberg.de@Germany": "SWRFernsehenBadenWurttemberg.de@SD",
    "SkyCinemaPremieren.de@Germany": "SkyCinemaPremieren.de@SD",
    "SkySport1.de@Germany": "SkySport1.de@SD",
    "SkySportBundesliga1.de@Germany": "SkySportBundesliga1.de@SD",
    "SuperRTL.de@SD": "RTLSuper.de@Germany",
    "hrfernsehen.de@Germany": "hrfernsehen.de@SD",
}
# Spelling and rebrand pairs. Applied to the whole station key, never as a substring.
STATION_ALIASES = {
    "kabel1": "kabeleins",
    "kabel1kabeleins": "kabeleins",
    "kabel1doku": "kabeleinsdoku",
    "rtl2": "rtlzwei",
    "rtlzwei": "rtlzwei",
    "pro7": "prosieben",
    "prosieben": "prosieben",
    "pro7maxx": "prosiebenmaxx",
    "natgeo": "nationalgeographic",
    "natgeowild": "nationalgeographicwild",
    "warnerseries": "warnertvserie",
    "warnerserie": "warnertvserie",
    "warnerfilm": "warnertvfilm",
    "warnercomedy": "warnertvcomedy",
    "warnerstvserie": "warnertvserie",
    "eentertainment": "e",
    "thehistorychannel": "history",
    "historychannel": "history",
    "daserste": "daserste",
    "ard": "daserste",
    "boomerang": "cartoonito",
    "cartoonito": "cartoonito",
    "skyone": "sky1",
    "sky1": "sky1",
    "automotorsport": "automotorundsport",
    "toggoplustv": "toggoplus",
    "heimatkanaltv": "heimatkanal",
    "motorvisiontv": "motorvision",
    "nicktoonssky": "nicktoons",
    "n24": "welt",
    "welt": "welt",
}


def presentation(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").strip()
    text = re.sub(r"^#(?!#)", "", text).strip()
    text = re.sub(r"^DE\s+", "", text, flags=re.IGNORECASE).strip()
    return TRAILING_MARK.sub("", text).strip()


def station_key(title: str) -> str:
    base = QUALITY_WORDS.sub(" ", presentation(title))
    base = re.sub(r"\[[^\]]*\]", " ", base)
    base = re.sub(r"\*+", " ", base)
    key = normalize_channel_name(base)
    return STATION_ALIASES.get(key, key)


def is_timeshift(title: str) -> bool:
    return bool(TIMESHIFT_RE.search(presentation(title)))


def identity_key(name: str) -> tuple:
    return (station_key(name), 1 if is_timeshift(name) else 0)


def id_token(channel_id: str) -> str:
    stem = (channel_id or "").strip().split("@", 1)[0]
    stem = re.sub(r"\.(?:de|at)$", "", stem, flags=re.IGNORECASE)
    return stem


def is_incorrect_panel_id(channel_id: str | None) -> bool:
    return (channel_id or "").strip().casefold() in INCORRECT_IDS


def channel_tld(channel_id: str) -> str:
    stem = (channel_id or "").split("@", 1)[0]
    if "." not in stem:
        return ""
    return stem.rsplit(".", 1)[-1].casefold()


def austria_feed_ok(name: str) -> bool:
    station = station_key(name)
    return station == "servustv" or station.startswith("orf")


def is_strong_id(channel_id: str) -> bool:
    if not channel_id or not ID_RE.fullmatch(channel_id) or is_forbidden_channel_id(channel_id):
        return False
    if NUMERIC_ID_RE.fullmatch(channel_id) or is_incorrect_panel_id(channel_id):
        return False
    return channel_tld(channel_id) in {"de", "at"}


def foreign_feed(channel_id: str, name: str) -> bool:
    tld = channel_tld(channel_id)
    if tld in {"", "de"}:
        return False
    if tld == "at" and austria_feed_ok(name):
        return False
    return True


def mint_id(name: str) -> str:
    text = QUALITY_WORDS.sub(" ", presentation(name))
    text = TIMESHIFT_RE.sub(" ", text)
    words = re.findall(r"[A-Za-z0-9]+", text)
    pretty = "".join(
        word if word.isupper() and len(word) > 1 else word[:1].upper() + word[1:]
        for word in words
        if word
    )
    candidate = f"{pretty}.de@SD" if pretty else ""
    if candidate and ID_RE.fullmatch(candidate) and not is_incorrect_panel_id(candidate):
        return candidate
    slug = station_key(name) or "channel"
    return f"de.{slug}"


def vanished_title(title: str | None) -> bool:
    return (title or "").strip().casefold() in VANISHED_TITLES


def accepts_channel(channel_id: str, name: str) -> bool:
    if not channel_id or is_forbidden_channel_id(channel_id):
        return False
    return not foreign_feed(channel_id, name)


def parse_xmltv(path: Path) -> ET.Element:
    root = ET.parse(path).getroot()
    if root.tag != "tv":
        raise ValueError(f"{path}: expected <tv> root")
    return root


def channel_name(channel: ET.Element) -> str:
    for node in channel.findall("display-name"):
        text = (node.text or "").strip()
        if text:
            return text
    text = "".join(channel.itertext()).strip()
    return text


def empty_identities() -> dict[str, dict[str, str]]:
    return {"site_ids": {}, "stations": {}}


def load_verified_identities(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = path or IDENTITIES_PATH
    identities = empty_identities()
    if not path.is_file():
        return identities
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: identities file must be an object")
    for bucket in ("site_ids", "stations"):
        raw = data.get(bucket) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: {bucket} must be an object")
        cleaned: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if not is_strong_id(value) or foreign_feed(value, key):
                continue
            cleaned[key] = value
        identities[bucket] = cleaned
    return identities


def iter_catalog_channels(path: Path) -> list[ET.Element]:
    if not path.is_file():
        return []
    return ET.parse(path).getroot().findall("channel")


def compile_identities(
    magenta_catalog: Path,
    web_catalog: Path,
    grabs: list[Path] | None = None,
) -> dict[str, dict[str, str]]:
    """Map Magenta numeric site ids to one web.magentatv.de XMLTV id per station.

    Grabs are accepted for CLI compatibility and are not used: a numeric id is
    verified only when the public web catalog has exactly one XMLTV id for that
    station name. Other channels keep a stable minted id at merge time.
    """
    del grabs
    stations: dict[str, str] = {}
    web_ids: dict[str, set[str]] = defaultdict(set)
    for channel in iter_catalog_channels(web_catalog):
        name = channel_name(channel)
        xmltv_id = (channel.get("xmltv_id") or "").strip()
        station = station_key(name)
        if not station or not xmltv_id or not is_strong_id(xmltv_id):
            continue
        if foreign_feed(xmltv_id, name):
            continue
        web_ids[station].add(xmltv_id)
    for station, ids in web_ids.items():
        if len(ids) == 1:
            stations[station] = next(iter(ids))
    site_ids: dict[str, str] = {}
    for channel in iter_catalog_channels(magenta_catalog):
        site_id = (channel.get("site_id") or "").strip()
        station = station_key(channel_name(channel))
        if site_id and station in stations:
            site_ids[site_id] = stations[station]
    return {"site_ids": site_ids, "stations": stations}


def published_for(
    channel_id: str,
    name: str,
    identities: dict[str, dict[str, str]],
) -> tuple[str, str]:
    site_ids = identities.get("site_ids") or {}
    stations = identities.get("stations") or {}
    if NUMERIC_ID_RE.fullmatch(channel_id) and channel_id in site_ids:
        return site_ids[channel_id], "catalog"
    if is_strong_id(channel_id) and not foreign_feed(channel_id, name):
        return channel_id, "native"
    station = station_key(name)
    mapped = stations.get(station) if station else None
    if mapped and is_strong_id(mapped) and not foreign_feed(mapped, name):
        return mapped, "catalog"
    return mint_id(name), "mint"


def programme_richness(programme: ET.Element) -> int:
    score = 0
    if (programme.findtext("title") or "").strip():
        score += 1
    if (programme.findtext("desc") or "").strip():
        score += 3
    if any((node.text or "").strip() for node in programme.findall("category")):
        score += 1
    if programme.find("icon") is not None or programme.find("image") is not None:
        score += 1
    return score


def score_channel(programmes: list[ET.Element], source: str) -> tuple[int, int, int]:
    titled = [
        programme
        for programme in programmes
        if (programme.findtext("title") or "").strip() and not vanished_title(programme.findtext("title"))
    ]
    if not titled:
        return (0, 0, SOURCE_PRIORITY.get(source, 0))
    days = {(programme.get("start") or "")[:8] for programme in titled if programme.get("start")}
    starts = [programme.get("start") for programme in titled]
    duplicates = len(starts) - len(set(starts))
    richness = sum(programme_richness(programme) for programme in titled)
    score = len(titled) * 4 + len(days) * 80 + richness - duplicates * 6
    return (score, SOURCE_PRIORITY.get(source, 0), len(titled))


def preferred_id(candidates: list[tuple[str, str, dict]]) -> str:
    durable = [
        item
        for item in candidates
        if item[2].get("kind") in {"catalog", "native"} and is_strong_id(item[0])
    ]
    if durable:
        durable.sort(key=lambda item: (-SOURCE_PRIORITY.get(item[1], 0), item[0]))
        return durable[0][0]
    best = max(candidates, key=lambda item: SOURCE_PRIORITY.get(item[1], 0))
    return mint_id(best[2]["name"])


def prepared_channels(groups: dict[tuple, list[dict]]) -> list[dict]:
    """One viable row per station, with the id its highest-priority source would publish."""
    rows = []
    for key, entries in groups.items():
        viable = [
            entry
            for entry in entries
            if score_channel(entry["programmes"], entry["source"])[0] > 0
        ]
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
            (entry["published_id"], entry["source"], {"name": entry["name"], "kind": entry["kind"]})
            for entry in viable
        ]
        rows.append(
            {
                "key": key,
                "viable": viable,
                "winner": winner,
                "programmes": programmes,
                "contrib": contrib,
                "desired": preferred_id(candidates),
                "kind": winner["kind"],
                "priority": SOURCE_PRIORITY.get(winner["source"], 0),
                "score": score_channel(winner["programmes"], winner["source"])[0],
            }
        )
    return rows


def strong_id_owners(rows: list[dict]) -> dict[str, dict]:
    """The highest-priority station keeps a canonical id already covered by an earlier source.

    A later source that merely repeats that xmltv id, under another display name, does not
    become a second channel and does not take the id. Two stations from the same source
    that resolve to one id both stay published; the catalog mapping keeps the canonical id.
    """
    kind_rank = {"catalog": 2, "native": 1, "mint": 0}
    owners: dict[str, dict] = {}
    for row in rows:
        desired = row["desired"]
        if not is_strong_id(desired):
            continue
        current = owners.get(desired)
        rank = (row["priority"], kind_rank.get(row["kind"], 0), row["score"], row["key"])
        current_rank = (
            (current["priority"], kind_rank.get(current["kind"], 0), current["score"], current["key"])
            if current is not None
            else None
        )
        if current_rank is None or rank > current_rank:
            owners[desired] = row
    return owners


def avoid_collision(channel_id: str, occupied: set[str], name: str) -> str:
    if channel_id in SHARED_XMLTV_IDS:
        return channel_id
    usable = (
        channel_id not in occupied
        and not NUMERIC_ID_RE.fullmatch(channel_id)
        and not is_incorrect_panel_id(channel_id)
    )
    if usable:
        return channel_id
    if "@" in channel_id:
        base = channel_id.split("@", 1)[0]
        rewritten = f"{base}@{COLLISION_FEED}"
        if (
            rewritten not in occupied
            and rewritten != channel_id
            and ID_RE.fullmatch(rewritten)
            and not is_incorrect_panel_id(rewritten)
        ):
            return rewritten
    minted = mint_id(name)
    if minted not in occupied and not is_incorrect_panel_id(minted):
        return minted
    slug = station_key(name) or "channel"
    fallback = f"de.{slug}"
    suffix = 2
    while fallback in occupied or not ID_RE.fullmatch(fallback):
        fallback = f"de.{slug}{suffix}"
        suffix += 1
    return fallback


def fill_programmes(entries: list[dict]) -> tuple[list[ET.Element], dict[str, int]]:
    ordered = sorted(entries, key=lambda entry: SOURCE_PRIORITY.get(entry["source"], 0), reverse=True)
    by_start: dict[str, ET.Element] = {}
    contrib: Counter = Counter()
    for entry in ordered:
        for programme in entry["programmes"]:
            start = programme.get("start") or ""
            if not start or start in by_start:
                continue
            by_start[start] = programme
            contrib[entry["source"]] += 1
    programmes = [by_start[start] for start in sorted(by_start)]
    return programmes, dict(contrib)


def programmed_channel_names(guide_paths: list[Path]) -> tuple[set[str], set[tuple]]:
    ids: set[str] = set()
    identities: set[tuple] = set()
    for path in guide_paths:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        root = parse_xmltv(path)
        programmed = {
            programme.get("channel")
            for programme in root.findall("programme")
            if (programme.findtext("title") or "").strip()
        }
        for channel in root.findall("channel"):
            channel_id = channel.get("id") or ""
            if channel_id not in programmed:
                continue
            ids.add(channel_id.casefold())
            label = channel_name(channel) or channel_id
            key = identity_key(label)
            if key[0]:
                identities.add(key)
    return ids, identities


def canonical_hints_from_guide(path: Path) -> dict[tuple, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    root = parse_xmltv(path)
    programmed = {
        programme.get("channel")
        for programme in root.findall("programme")
        if (programme.findtext("title") or "").strip()
    }
    hints: dict[tuple, str] = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if channel_id not in programmed:
            continue
        key = identity_key(channel_name(channel) or channel_id)
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
    covered_ids, covered_identities = programmed_channel_names(covered_guides or [])
    selected = ET.Element("channels")
    seen: set[str] = set()
    seen_identities: set[tuple] = set()
    for channel in root.findall("channel"):
        site_id = (channel.get("site_id") or "").strip()
        xmltv_id = (channel.get("xmltv_id") or "").strip()
        name = channel_name(channel)
        key = identity_key(name)
        if not key[0]:
            continue
        if foreign_feed(xmltv_id or site_id, name):
            continue
        if (xmltv_id and xmltv_id.casefold() in covered_ids) or key in covered_identities:
            continue
        if key in seen_identities:
            continue
        identity = site_id or xmltv_id or name
        if identity in seen:
            continue
        seen.add(identity)
        seen_identities.add(key)
        node = ET.SubElement(selected, "channel", channel.attrib)
        node.text = channel.text
        node.tail = channel.tail
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(selected, space="    ")
    ET.ElementTree(selected).write(output, encoding="utf-8", xml_declaration=True)
    return len(seen)


def merge_guides(
    sources: list[tuple[str, Path, Path | None]],
    occupied: set[str],
    canonical_hints: dict[tuple, str] | None = None,
    identities: dict[str, dict[str, str]] | None = None,
) -> tuple[ET.Element, dict[str, dict], list[dict]]:
    canonical_hints = canonical_hints or {}
    identities = identities if identities is not None else load_verified_identities()
    groups: dict[tuple, list[dict]] = defaultdict(list)
    collisions: list[dict] = []

    for source_name, guide_path, _catalog_path in sources:
        if not guide_path.is_file() or guide_path.stat().st_size == 0:
            continue
        root = parse_xmltv(guide_path)
        channels = {channel.get("id"): channel for channel in root.findall("channel") if channel.get("id")}
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
            name = channel_name(channel) or channel_id
            if not accepts_channel(channel_id, name):
                continue
            key = identity_key(name)
            if not key[0]:
                continue
            published_id, kind = published_for(channel_id, name, identities)
            groups[key].append(
                {
                    "source": source_name,
                    "channel": channel,
                    "name": name,
                    "published_id": published_id,
                    "kind": kind,
                    "programmes": programmes.get(channel_id, []),
                }
            )

    result = ET.Element("tv")
    used_ids: set[str] = set()
    source_choice: dict[str, dict] = {}
    rows = prepared_channels(groups)
    owners = strong_id_owners(rows)
    for row in sorted(rows, key=lambda item: (-item["priority"], item["key"])):
        winner = row["winner"]
        desired = row["desired"]
        owner = owners.get(desired)
        if owner is not None and owner is not row and owner["priority"] > row["priority"]:
            collisions.append(
                {
                    "name": winner["name"],
                    "original_id": desired,
                    "rewritten_id": "dropped",
                    "source": winner["source"],
                    "kept_by": owner["winner"]["name"],
                }
            )
            continue
        reserved = set(used_ids)
        if owner is not None and owner is not row:
            reserved.add(desired)
            channel_id = mint_id(winner["name"])
        else:
            channel_id = desired
        # Stale hints must not move a priority source off the canonical id, nor
        # hand that id to the abbreviation that previously stole it.
        if not is_strong_id(channel_id):
            hinted = canonical_hints.get(row["key"])
            hint_owner = owners.get(hinted) if hinted else None
            if (
                hinted
                and hinted not in used_ids
                and ID_RE.fullmatch(hinted)
                and not is_incorrect_panel_id(hinted)
                and hint_owner in (None, row)
            ):
                channel_id = hinted
        original_id = channel_id
        channel_id = avoid_collision(channel_id, occupied | reserved, winner["name"])
        if original_id in occupied or is_incorrect_panel_id(original_id) or NUMERIC_ID_RE.fullmatch(original_id or ""):
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
            or is_incorrect_panel_id(channel_id)
            or is_forbidden_channel_id(channel_id)
        ):
            raise ValueError(f"invalid DE channel id for {winner['name']}: {channel_id!r}")
        used_ids.add(channel_id)
        source_choice[channel_id] = {
            "identity_source": winner["source"],
            "contrib": row["contrib"],
            "name": winner["name"],
            "original_id": original_id,
            "station": row["key"][0],
        }
        node = copy.deepcopy(winner["channel"])
        node.set("id", channel_id)
        display = node.find("display-name")
        if display is None:
            display = ET.Element("display-name")
            node.insert(0, display)
        display.text = winner["name"]
        result.append(node)
        for programme in row["programmes"]:
            cloned = copy.deepcopy(programme)
            cloned.set("channel", channel_id)
            result.append(cloned)
    if not result.findall("programme"):
        raise ValueError("no German programmes were generated")
    normalize_channels_in_tree(result)
    return result, source_choice, collisions


def write_merged(
    sources: list[tuple[str, Path, Path | None]],
    output: Path,
    occupied: set[str],
    canonical_hints: dict[tuple, str] | None = None,
    identities: dict[str, dict[str, str]] | None = None,
) -> tuple[int, int, dict[str, dict], list[dict]]:
    merged, source_choice, collisions = merge_guides(
        sources, occupied, canonical_hints, identities
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged, space="  ")
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    checked = parse_xmltv(output)
    channels = [channel.get("id") for channel in checked.findall("channel")]
    if any(not channel_id for channel_id in channels) or len(channels) != len(set(channels)):
        raise ValueError("merged DE guide contains empty or duplicate channel ids")
    channel_ids = set(channels)
    programmes = checked.findall("programme")
    if any(programme.get("channel") not in channel_ids for programme in programmes):
        raise ValueError("merged DE guide has invalid programme references")
    return len(channels), len(programmes), source_choice, collisions


def parse_source(value: str) -> tuple[str, Path, Path | None]:
    name, sep, rest = value.partition("=")
    if not sep or not name:
        raise ValueError(f"invalid --source value: {value}")
    if "," in rest:
        guide, catalog = rest.split(",", 1)
        return name, Path(guide), Path(catalog) if catalog else None
    return name, Path(rest), None


def write_identities(path: Path, identities: dict[str, dict[str, str]]) -> None:
    payload = {
        "site_ids": dict(sorted(identities.get("site_ids", {}).items())),
        "stations": dict(sorted(identities.get("stations", {}).items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    merge.add_argument("--identities", type=Path, default=IDENTITIES_PATH)
    identities_cmd = sub.add_parser("identities")
    identities_cmd.add_argument("--magenta-catalog", type=Path, required=True)
    identities_cmd.add_argument("--web-catalog", type=Path, required=True)
    identities_cmd.add_argument("--grab", action="append", type=Path, default=[])
    identities_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "select":
        count = select_channels(args.catalog, args.output, covered_guides=args.covered_guide)
        print(count)
        return 0
    if args.command == "identities":
        compiled = compile_identities(args.magenta_catalog, args.web_catalog, args.grab)
        write_identities(args.output, compiled)
        print(
            f"Verified identities: {len(compiled['site_ids'])} site ids, "
            f"{len(compiled['stations'])} stations -> {args.output}"
        )
        return 0
    sources = [parse_source(value) for value in args.source]
    occupied = collect_occupied(args.occupied_guide)
    hints: dict[tuple, str] = {}
    for guide in args.canonical_guide:
        for key, channel_id in canonical_hints_from_guide(guide).items():
            hints.setdefault(key, channel_id)
    identities = load_verified_identities(args.identities)
    channels, programmes, choices, collisions = write_merged(
        sources, args.output, occupied, hints or None, identities
    )
    by_source: dict[str, int] = defaultdict(int)
    for meta in choices.values():
        by_source[meta["identity_source"]] += 1
    print(
        f"German guide: {channels} channels, {programmes} programmes; "
        f"sources {dict(by_source)}; collisions rewritten {len(collisions)}"
    )
    for row in collisions:
        print(f"collision: {row['original_id']} -> {row['rewritten_id']} ({row['name']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"German EPG failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
