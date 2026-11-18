#!/usr/bin/env python3
"""Conservative Xtream catalog to XMLTV guide matching (no credentials)."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

ID_RE = re.compile(r"^[^\s<>\"']+$")
NULLS = {"null", "none", "undefined", ""}
QUALITY_4K = re.compile(r"\b(4k|uhd)\b", re.IGNORECASE)
QUALITY_HD = re.compile(r"(?:\bhd\b|ʜᴅ|full\s*hd|fhd)", re.IGNORECASE)
QUALITY_SD = re.compile(r"\bsd\b", re.IGNORECASE)
SECTION_HEADER = re.compile(r"^#{3,}")
FAKE_HD_CHARS = re.compile(r"[\u029c\u1d05\u1d2c\uff48\uff44]", re.IGNORECASE)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

COUNTRY_PREFIX_RE = re.compile(
    r"^\s*(?:\[(ES|FR|AR|GB|UK)\]\s*|(ES|FR|AR|GB|UK)\s*[:|/_-]\s*)",
    re.IGNORECASE,
)
TECHNICAL_SUFFIX_RE = re.compile(
    r"(?:[\s._()\[\]-]*)(?:FULL[\s._-]*HD|FHD|UHD|HD|SD|4K|HEVC|H265|H264)[\s)\]]*$",
    re.IGNORECASE,
)
TRAILING_FEED_NUMBER = re.compile(r"^(.*?)(?:\s+)(\d{1,2})$")


def classify_playlist_region(category: str) -> str | None:
    cat = category or ""
    if cat.startswith("[ES]"):
        return "ES"
    if cat.startswith("[FR]"):
        return "FR"
    if cat.startswith("[GB]") or cat.startswith("[UK]"):
        return "GB"
    if cat.startswith("[PR]") or cat.startswith("[PT]"):
        return "PT"
    if cat.startswith("[NL]"):
        return "NL"
    if cat.startswith("[IT]"):
        return "IT"
    if cat.startswith("[AR]") or "ARABIC" in cat.upper():
        return "ARABIC"
    return None


def channel_stem(channel_id: str) -> str:
    return re.sub(r"@[A-Za-z0-9]+$", "", channel_id or "").casefold()


def panel_core_key(epg_id: str) -> str:
    base = epg_id.strip().split("@", 1)[0]
    base = base.split(".", 1)[0]
    return normalize_channel_name(base)


def guide_core_key(channel_id: str) -> str:
    stem = channel_stem(channel_id)
    base = stem.split(".", 1)[0]
    return normalize_channel_name(base)


def normalize_channel_name(name: str) -> str:
    value = unicodedata.normalize("NFKD", name or "")
    value = value.translate(ARABIC_DIGITS)
    value = FAKE_HD_CHARS.sub("hd", value)
    value = "".join(c for c in value if not unicodedata.combining(c)).casefold().strip()
    while True:
        without_country = COUNTRY_PREFIX_RE.sub("", value).strip()
        if without_country == value:
            break
        value = without_country
    while True:
        without_suffix = TECHNICAL_SUFFIX_RE.sub("", value).strip()
        if without_suffix == value:
            break
        value = without_suffix
    value = re.sub(r"[^0-9a-z\u0600-\u06ff]+", "", value)
    return value


def name_lookup_keys(name: str, *, channel_id: str | None = None) -> set[str]:
    keys: set[str] = set()
    normalized = normalize_channel_name(name)
    if normalized:
        keys.add(normalized)
    raw = (name or "").casefold()
    if channel_id:
        core = guide_core_key(channel_id)
        if core:
            keys.add(core)

    stripped_hd = normalize_channel_name(re.sub(r"\bhd\b", "", raw, flags=re.IGNORECASE))
    if stripped_hd:
        keys.add(stripped_hd)

    without_feed = TRAILING_FEED_NUMBER.match((name or "").strip())
    if without_feed and any(
        token in raw for token in ("ecran", "cine", "cinema", "ligue", "plus", "feed", "event")
    ):
        base = normalize_channel_name(without_feed.group(1))
        if base:
            keys.add(base)

    if "grand" in raw and "ecran" in raw:
        keys.add("canalgrandecran")
    if "canal" in raw and "cine" in raw and "cinema" not in raw:
        keys.add("canalpluscine")
    if "ligue1" in raw and "plus" in raw:
        keys.add("ligue1plus")

    if "al jazeera" in raw or "aljazeera" in normalized:
        if "documentary" in raw:
            keys.add("aljazeeradocumentary")
        elif "mubasher" in raw and "2" in raw:
            keys.add("aljazeeramubasher2")
        elif "mubasher" in raw:
            keys.add("aljazeeramubasher")
        elif "english" in raw:
            keys.add("aljazeeraenglish")
        elif "2" in raw:
            keys.add("aljazeera2")
        elif QUALITY_HD.search(raw) and not any(token in raw for token in ("english", "documentary", "mubasher")):
            keys.add("aljazeeraarabic")
            keys.discard("aljazeera")
            keys.discard("aljazeerahd")

    compact = re.sub(r"\s+", "", raw)
    if compact != raw:
        compact_key = normalize_channel_name(compact)
        if compact_key:
            keys.add(compact_key)
    return keys


def valid_panel_epg_id(epg_id: str | None) -> bool:
    if epg_id is None:
        return False
    cleaned = epg_id.strip()
    if not cleaned or cleaned.casefold() in NULLS:
        return False
    if not ID_RE.fullmatch(cleaned):
        return False
    if cleaned.isdigit():
        return False
    return True


def build_guide_indexes(
    channel_ids: set[str],
    display_names: dict[str, list[str]],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    stem_index: dict[str, set[str]] = defaultdict(set)
    name_index: dict[str, set[str]] = defaultdict(set)
    panel_core_index: dict[str, set[str]] = defaultdict(set)
    for channel_id in channel_ids:
        stem_index[channel_stem(channel_id)].add(channel_id)
        core = guide_core_key(channel_id)
        if core:
            panel_core_index[core].add(channel_id)
        for name in display_names.get(channel_id, []):
            for key in name_lookup_keys(name, channel_id=channel_id):
                name_index[key].add(channel_id)
        for key in name_lookup_keys(channel_id, channel_id=channel_id):
            name_index[key].add(channel_id)
    return dict(stem_index), dict(name_index), dict(panel_core_index)


def disambiguate_by_quality(title: str, candidates: set[str]) -> str | None:
    if len(candidates) == 1:
        return next(iter(candidates))
    if len(candidates) < 2:
        return None
    title_cf = title.casefold()
    if QUALITY_4K.search(title_cf):
        subset = {c for c in candidates if "4k" in c.casefold() or "uhd" in c.casefold()}
        if len(subset) == 1:
            return next(iter(subset))
    if QUALITY_HD.search(title_cf):
        subset = {
            c
            for c in candidates
            if c.endswith("@SD")
            or "@HD" in c
            or ".hd" in c.casefold()
            or c.casefold().endswith("hd")
        }
        if len(subset) == 1:
            return next(iter(subset))
    if QUALITY_SD.search(title_cf):
        subset = {c for c in candidates if c.endswith("@SD")}
        if len(subset) == 1:
            return next(iter(subset))
    return None


def title_name_hits(title: str, name_index: dict[str, set[str]]) -> set[str]:
    hits: set[str] = set()
    for key in name_lookup_keys(title):
        hits |= name_index.get(key, set())
    return hits


def lookup_by_name(title: str, name_index: dict[str, set[str]]) -> tuple[str | None, str]:
    hits = title_name_hits(title, name_index)
    if not hits:
        return None, "no_match"
    if len(hits) == 1:
        return next(iter(hits)), "display_name"
    pick = disambiguate_by_quality(title, hits)
    if pick:
        return pick, "display_name_quality"
    return None, "ambiguous_name"


def pick_panel_core(
    pid: str,
    title: str,
    panel_core_index: dict[str, set[str]],
    name_index: dict[str, set[str]],
) -> tuple[str | None, str]:
    title_hits = title_name_hits(title, name_index)
    if not title_hits:
        return None, "no_match"
    core_hits = panel_core_index.get(panel_core_key(pid), set())
    if not core_hits:
        return None, "no_match"
    overlap = title_hits & core_hits
    if not overlap:
        return None, "no_match"
    if len(overlap) == 1:
        return next(iter(overlap)), "panel_core"
    pick = disambiguate_by_quality(title, overlap)
    if pick:
        return pick, "panel_core_quality"
    return None, "ambiguous_core"


def resolve_row(
    *,
    title: str,
    panel_epg_id: str | None,
    stream_id: str,
    channel_ids: set[str],
    stem_index: dict[str, set[str]],
    name_index: dict[str, set[str]],
    panel_core_index: dict[str, set[str]] | None = None,
    allow_stream_clone: bool,
) -> tuple[str | None, str | None, str]:
    """Return (guide_channel_id, clone_alias_id, match_kind)."""
    if panel_core_index is None:
        panel_core_index = {}

    if SECTION_HEADER.match((title or "").strip()):
        return None, None, "section_header"

    if panel_epg_id and valid_panel_epg_id(panel_epg_id):
        pid = panel_epg_id.strip()
        if pid in channel_ids:
            return pid, None, "exact_id"
        if pid.casefold() in {c.casefold() for c in channel_ids}:
            exact = next(c for c in channel_ids if c.casefold() == pid.casefold())
            return exact, None, "exact_id_casefold"

        stem_hits = stem_index.get(channel_stem(pid), set())
        if len(stem_hits) == 1:
            return next(iter(stem_hits)), None, "exact_stem"
        if len(stem_hits) > 1:
            pick = disambiguate_by_quality(title, stem_hits)
            if pick:
                return pick, None, "stem_quality"
            guide_id, name_kind = lookup_by_name(title, name_index)
            if guide_id:
                clone_id = None
                if allow_stream_clone and not valid_panel_epg_id(panel_epg_id):
                    sid = str(stream_id).strip()
                    if sid and sid not in channel_ids and sid != guide_id:
                        clone_id = sid
                return guide_id, clone_id, name_kind
            return None, None, "ambiguous_stem"

        guide_id, core_kind = pick_panel_core(pid, title, panel_core_index, name_index)
        if guide_id:
            clone_id = None
            if pid != guide_id and pid not in channel_ids:
                clone_id = pid
            return guide_id, clone_id, core_kind
        if core_kind == "ambiguous_core":
            return None, None, "ambiguous_core"

    guide_id, name_kind = lookup_by_name(title, name_index)
    if guide_id:
        clone_id = None
        if allow_stream_clone and not valid_panel_epg_id(panel_epg_id):
            sid = str(stream_id).strip()
            if sid and sid not in channel_ids and sid != guide_id:
                clone_id = sid
        return guide_id, clone_id, name_kind

    return None, None, name_kind


def merge_display_names(existing: dict[str, list[str]], guide_id: str, title: str) -> None:
    title = (title or "").strip()
    if not title or SECTION_HEADER.match(title):
        return
    names = existing.setdefault(guide_id, [])
    if title not in names:
        names.append(title)


def merge_clone_map(clones: dict[str, str], clone_id: str, guide_id: str) -> bool:
    if clone_id == guide_id:
        return False
    if clone_id in clones and clones[clone_id] != guide_id:
        return False
    clones[clone_id] = guide_id
    return True


def build_region_mappings(
    rows: list[dict[str, Any]],
    channel_ids: set[str],
    display_names: dict[str, list[str]],
    *,
    allow_stream_clone: bool,
) -> tuple[dict[str, list[str]], dict[str, str], dict[str, int]]:
    stem_index, name_index, panel_core_index = build_guide_indexes(channel_ids, display_names)
    aliases: dict[str, list[str]] = {}
    clones: dict[str, str] = {}
    stats: dict[str, int] = defaultdict(int)

    for row in rows:
        title = str(row.get("name") or "")
        panel_epg_id = row.get("epg_id")
        if panel_epg_id is not None and not isinstance(panel_epg_id, str):
            panel_epg_id = str(panel_epg_id)
        stream_id = str(row.get("xtream_id") or "").strip()
        guide_id, stream_clone, kind = resolve_row(
            title=title,
            panel_epg_id=panel_epg_id,
            stream_id=stream_id,
            channel_ids=channel_ids,
            stem_index=stem_index,
            name_index=name_index,
            panel_core_index=panel_core_index,
            allow_stream_clone=allow_stream_clone,
        )
        stats[kind] += 1
        if not guide_id:
            continue

        merge_display_names(aliases, guide_id, title)

        clone_key = None
        if valid_panel_epg_id(panel_epg_id):
            pid = panel_epg_id.strip()
            if pid != guide_id and pid not in channel_ids:
                clone_key = pid
        elif stream_clone:
            clone_key = stream_clone

        if clone_key and merge_clone_map(clones, clone_key, guide_id):
            stats["clone_added"] += 1
        elif clone_key and clone_key in clones:
            stats["clone_conflict"] += 1

    return aliases, clones, dict(stats)