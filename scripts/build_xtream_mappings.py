#!/usr/bin/env python3
"""Build regional Xtream alias JSON from a local IPTVnator DB (read-only)."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from xtream_matching import (  # noqa: E402
    build_guide_indexes,
    build_region_mappings,
    classify_playlist_region,
    valid_panel_epg_id,
)
from es_xtream_policy import denied_xtream_clone_ids, filter_denied_xtream_aliases  # noqa: E402
from xtream_pending import build_pending_report  # noqa: E402

DEFAULT_DB = Path.home() / ".iptvnator" / "databases" / "iptvnator.db"
GUIDES = {
    "ES": ROOT / "guide-es.xml",
    "FR": ROOT / "guide-fr.xml",
    "ARABIC": ROOT / "guide-arabic.xml",
    "GB": ROOT / "guide-gb.xml",
    "PT": ROOT / "guide-pt.xml",
}
ALIAS_OUT = {
    "ES": ROOT / "epg" / "aliases.json",
    "FR": ROOT / "epg" / "aliases-fr.json",
    "ARABIC": ROOT / "epg" / "aliases-arabic.json",
    "GB": ROOT / "epg" / "aliases-gb.json",
    "PT": ROOT / "epg" / "aliases-pt.json",
}
CLONE_OUT = {
    "ES": ROOT / "epg" / "xtream-aliases.json",
    "FR": ROOT / "epg" / "xtream-aliases-fr.json",
    "ARABIC": ROOT / "epg" / "xtream-aliases-arabic.json",
    "GB": ROOT / "epg" / "xtream-aliases-gb.json",
    "PT": ROOT / "epg" / "xtream-aliases-pt.json",
}
PENDING_OUT = {
    "ES": ROOT / "epg" / "xtream-pending-es.json",
    "FR": ROOT / "epg" / "xtream-pending-fr.json",
    "ARABIC": ROOT / "epg" / "xtream-pending-arabic.json",
    "GB": ROOT / "epg" / "xtream-pending-gb.json",
    "PT": ROOT / "epg" / "xtream-pending-pt.json",
}


def load_guide_channels(path: Path) -> tuple[set[str], dict[str, list[str]], set[str]]:
    root = ET.parse(path).getroot()
    ids: set[str] = set()
    names: dict[str, list[str]] = {}
    programmed: set[str] = set()
    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if not channel_id:
            continue
        ids.add(channel_id)
        names[channel_id] = [n.text or "" for n in channel.findall("display-name") if (n.text or "").strip()]
    for programme in root.findall("programme"):
        if not (programme.findtext("title") or "").strip():
            continue
        channel_id = programme.get("channel") or ""
        if channel_id:
            programmed.add(channel_id)
    return ids, names, programmed


def read_catalog_rows(db_path: Path) -> list[dict]:
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
    rows = [
        {
            "xtream_id": row["xtream_id"],
            "name": row["name"],
            "epg_id": row["epg_id"] or None,
            "category": row["category"],
        }
        for row in cur.fetchall()
    ]
    con.close()
    return rows


def merge_aliases(
    existing: dict[str, list[str]],
    discovered: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged = {key: list(names) for key, names in existing.items()}
    for guide_id, names in discovered.items():
        bucket = merged.setdefault(guide_id, [])
        for name in names:
            if name not in bucket:
                bucket.append(name)
    return merged


def resolve_clone_root(clone_map: dict[str, str], channel_id: str) -> str:
    seen = {channel_id}
    while channel_id in clone_map:
        channel_id = clone_map[channel_id]
        if channel_id in seen:
            return channel_id
        seen.add(channel_id)
    return channel_id


def strip_spanish_skyshowtime_panel_clones(mapping: dict[str, str]) -> dict[str, str]:
    """Keep a single SkyShowtime panel clone; drop legacy fox.es.* panels (see commit 95eea31b)."""
    allowed = {"fox.es.skyshowtime1"}
    cleaned = dict(mapping)
    for clone_id in list(cleaned):
        if clone_id.startswith("fox.es.") and clone_id not in allowed:
            del cleaned[clone_id]
    return cleaned


def merge_clones(
    existing: dict[str, str],
    discovered: dict[str, str],
) -> dict[str, str]:
    discovered = strip_spanish_skyshowtime_panel_clones(discovered)
    existing = strip_spanish_skyshowtime_panel_clones(existing)
    merged = dict(existing)
    for clone_id, guide_id in discovered.items():
        target = resolve_clone_root({**merged, **discovered}, guide_id)
        if clone_id in merged and merged[clone_id] != target:
            continue
        if clone_id == target:
            continue
        merged[clone_id] = target
    for clone_id, guide_id in list(merged.items()):
        root = resolve_clone_root(merged, guide_id)
        if root == clone_id:
            del merged[clone_id]
        else:
            merged[clone_id] = root
    return merged


def legacy_es_status(row: dict[str, object]) -> dict[str, object]:
    status = row.get("status")
    return {
        **row,
        "status": status,
        "reason": row.get("detail") or status,
    }


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("XTREAM_DB", DEFAULT_DB)),
        help="IPTVnator SQLite database (read-only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1

    rows = read_catalog_rows(args.db)
    by_region: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        region = classify_playlist_region(str(row["category"]))
        if region:
            by_region[region].append(row)

    summary: dict[str, object] = {"regions": {}}

    for region, guide_path in GUIDES.items():
        if not guide_path.is_file():
            if region == "PT":
                print(f"Skipping PT: missing guide {guide_path}", file=sys.stderr)
                continue
            print(f"Missing guide: {guide_path}", file=sys.stderr)
            return 1
        guide_ids, guide_names, programmed = load_guide_channels(guide_path)
        stem_index, name_index, panel_core_index = build_guide_indexes(guide_ids, guide_names)
        alias_path = ALIAS_OUT[region]
        clone_path = CLONE_OUT[region]
        existing_aliases = json.loads(alias_path.read_text(encoding="utf-8")) if alias_path.is_file() else {}
        existing_clones = json.loads(clone_path.read_text(encoding="utf-8")) if clone_path.is_file() else {}
        catalog = by_region.get(region, [])
        allow_stream = region == "ARABIC"
        discovered_aliases, discovered_clones, stats = build_region_mappings(
            catalog,
            guide_ids,
            guide_names,
            allow_stream_clone=allow_stream,
        )
        canonical_aliases: dict[str, list[str]] = {}
        clone_map = {**existing_clones, **discovered_clones}
        for guide_id, names in discovered_aliases.items():
            target = clone_map.get(guide_id, guide_id)
            if target not in guide_ids or target in clone_map:
                continue
            bucket = canonical_aliases.setdefault(target, [])
            for name in names:
                if name not in bucket:
                    bucket.append(name)
        discovered_aliases = canonical_aliases
        aliases = merge_aliases(existing_aliases, discovered_aliases)
        clones = merge_clones(existing_clones, discovered_clones)
        clones = strip_spanish_skyshowtime_panel_clones(clones)
        clones = filter_denied_xtream_aliases(clones, denied_xtream_clone_ids())

        for clone_id, original_id in list(clones.items()):
            if original_id not in guide_ids:
                del clones[clone_id]
        aliases = {cid: names for cid, names in aliases.items() if cid in guide_ids}

        summary["regions"][region] = {
            "catalog_rows": len(catalog),
            "display_alias_channels": len(aliases),
            "display_names_total": sum(len(v) for v in aliases.values()),
            "clone_mappings": len(clones),
            "stats": stats,
        }

        pending = build_pending_report(
            catalog,
            channel_ids=guide_ids | set(clones),
            programmed=programmed,
            stem_index=stem_index,
            name_index=name_index,
            panel_core_index=panel_core_index,
            allow_stream_clone=allow_stream,
            clones=clones,
        )
        summary["regions"][region]["pending"] = len(pending)
        pending_counts: dict[str, int] = defaultdict(int)
        for entry in pending:
            pending_counts[str(entry["status"])] += 1
        summary["regions"][region]["pending_by_status"] = dict(pending_counts)

        if args.dry_run:
            continue
        write_json(alias_path, aliases)
        write_json(clone_path, clones)
        pending_path = PENDING_OUT[region]
        if region == "ES":
            write_json(pending_path, [legacy_es_status(entry) for entry in pending])
        else:
            write_json(pending_path, pending)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())