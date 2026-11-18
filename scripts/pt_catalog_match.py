#!/usr/bin/env python3
"""Portuguese IPTVnator catalog matching helpers (display aliases + panel cores)."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from xtream_matching import build_guide_indexes, normalize_channel_name, resolve_row

PT_PREFIX = re.compile(r"^\s*PT\s+", re.IGNORECASE)
VIP_RE = re.compile(r"\bVIP\b", re.IGNORECASE)
SAFE_KINDS = {
    "exact_id",
    "exact_id_casefold",
    "exact_stem",
    "stem_quality",
    "panel_core",
    "panel_core_quality",
    "display_name",
    "display_name_quality",
}

BRAND_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("eleven_sports", re.compile(r"^eleven\s+sports?\s*(\d+)\b", re.I), "DAZN {n}"),
    ("fox_comedy", re.compile(r"^fox\s+comedy\b", re.I), "STAR Comedy"),
    ("fox_crime", re.compile(r"^fox\s+crime\b", re.I), "STAR Crime"),
    ("fox_life", re.compile(r"^fox\s+life\b", re.I), "STAR Life"),
    ("fox_movies", re.compile(r"^fox\s+movies\b", re.I), "STAR Movies"),
    ("fox_main", re.compile(r"^fox\b", re.I), "STAR Channel"),
    (
        "star_main",
        re.compile(r"^star(?:\s+channel)?(?:\s+(?:hd|sd|4k|uhd|fhd))?$", re.I),
        "STAR Channel",
    ),
    ("natgeo_wild", re.compile(r"^nat(?:ional)?\s*geo(?:graphic)?\s+wild\b", re.I), "National Geographic Wild"),
    ("natgeo", re.compile(r"^nat(?:ional)?\s*geo(?:graphic)?\b", re.I), "National Geographic"),
    ("rtp3", re.compile(r"^rtp\s*3\b", re.I), "RTP Notícias"),
    ("benfica", re.compile(r"^benfica\b", re.I), "BTV"),
    ("tvi24", re.compile(r"^tvi\s*24\b", re.I), "CNN Portugal"),
    ("boomerang", re.compile(r"^boomerang\b", re.I), "Cartoonito"),
    ("biggs", re.compile(r"^biggs\b", re.I), "VinTV"),
]


def is_portuguese_market(channel_id: str) -> bool:
    cid = channel_id or ""
    stem = cid.split("@", 1)[0]
    feed = cid.split("@", 1)[1] if "@" in cid else ""
    if stem.casefold().endswith(".br") or feed.casefold() == "brazil":
        return False
    if stem.endswith(".pt"):
        return True
    if feed.casefold() in {"portugal", "europe"}:
        return True
    return False


PT_OPERATOR_SOURCES = frozenset({"meo", "nostv", "vodafone", "tvi"})

CATALOG_MATCH_TITLES: dict[str, str] = {
    "ftv": "Fashion TV",
    "bbc world news": "BBC World News",
    "zap viva 4k": "ZAP Viva",
    "zap viva hd": "ZAP Viva",
}


def catalogue_resolve_title(match_name: str) -> str:
    key = match_name.strip().casefold()
    return CATALOG_MATCH_TITLES.get(key, match_name)


def clean_catalog_row(row: dict) -> dict:
    epg = (row.get("epg_id") or "").strip()
    if not epg or epg.upper() == "NULL":
        epg = None
    name = row["name"]
    match_name = PT_PREFIX.sub("", name).strip()
    return {
        "xtream_id": row.get("xtream_id"),
        "name": name,
        "match_name": match_name,
        "epg_id": epg,
        "vip": bool(VIP_RE.search(name)),
    }


def apply_brand_alias(match_name: str) -> tuple[str | None, str | None]:
    for _rule_id, pattern, template in BRAND_RULES:
        found = pattern.search(match_name)
        if not found:
            continue
        if "{n}" in template:
            number = found.group(1)
            if _rule_id == "eleven_sports" and number.isdigit() and int(number) > 5:
                return None, None
            return _rule_id, template.format(n=number)
        return _rule_id, template
    return None, None


def load_guide_match_context(guide_path: Path) -> tuple[set[str], dict[str, list[str]], set[str]]:
    root = ET.parse(guide_path).getroot()
    names: dict[str, list[str]] = {}
    programmed: set[str] = set()
    channel_ids: set[str] = set()
    titled_channels = {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip() and p.get("channel")
    }
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if not channel_id or channel_id not in titled_channels:
            continue
        channel_ids.add(channel_id)
        names[channel_id] = [
            node.text.strip() for node in channel.findall("display-name") if (node.text or "").strip()
        ]
        programmed.add(channel_id)
    return channel_ids, names, programmed


def match_catalog_row(
    row: dict,
    title: str,
    channel_ids: set[str],
    names: dict[str, list[str]],
    programmed: set[str],
    *,
    use_catalog_title: bool = False,
) -> tuple[str | None, str | None, bool]:
    if use_catalog_title:
        title = catalogue_resolve_title(title)
    stems, name_index, cores = build_guide_indexes(channel_ids, names)
    guide_id, _, kind = resolve_row(
        title=title,
        panel_epg_id=row["epg_id"],
        stream_id=str(row["xtream_id"]),
        channel_ids=channel_ids,
        stem_index=stems,
        name_index=name_index,
        panel_core_index=cores,
        allow_stream_clone=False,
    )
    ok = bool(guide_id and guide_id in programmed and kind in SAFE_KINDS)
    return guide_id, kind, ok


def resolve_catalog_row(
    row: dict,
    channel_ids: set[str],
    names: dict[str, list[str]],
    programmed: set[str],
) -> tuple[str | None, str]:
    titles = [
        catalogue_resolve_title(row["match_name"]),
        row["match_name"],
        catalogue_resolve_title(row["match_name"]).replace(" ", ""),
    ]
    seen: set[str] = set()
    for title in titles:
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        guide_id, _, ok = match_catalog_row(
            row, title, channel_ids, names, programmed, use_catalog_title=False
        )
        if ok and guide_id:
            return guide_id, "direct"
    rule_id, alias = apply_brand_alias(row["match_name"])
    if rule_id and alias:
        alias_row = {**row, "epg_id": None}
        guide_id, _, ok = match_catalog_row(alias_row, alias, channel_ids, names, programmed)
        if ok and guide_id and is_portuguese_market(guide_id):
            return guide_id, f"brand:{rule_id}"
    return None, "unresolved"


def panel_clone_key(epg_id: str) -> str:
    return epg_id.strip().split("@", 1)[0].casefold()


def build_mappings_from_guide(
    catalog_rows: list[dict],
    guide_path: Path,
) -> tuple[dict[str, list[str]], dict[str, str], set[int]]:
    channel_ids, names, programmed = load_guide_match_context(guide_path)
    aliases: dict[str, list[str]] = {}
    clones: dict[str, str] = {}
    covered_indexes: set[int] = set()
    for index, raw in enumerate(catalog_rows):
        row = clean_catalog_row(raw)
        if row["vip"]:
            continue
        guide_id, _status = resolve_catalog_row(row, channel_ids, names, programmed)
        if not guide_id:
            continue
        covered_indexes.add(index)
        bucket = aliases.setdefault(guide_id, [])
        if row["name"] not in bucket:
            bucket.append(row["name"])
        if row["epg_id"]:
            key = panel_clone_key(row["epg_id"])
            stem = guide_id.split("@", 1)[0].casefold()
            if key != stem and key not in clones:
                clones[key] = guide_id
    return aliases, clones, covered_indexes


def load_catalog_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected JSON array of catalog rows")
    return data


def _trial_guide_context(path: Path) -> tuple[set[str], dict[str, list[str]], set[str]]:
    root = ET.parse(path).getroot()
    channel_ids: set[str] = set()
    names: dict[str, list[str]] = {}
    programmed: set[str] = set()
    titled = {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip() and p.get("channel")
    }
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if not channel_id or channel_id not in titled:
            continue
        channel_ids.add(channel_id)
        names[channel_id] = [
            node.text.strip() for node in channel.findall("display-name") if (node.text or "").strip()
        ]
        programmed.add(channel_id)
    return channel_ids, names, programmed


def _identity_label(channel_id: str, names: dict[str, list[str]]) -> str:
    options = names.get(channel_id) or [channel_id]
    return options[0] if options else channel_id


def build_identity_index(
  guide_path: Path,
  identity_key,
) -> tuple[dict[tuple, str], dict[str, str]]:
    root = ET.parse(guide_path).getroot()
    by_identity: dict[tuple, str] = {}
    by_stem: dict[str, str] = {}
    titled = {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip() and p.get("channel")
    }
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if not channel_id or channel_id not in titled:
            continue
        label = _identity_label(
            channel_id,
            {
                channel_id: [
                    node.text.strip() for node in channel.findall("display-name") if (node.text or "").strip()
                ]
            },
        )
        display_names = [
            node.text.strip() for node in channel.findall("display-name") if (node.text or "").strip()
        ]
        if not display_names:
            display_names = [label]
        by_identity[identity_key(label)] = channel_id
        by_stem[channel_id.split("@", 1)[0].casefold()] = channel_id
        for display_name in display_names:
            by_stem.setdefault(normalize_channel_name(display_name), channel_id)
    return by_identity, by_stem


def map_source_id_to_merged(
    source_id: str,
    source_names: dict[str, list[str]],
    merged_by_identity: dict[tuple, str],
    merged_by_stem: dict[str, str],
    identity_key,
) -> str | None:
    label = _identity_label(source_id, source_names)
    merged = merged_by_identity.get(identity_key(label))
    if merged:
        return merged
    stem = source_id.split("@", 1)[0].casefold()
    if stem in merged_by_stem:
        return merged_by_stem[stem]
    hit = merged_by_stem.get(normalize_channel_name(label))
    if hit:
        return hit
    for merged_stem, merged_id in merged_by_stem.items():
        if "." in merged_stem or len(merged_stem) < 2:
            continue
        if merged_stem == stem:
            return merged_id
    return None


def resolve_collision_rewrite(merged_guide: Path, trial_id: str) -> str | None:
    if not trial_id or "@" not in trial_id:
        return None
    stem = trial_id.split("@", 1)[0]
    root = ET.parse(merged_guide).getroot()
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if channel_id.split("@", 1)[0].casefold() != stem.casefold():
            continue
        programmed = any(
            (programme.get("channel") == channel_id)
            and (programme.findtext("title") or "").strip()
            for programme in root.findall("programme")
        )
        if programmed:
            return channel_id
    return None


def build_mappings_from_trials(
    catalog_rows: list[dict],
    merged_guide: Path,
    trial_dir: Path,
    identity_key,
    source_priority: tuple[str, ...] = ("nostv.pt", "meo.pt", "vodafone.pt", "tvi.iol.pt"),
) -> tuple[dict[str, list[str]], dict[str, str], set[int]]:
    merged_by_identity, merged_by_stem = build_identity_index(merged_guide, identity_key)
    merged_ids, merged_names, merged_prog = load_guide_match_context(merged_guide)
    trials = {
        source: _trial_guide_context(trial_dir / f"{source}.xml") for source in source_priority
    }
    aliases: dict[str, list[str]] = {}
    clones: dict[str, str] = {}
    covered: set[int] = set()
    for index, raw in enumerate(catalog_rows):
        row = clean_catalog_row(raw)
        if row["vip"]:
            continue
        merged_id, _status = resolve_catalog_row(row, merged_ids, merged_names, merged_prog)
        if merged_id and merged_id in merged_ids:
            covered.add(index)
            bucket = aliases.setdefault(merged_id, [])
            if row["name"] not in bucket:
                bucket.append(row["name"])
            if row["epg_id"]:
                key = panel_clone_key(row["epg_id"])
                stem = merged_id.split("@", 1)[0].casefold()
                if key != stem and key not in clones:
                    clones[key] = merged_id
            continue
        merged_id = None
        for source in source_priority:
            channel_ids, names, programmed = trials[source]
            guide_id, _kind, ok = match_catalog_row(row, row["match_name"], channel_ids, names, programmed)
            if ok and guide_id and is_portuguese_market(guide_id):
                merged_id = map_source_id_to_merged(
                    guide_id, names, merged_by_identity, merged_by_stem, identity_key
                )
                if not merged_id or merged_id not in merged_ids:
                    merged_id = resolve_collision_rewrite(merged_guide, guide_id)
                if merged_id:
                    break
            rule_id, alias = apply_brand_alias(row["match_name"])
            if rule_id and alias:
                alias_row = {**row, "epg_id": None}
                guide_id, _, ok = match_catalog_row(alias_row, alias, channel_ids, names, programmed)
                if ok and guide_id and is_portuguese_market(guide_id):
                    merged_id = map_source_id_to_merged(
                        guide_id, names, merged_by_identity, merged_by_stem, identity_key
                    )
                    if not merged_id or merged_id not in merged_ids:
                        merged_id = resolve_collision_rewrite(merged_guide, guide_id)
                    if merged_id:
                        break
        if not merged_id or merged_id not in merged_ids:
            continue
        covered.add(index)
        bucket = aliases.setdefault(merged_id, [])
        if row["name"] not in bucket:
            bucket.append(row["name"])
        if row["epg_id"]:
            key = panel_clone_key(row["epg_id"])
            stem = merged_id.split("@", 1)[0].casefold()
            if key != stem and key not in clones:
                clones[key] = merged_id
    return aliases, clones, covered