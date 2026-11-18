#!/usr/bin/env python3
"""Italian Xtream catalog matching and AquaPlay / IPTVnator client simulation."""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xtream_matching import SECTION_HEADER, valid_panel_epg_id  # noqa: E402

REFERENCE_CURATED = 66
REFERENCE_USEFUL = 65
REFERENCE_STREAMS = 116
DEFAULT_REJECTED = _ROOT / "temp" / "it-trial" / "rejected-curated-aliases.json"
DEFAULT_CATALOG = _ROOT / "temp" / "it-trial" / "xtream-it-catalog.json"
DB = Path.home() / ".iptvnator" / "databases" / "iptvnator.db"

PLACEHOLDER_RES = [
    re.compile(r"nessun\s+evento\s+in\s+onda", re.I),
    re.compile(r"no\s+event\s+on\s+air", re.I),
    re.compile(r"^programmazione\s+non\s+disponibile", re.I),
]


def _it_epg():
    spec = importlib.util.spec_from_file_location("it_epg", _SCRIPT_DIR / "it-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_catalog_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "streams" in data:
        data = data["streams"]
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected JSON array")
    return data


def clean_catalog_rows(rows: list[dict]) -> list[dict]:
    from es_xtream_policy import is_forbidden_alias_token

    out = []
    for row in rows:
        cat = row.get("category") or ""
        if "[IT]" not in str(cat).upper():
            continue
        name = row.get("name") or ""
        if SECTION_HEADER.match(name.strip()):
            continue
        epg = row.get("epg_id")
        if is_forbidden_alias_token(epg):
            epg = None
        out.append({"xtream_id": row.get("xtream_id"), "name": name, "epg_id": epg})
    return out


def load_streams_db() -> list[dict]:
    if DB.is_file():
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(
            """
            SELECT CAST(c.xtream_id AS TEXT) AS xtream_id, c.title AS name,
                   COALESCE(c.epg_channel_id, '') AS epg_id, cat.name AS category
            FROM content c JOIN categories cat ON cat.id=c.category_id
            WHERE c.type='live' AND cat.name LIKE '[IT]%'
            ORDER BY c.title
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    if DEFAULT_CATALOG.is_file():
        return clean_catalog_rows(load_catalog_json(DEFAULT_CATALOG))
    raise FileNotFoundError("No Italian Xtream catalog (DB or temp/it-trial/xtream-it-catalog.json)")


def load_guide_match_context(guide_path: Path) -> tuple[set[str], dict[str, list[str]], set[str]]:
    root = ET.parse(guide_path).getroot()
    names: dict[str, list[str]] = {}
    channel_ids: set[str] = set()
    programmed: set[str] = set()
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


def match_key_ap(value: str) -> str:
    t = str(value or "").lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\[.*?\]", " ", t)
    t = re.sub(r"\b(hd|fhd|uhd|4k|sd|hevc|h265|raw|backup|vip)\b", " ", t)
    t = re.sub(r"[\s\-_.,:;/\\()[\]{}'\"!?&+*#@|~`^%$]+", "", t)
    return "" if len(t) < 3 else t


def aquaplay_index(root: ET.Element) -> dict[str, str]:
    programmed = {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip() and p.get("channel")
    }
    name_index: dict[str, str] = {}
    for ch in root.findall("channel"):
        cid = ch.get("id") or ""
        if not cid or cid not in programmed:
            continue
        for n in ch.findall("display-name"):
            key = match_key_ap(n.text or "")
            if key:
                name_index.setdefault(key, cid)
        key = match_key_ap(cid)
        if key:
            name_index.setdefault(key, cid)
    return name_index


def aquaplay_resolve(epg_id: str | None, stream_name: str, name_index: dict[str, str], *, ids: set[str]) -> str | None:
    if epg_id and valid_panel_epg_id(epg_id) and epg_id in ids:
        return epg_id
    key = match_key_ap(stream_name)
    if key in name_index:
        return name_index[key]
    return None


def iptvnator_auto(epg_id: str | None, ids: set[str]) -> str | None:
    if epg_id and valid_panel_epg_id(epg_id) and epg_id in ids:
        return epg_id
    return None


def iptvnator_with_aliases(
    stream_name: str,
    panel_epg_id: str | None,
    ids: set[str],
    aliases: dict[str, list[str]],
) -> str | None:
    auto = iptvnator_auto(panel_epg_id, ids)
    if auto:
        return auto
    for gid, extra in aliases.items():
        if gid not in ids:
            continue
        if stream_name in extra:
            return gid
    return None


def programme_quality(titles: list[str]) -> bool:
    if not titles:
        return False
    ph = sum(1 for t in titles if any(rx.search(t) for rx in PLACEHOLDER_RES))
    return len(titles) - ph > 0


def curated_reference_mappings(aliases: dict[str, list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for gid, names in aliases.items():
        for name in names:
            out[name] = gid
    return out


def load_rejected_streams(path: Path | None = None) -> set[str]:
    path = path or DEFAULT_REJECTED
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["stream"] for row in data if isinstance(row, dict) and row.get("stream")}


def client_coverage_report(
    guide_path: Path,
    *,
    aliases: dict[str, list[str]] | None = None,
    catalog_rows: list[dict] | None = None,
) -> dict[str, object]:
    aliases = aliases or {}
    rows = catalog_rows or load_streams_db()
    root = ET.parse(guide_path).getroot()
    ids, names, programmed = load_guide_match_context(guide_path)
    titles_by_ch: dict[str, list[str]] = {}
    for p in root.findall("programme"):
        cid = p.get("channel") or ""
        t = (p.findtext("title") or "").strip()
        if cid and t:
            titles_by_ch.setdefault(cid, []).append(t)
    ap_index = aquaplay_index(root)
    curated = curated_reference_mappings(aliases)

    aqua_auto = aqua_alias = 0
    iptv_auto = iptv_alias = 0
    curated_hits = useful_hits = 0
    per_stream: list[dict] = []

    for row in rows:
        name = row["name"]
        epg = row.get("epg_id") if valid_panel_epg_id(row.get("epg_id")) else None
        ap_a = aquaplay_resolve(epg, name, ap_index, ids=ids)
        it_a = iptvnator_auto(epg, ids)
        gid = curated.get(name)
        has_prog = gid in programmed if gid else False
        useful = has_prog and programme_quality(titles_by_ch.get(gid or "", []))
        ap_e = gid if gid in programmed else None
        it_m = iptvnator_with_aliases(name, epg, ids, aliases)

        if ap_a:
            aqua_auto += 1
        if ap_e:
            aqua_alias += 1
        if it_a:
            iptv_auto += 1
        if it_m:
            iptv_alias += 1
        if gid and has_prog:
            curated_hits += 1
            if useful:
                useful_hits += 1
        per_stream.append(
            {
                "stream": name,
                "aquaplay_auto": ap_a,
                "aquaplay_after_aliases": ap_e,
                "iptvnator_auto": it_a,
                "iptvnator_after_aliases": it_m,
                "curated_guide_id": gid,
                "useful_programming": useful,
            }
        )

    return {
        "catalog_streams": len(rows),
        "aquaplay_auto_hits": aqua_auto,
        "aquaplay_after_aliases": aqua_alias,
        "iptvnator_auto_hits": iptv_auto,
        "iptvnator_after_aliases": iptv_alias,
        "curated_mappings_verified": curated_hits,
        "curated_with_useful_programming": useful_hits,
        "per_stream": per_stream,
    }


def validate_rejected_not_in_aliases(aliases: dict[str, list[str]], rejected: set[str]) -> list[str]:
    violations = []
    for _gid, names in aliases.items():
        for name in names:
            if name in rejected:
                violations.append(name)
    return sorted(violations)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("guide", type=Path)
    parser.add_argument("--aliases", type=Path, default=_ROOT / "epg" / "aliases-it.json")
    args = parser.parse_args()
    aliases = json.loads(args.aliases.read_text(encoding="utf-8"))
    rejected = load_rejected_streams()
    violations = validate_rejected_not_in_aliases(aliases, rejected)
    if violations:
        raise SystemExit("Rejected streams present in aliases: " + ", ".join(violations))
    report = client_coverage_report(args.guide, aliases=aliases)
    print(json.dumps({k: v for k, v in report.items() if k != "per_stream"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())