#!/usr/bin/env python3
"""Compare Xtream catalog linkage before/after alias + clone enrichment."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from xtream_matching import (  # noqa: E402
    build_guide_indexes,
    classify_playlist_region,
    resolve_row,
    valid_panel_epg_id,
)

PROFILES = {
    "es": ("guide-es.xml", "epg/aliases.json", "epg/xtream-aliases.json", "ES"),
    "fr": ("guide-fr.xml", "epg/aliases-fr.json", "epg/xtream-aliases-fr.json", "FR"),
    "arabic": (
        "guide-arabic.xml",
        "epg/aliases-arabic.json",
        "epg/xtream-aliases-arabic.json",
        "ARABIC",
    ),
    "gb": ("guide-gb.xml", "epg/aliases-gb.json", "epg/xtream-aliases-gb.json", "GB"),
    "pt": ("guide-pt.xml", "epg/aliases-pt.json", "epg/xtream-aliases-pt.json", "PT"),
}


def read_catalog(db_path: Path, region_filter: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            CAST(c.xtream_id AS TEXT) AS xtream_id,
            c.title AS name,
            COALESCE(c.epg_channel_id, '') AS epg_id,
            cat.name AS category
        FROM content c
        JOIN categories cat ON cat.id = c.category_id
        WHERE c.type = 'live'
        """
    )
    rows = []
    for row in cur.fetchall():
        region = classify_playlist_region(row["category"])
        if region != region_filter:
            continue
        rows.append(
            {
                "xtream_id": row["xtream_id"],
                "name": row["name"],
                "epg_id": row["epg_id"] or None,
                "category": row["category"],
            }
        )
    con.close()
    return rows


def load_guide(path: Path) -> tuple[set[str], dict[str, list[str]], set[str], set[str]]:
    root = ET.parse(path).getroot()
    ids: set[str] = set()
    names: dict[str, list[str]] = {}
    clone_ids: set[str] = set()
    programmed: set[str] = set()
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if channel_id:
            ids.add(channel_id)
            names[channel_id] = [
                n.text or "" for n in channel.findall("display-name") if (n.text or "").strip()
            ]
    for programme in root.findall("programme"):
        title = (programme.findtext("title") or "").strip()
        channel_id = programme.get("channel") or ""
        if title and channel_id:
            programmed.add(channel_id)
    return ids, names, programmed, clone_ids


def merge_aliases_into_names(
    channel_ids: set[str],
    display_names: dict[str, list[str]],
    aliases: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged = {cid: list(display_names.get(cid, [])) for cid in channel_ids}
    for channel_id, extra in aliases.items():
        if channel_id not in merged:
            continue
        for name in extra:
            if name not in merged[channel_id]:
                merged[channel_id].append(name)
    return merged


def catalog_link_stats(
    rows: list[dict],
    *,
    channel_ids: set[str],
    display_names: dict[str, list[str]],
    clones: dict[str, str],
    programmed: set[str],
    allow_stream_clone: bool,
) -> dict[str, object]:
    stem_index, name_index, panel_core_index = build_guide_indexes(
        channel_ids | set(clones), display_names
    )
    match_kind: Counter = Counter()
    linkage: Counter = Counter()
    matched = 0
    matched_programmed = 0

    for row in rows:
        title = str(row["name"])
        panel_epg = row.get("epg_id")
        if panel_epg and valid_panel_epg_id(str(panel_epg)) and str(panel_epg).strip() in clones:
            root = clones[str(panel_epg).strip()]
            if root in programmed:
                matched += 1
                match_kind["clone_map"] += 1
                matched_programmed += 1
                linkage["id_exact"] += 1
                continue
        guide_id, _, kind = resolve_row(
            title=title,
            panel_epg_id=panel_epg,
            stream_id=str(row["xtream_id"]),
            channel_ids=channel_ids | set(clones),
            stem_index=stem_index,
            name_index=name_index,
            panel_core_index=panel_core_index,
            allow_stream_clone=allow_stream_clone,
        )
        if not guide_id:
            title_cf = title.strip()
            title_plain = title_cf.replace("UK ", "", 1).strip()
            for channel_id, labels in display_names.items():
                if channel_id not in programmed:
                    continue
                if title_cf in labels or title_plain in labels:
                    guide_id = channel_id
                    kind = "display_name_literal"
                    break
        if not guide_id:
            linkage["unmatched"] += 1
            continue
        matched += 1
        match_kind[kind] += 1
        has_prog = guide_id in programmed
        if has_prog:
            matched_programmed += 1

        if valid_panel_epg_id(panel_epg):
            pid = str(panel_epg).strip()
            if pid.casefold() == guide_id.casefold():
                linkage["id_exact"] += 1
            elif kind.startswith("panel_"):
                linkage["id_panel_core"] += 1
            else:
                linkage["display_name_with_panel_id"] += 1
        elif kind.startswith("display_name"):
            literal = title in display_names.get(guide_id, [])
            linkage["display_name_literal" if literal else "display_name_alias"] += 1
        else:
            linkage["other"] += 1

    stats = {
        "catalog_rows": len(rows),
        "matched_to_guide": matched,
        "matched_programmed_originals": matched_programmed,
        "match_kind": dict(match_kind),
        "linkage": dict(linkage),
        "clone_count": len(clones),
    }
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--db", type=Path, default=Path.home() / ".iptvnator" / "databases" / "iptvnator.db")
    parser.add_argument("--enriched", type=Path)
    args = parser.parse_args()

    guide_rel, alias_rel, clone_rel, region_key = PROFILES[args.profile]
    guide_path = ROOT / guide_rel
    if not guide_path.is_file():
        print(f"Missing guide: {guide_path}", file=sys.stderr)
        return 1
    if not args.db.is_file():
        print(f"Missing database: {args.db}", file=sys.stderr)
        return 1

    catalog = read_catalog(args.db, region_key if region_key != "ARABIC" else "ARABIC")
    allow_stream = args.profile == "arabic"
    channel_ids, base_names, programmed, _ = load_guide(guide_path)
    before = catalog_link_stats(
        catalog,
        channel_ids=channel_ids,
        display_names=base_names,
        clones={},
        programmed=programmed,
        allow_stream_clone=allow_stream,
    )

    aliases = json.loads((ROOT / alias_rel).read_text(encoding="utf-8"))
    clones = json.loads((ROOT / clone_rel).read_text(encoding="utf-8"))
    enriched_names = merge_aliases_into_names(channel_ids, base_names, aliases)

    if args.enriched:
        enriched_ids, enriched_names2, enriched_prog, _ = load_guide(args.enriched)
        after = catalog_link_stats(
            catalog,
            channel_ids=enriched_ids,
            display_names=enriched_names2,
            clones=clones,
            programmed=enriched_prog,
            allow_stream_clone=allow_stream,
        )
    else:
        after = catalog_link_stats(
            catalog,
            channel_ids=channel_ids,
            display_names=enriched_names,
            clones=clones,
            programmed=programmed,
            allow_stream_clone=allow_stream,
        )

    print(
        json.dumps(
            {
                "profile": args.profile,
                "before": before,
                "after": after,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())