#!/usr/bin/env python3
"""Dutch IPTVnator catalog matching and AquaPlay/IPTVnator client simulation."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from xtream_matching import (
    SECTION_HEADER,
    build_guide_indexes,
    normalize_channel_name,
    resolve_row,
    valid_panel_epg_id,
)

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

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


def _nl_epg():
    spec = importlib.util.spec_from_file_location("nl_epg", _SCRIPT_DIR / "nl-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_catalog_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected JSON array")
    return data


def clean_catalog_rows(rows: list[dict]) -> list[dict]:
    from es_xtream_policy import is_forbidden_alias_token

    out = []
    for row in rows:
        if row.get("category") != "[NL] HOLLANDS":
            continue
        name = row.get("name") or ""
        if SECTION_HEADER.match(name.strip()):
            continue
        if "✦" in name or name.strip().startswith("●"):
            continue
        epg = row.get("epg_id")
        if is_forbidden_alias_token(epg):
            epg = None
        out.append({"xtream_id": row.get("xtream_id"), "name": name, "epg_id": epg})
    return out


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


def resolve_catalog_row(
    row: dict,
    channel_ids: set[str],
    display_names: dict[str, list[str]],
    programmed: set[str],
    *,
    aliases: dict[str, list[str]] | None = None,
) -> tuple[str | None, str]:
    nl = _nl_epg()
    stem, name_index, core = build_guide_indexes(channel_ids, display_names)
    is_nh = bool(nl.NH_RE.search(row["name"])) or normalize_channel_name(row["name"]) in {
        "nhnieuws",
        "nh",
    }
    panel_id = None if is_nh else row.get("epg_id")
    for title in nl.extra_titles(row["name"]):
        guide_id, _clone, kind = resolve_row(
            title=title,
            panel_epg_id=panel_id,
            stream_id=row.get("xtream_id"),
            channel_ids=channel_ids,
            stem_index=stem,
            name_index=name_index,
            panel_core_index=core,
            allow_stream_clone=False,
        )
        if guide_id and kind in SAFE_KINDS and guide_id in programmed:
            return guide_id, kind
    if aliases:
        for guide_id, names in aliases.items():
            if guide_id not in programmed:
                continue
            if row["name"] in names:
                return guide_id, "display_alias"
    return None, "no_match"


def match_key(value: str) -> str:
    t = str(value or "").lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\[.*?\]", " ", t)
    t = re.sub(r"\b(hd|fhd|uhd|4k|sd|hevc|h265|raw|backup|vip)\b", " ", t)
    t = re.sub(r"[\s\-_.,:;/\\()[\]{}'\"!?&+*#@|~`^%$]+", "", t)
    return "" if len(t) < 3 else t


def aquaplay_index(root: ET.Element) -> tuple[dict[str, list[str]], dict[str, str]]:
    programmed = {
        p.get("channel") or ""
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip()
    }
    by_channel: dict[str, list[str]] = {}
    name_index: dict[str, str] = {}
    for channel in root.findall("channel"):
        cid = channel.get("id") or ""
        if not cid or cid not in programmed:
            continue
        names = [n.text.strip() for n in channel.findall("display-name") if (n.text or "").strip()]
        by_channel[cid] = names
        keys: list[str] = []
        for name in names:
            key = match_key(name)
            if key and key not in keys:
                keys.append(key)
        id_key = match_key(cid)
        for key in keys + ([id_key] if id_key else []):
            name_index.setdefault(key, cid)
    return by_channel, name_index


def aquaplay_resolve(
    panel_epg_id: str | None,
    stream_name: str,
    by_channel: dict[str, list[str]],
    name_index: dict[str, str],
) -> str | None:
    if panel_epg_id and panel_epg_id in by_channel:
        return panel_epg_id
    nl = _nl_epg()
    for title in nl.extra_titles(stream_name):
        key = match_key(title)
        if key and key in name_index:
            return name_index[key]
    key = match_key(panel_epg_id or "")
    if key and key in name_index:
        return name_index[key]
    return None


SHARED_PANEL_IDS = frozenset(
    {
        "nponieuws.nl",
        "discoverychannel.nl",
        "nickelodeon.nl",
        "rtl7.nl",
        "rtvutrecht.nl",
        "ziggosportdocu.nl",
    }
)


def build_mappings_from_guide(
    catalog_rows: list[dict],
    guide_path: Path,
    *,
    aliases: dict[str, list[str]] | None = None,
) -> tuple[dict[str, list[str]], dict[str, str], set[int]]:
    nl = _nl_epg()
    channel_ids, names, programmed = load_guide_match_context(guide_path)
    aliases_out: dict[str, list[str]] = {}
    covered: set[int] = set()
    for index, row in enumerate(catalog_rows):
        guide_id, _kind = resolve_catalog_row(row, channel_ids, names, programmed, aliases=aliases)
        if not guide_id or guide_id not in channel_ids or "@" not in guide_id:
            continue
        covered.add(index)
        bucket = aliases_out.setdefault(guide_id, [])
        if row["name"] not in bucket:
            bucket.append(row["name"])
        if bool(nl.NH_RE.search(row["name"])):
            continue
        epg = row.get("epg_id")
        if not epg or not valid_panel_epg_id(epg):
            continue
        if epg.strip().split("@", 1)[0].casefold() in SHARED_PANEL_IDS:
            continue
    return aliases_out, {}, covered


def real_client_coverage(
    guide_path: Path,
    catalog_path: Path,
    *,
    aliases: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    root = ET.parse(guide_path).getroot()
    rows = clean_catalog_rows(load_catalog_json(catalog_path))
    by_ch, name_index = aquaplay_index(root)
    channel_ids, display_names, programmed = load_guide_match_context(guide_path)
    aqua_hits = 0
    iptv_hits = 0
    missing = []
    kinds: dict[str, int] = {}
    nh_rows = []
    for row in rows:
        aqua = aquaplay_resolve(row.get("epg_id"), row["name"], by_ch, name_index)
        iptv, kind = resolve_catalog_row(row, channel_ids, display_names, programmed, aliases=aliases)
        kinds[kind] = kinds.get(kind, 0) + 1
        if aqua:
            aqua_hits += 1
        if iptv:
            iptv_hits += 1
        nl = _nl_epg()
        if nl.NH_RE.search(row["name"]):
            nh_rows.append(
                {
                    "name": row["name"],
                    "panel_epg_id": row.get("epg_id"),
                    "aquaplay": aqua,
                    "iptvnator": iptv,
                    "ok": bool(iptv) and "nponieuws" not in (iptv or "").casefold(),
                }
            )
        if not iptv:
            missing.append({"name": row["name"], "epg_id": row.get("epg_id"), "kind": kind})
    total = len(rows)
    return {
        "catalog_real_streams": total,
        "aquaplay_hits": aqua_hits,
        "aquaplay_pct": round(100 * aqua_hits / total, 1) if total else 0.0,
        "iptvnator_hits": iptv_hits,
        "iptvnator_pct": round(100 * iptv_hits / total, 1) if total else 0.0,
        "iptvnator_kinds": kinds,
        "missing": missing,
        "nh_nieuws": nh_rows,
    }