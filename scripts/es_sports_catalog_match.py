#!/usr/bin/env python3
"""Spanish sports Xtream coverage: IPTVnator vs AquaPlay (not interchangeable)."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from xmltv_gzip import is_global_guide, parse_xmltv, published_global_guide  # noqa: E402
from xtream_matching import (  # noqa: E402
    build_guide_indexes,
    classify_playlist_region,
    normalize_channel_name,
    resolve_row,
    valid_panel_epg_id,
)

FOREIGN_GUIDE_ID = re.compile(r"\.(de|fr|gb|pt|nl|it|lu|ar)@", re.IGNORECASE)

DB = Path.home() / ".iptvnator" / "databases" / "iptvnator.db"
SPORT_MARKERS = (
    "laliga",
    "dazn",
    "deporte",
    "vamos",
    "campeon",
    "champion",
    "eurosport",
    "gol",
    "hypermotion",
    "f1",
    "moto",
    "sport",
    "liga tv",
    "federacion",
    "uefa",
)


def is_sport_stream(name: str, category: str) -> bool:
    cat = (category or "").upper()
    text = f"{name} {category}".casefold()
    if cat.startswith("[ES]") and "SPORT" in cat:
        return True
    return any(m in text for m in SPORT_MARKERS)


def load_sports_rows() -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        """
        SELECT CAST(c.xtream_id AS TEXT), c.title, COALESCE(c.epg_channel_id,''), cat.name
        FROM content c JOIN categories cat ON cat.id = c.category_id
        WHERE c.type = 'live'
        """
    )
    rows = []
    for xid, title, epg, cat in cur.fetchall():
        if classify_playlist_region(cat) != "ES":
            continue
        if not is_sport_stream(title, cat):
            continue
        rows.append(
            {
                "xtream_id": str(xid),
                "name": str(title),
                "epg_id": epg.strip() or None,
                "category": str(cat),
            }
        )
    con.close()
    return rows


def match_key_ap(value: str) -> str:
    t = str(value or "").lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\[.*?\]", " ", t)
    t = re.sub(r"\b(hd|fhd|uhd|4k|sd|hevc|h265|raw|backup|vip)\b", " ", t)
    t = re.sub(r"[\s\-_.,:;/\\()[\]{}'\"!?&+*#@|~`^%$]+", "", t)
    return "" if len(t) < 3 else t


def load_guide_context(path: Path) -> tuple[set[str], dict[str, list[str]], set[str]]:
    root = parse_xmltv(path)
    ids: set[str] = set()
    names: dict[str, list[str]] = {}
    programmed: set[str] = set()
    for ch in root.findall("channel"):
        cid = ch.get("id") or ""
        if cid:
            ids.add(cid)
            names[cid] = [n.text or "" for n in ch.findall("display-name") if (n.text or "").strip()]
    for p in root.findall("programme"):
        if (p.findtext("title") or "").strip():
            cid = p.get("channel") or ""
            if cid:
                programmed.add(cid)
    return ids, names, programmed


def aquaplay_index(
    root: ET.Element, programmed: set[str]
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """First channel wins per key (AquaPlay-style); reverse map for collision audit."""
    index: dict[str, str] = {}
    collisions: dict[str, set[str]] = defaultdict(set)
    for ch in root.findall("channel"):
        cid = ch.get("id") or ""
        if not cid or cid not in programmed:
            continue
        keys = {match_key_ap(n.text or "") for n in ch.findall("display-name")}
        keys.add(match_key_ap(cid))
        keys = {k for k in keys if k}
        for key in keys:
            collisions[key].add(cid)
            index.setdefault(key, cid)
    return index, dict(collisions)


def programmed_channel_ids(ids: set[str], programmed: set[str]) -> set[str]:
    return {cid for cid in ids if cid in programmed}


def is_foreign_guide_channel(channel_id: str) -> bool:
    return bool(FOREIGN_GUIDE_ID.search(channel_id or ""))


def iptvnator_resolve(
    stream_name: str,
    epg_id: str | None,
    ids: set[str],
    display_names: dict[str, list[str]],
    programmed: set[str],
    *,
    stream_id: str = "",
) -> tuple[str | None, str]:
    """IPTVnator only sees published XMLTV (resolve_row on guide indexes)."""
    if epg_id and valid_panel_epg_id(epg_id) and epg_id in ids:
        return epg_id, "iptv_id"
    active = programmed_channel_ids(ids, programmed)
    names = {cid: display_names.get(cid, []) for cid in active}
    stem, name_index, panel_core = build_guide_indexes(active, names)
    panel = epg_id if valid_panel_epg_id(epg_id) else None
    exact_hits = [cid for cid in active if stream_name in display_names.get(cid, [])]
    if len(exact_hits) == 1:
        return exact_hits[0], "iptv_display_exact"
    if len(exact_hits) > 1:
        clones = clone_roots(ROOT / "epg/xtream-aliases.json")
        canonical = {clones.get(h, h) for h in exact_hits}
        if len(canonical) == 1:
            return exact_hits[0], "iptv_display_exact"

    guide_id, _clone, kind = resolve_row(
        title=stream_name,
        panel_epg_id=panel,
        stream_id=stream_id or "",
        channel_ids=active,
        stem_index=stem,
        name_index=name_index,
        panel_core_index=panel_core,
        allow_stream_clone=False,
    )
    if not guide_id:
        return None, kind or "iptv_miss"
    if kind in {"exact_id", "exact_id_casefold", "exact_stem", "stem_quality"}:
        return guide_id, "iptv_id"
    if kind in {"display_name", "display_name_quality"}:
        return guide_id, "iptv_display_name"
    return guide_id, f"iptv_{kind}"


def aquaplay_resolve(
    stream_name: str,
    epg_id: str | None,
    ids: set[str],
    ap_index: dict[str, str],
    *,
    global_guide: bool,
) -> tuple[str | None, str]:
    if epg_id and valid_panel_epg_id(epg_id) and epg_id in ids:
        return epg_id, "aqua_id"
    key = match_key_ap(stream_name)
    if key and key in ap_index:
        hit = ap_index[key]
        if global_guide and is_foreign_guide_channel(hit):
            return None, "aqua_false_foreign"
        return hit, "aqua_name"
    return None, "aqua_miss"


CHAMP_PANEL = re.compile(r"^M\+LCAMPEON(\d+)$", re.IGNORECASE)
CHAMP_PANEL2 = re.compile(r"^M\+ LCAMPEONES (\d+)", re.IGNORECASE)
HYPER = re.compile(r"HYPERMOTION\s*(\d+)?", re.IGNORECASE)


def infer_target(name: str, programmed: set[str]) -> str | None:
    """Curated fallback when clients miss (exact stream titles from panel)."""
    raw = (name or "").strip()
    if not raw:
        return None
    up = raw.upper()

    m = CHAMP_PANEL.match(raw.strip())
    if m:
        n = int(m.group(1))
        if n >= 6:
            cid = f"MovistarPlus.chap{n - 1}"
            return cid if cid in programmed else None

    m2 = CHAMP_PANEL2.match(raw)
    if m2:
        n = int(m2.group(1))
        if n == 2:
            return "chap1" if "chap1" in programmed else None
        if n == 3:
            return "chap2" if "chap2" in programmed else None
        if n == 4:
            return "chap3" if "chap3" in programmed else None
        if n == 5:
            return "chap4" if "chap4" in programmed else None

    if "LCAMPEONES" in up or "LCAMPEON" in up:
        if any(x in up for x in (" 2 ", "2 HD", "2 FULL")):
            return "chap1"
        if any(x in up for x in (" 3 ", "3 HD", "3 FULL")):
            return "chap2"
        if " 4" in up and "LCAMPEONES 4" in up:
            return "chap3"
        if " 5" in up:
            return "chap4"
        if "LCAMPEONES" in up and "2" not in up and "3" not in up:
            return "chapio"

    if "DAZN LALIGA 2" in up or "DAZN LALIGA2" in up:
        return "daznl2"
    if "DAZN LALIGA" in up and "2" not in up.replace("LALIGA 2", ""):
        return "daznli"
    if re.match(r"^DAZN\s+[1-4]", up):
        n = re.search(r"DAZN\s+(\d)", up)
        if n:
            site = {"1": "m1sd", "2": "m2sd", "3": "dazn3", "4": "dazn4"}.get(n.group(1))
            if site and site in programmed:
                return site
    if "DAZN F1" in up or "DAZN MOTO" in up:
        return "mvf1" if "mvf1" in programmed else None
    if "HYPERMOTION" in up:
        h = HYPER.search(raw)
        num = h.group(1) if h and h.group(1) else "1"
        cid = {"1": "mligs", "2": "mligs2", "3": "mligs3"}.get(num, "mligs")
        return cid if cid in programmed else None
    if "LALIGA TV 4" in up or "LALIGA TV4" in up or "LALIGA 4" in up:
        return "mlig3" if "mlig3" in programmed else None
    if "LALIGA TV 3" in up or "LALIGA 3" in up:
        return "mlig2" if "mlig2" in programmed else None
    if "LALIGA TV 2" in up or "LALIGA 2" in up and "DAZN" not in up:
        return "mlig1" if "mlig1" in programmed else None
    if "LALIGATV" in up.replace(" ", "") or "LA LIGATV" in up:
        if "4K" in up or "UHD" in up:
            return "mliguh" if "mliguh" in programmed else "mliga"
        return "mliga"
    if "DEPORTES" in up:
        if "2" in up:
            return "arthur"
        if "3" in up:
            return "usop2"
        if "4" in up:
            return "usop3"
        if "5" in up:
            return "usop11"
        if "6" in up:
            return "multi8"
        if "7" in up:
            return "multi6"
        return "cpdep"
    if "VAMOS" in up:
        if "3" in up:
            return "mellav" if "mellav" in programmed else "vamosd"
        return "vamosd"
    if "EUROSPORT" in up:
        return "esp2" if " 2" in up or "2 " in up else "esp"
    if "GOL PLAY" in up or up.startswith("GOL "):
        return "gol"
    if "TELEDEPORTE" in up:
        return "tdep"
    if "GOLF" in up:
        return "golf2" if " 2" in up else "golf+"
    return None


def clone_roots(path: Path) -> dict[str, str]:
    xt = json.loads((ROOT / "epg" / "xtream-aliases.json").read_text(encoding="utf-8"))
    return dict(xt)


def same_station(a: str, b: str, clones: dict[str, str]) -> bool:
    if a == b:
        return True
    ra = clones.get(a, a)
    rb = clones.get(b, b)
    return ra == rb or ra == b or rb == a


def safe_to_add_name(
    stream_name: str,
    target: str,
    *,
    aliases: dict[str, list[str]],
    clones: dict[str, str],
    programmed: set[str],
    ap_index: dict[str, str],
    ap_collisions: dict[str, set[str]],
) -> tuple[bool, str]:
    if stream_name in aliases.get(target, []):
        return False, "already_present"
    if target not in programmed:
        return False, "target_no_programming"
    key = match_key_ap(stream_name)
    if not key:
        return False, "empty_ap_key"
    existing = ap_index.get(key)
    if existing and existing != target and not same_station(existing, target, clones):
        owners = ap_collisions.get(key, {existing})
        return False, f"aquaplay_collision:{sorted(owners)}"
    for gid, names in aliases.items():
        if gid == target:
            continue
        if stream_name in names:
            return False, f"iptv_alias_on_other:{gid}"
    nk = normalize_channel_name(stream_name)
    if nk:
        for gid, names in aliases.items():
            for other in names:
                if normalize_channel_name(other) == nk and gid != target:
                    if not same_station(gid, target, clones):
                        return False, f"normalized_collision:{gid}"
    return True, "ok"


def coverage_report(guide_path: Path, aliases: dict[str, list[str]] | None = None) -> dict:
    del aliases  # display aliases are materialised in the XMLTV guide
    rows = load_sports_rows()
    ids, display, programmed = load_guide_context(guide_path)
    root = parse_xmltv(guide_path)
    ap_index, ap_collisions = aquaplay_index(root, programmed)
    clones = clone_roots(guide_path) if guide_path.name.startswith("guide-es") else clone_roots(ROOT / "guides" / "guide-es.xml")
    global_guide = is_global_guide(guide_path)

    stats = defaultdict(int)
    details: list[dict] = []

    for row in rows:
        name = row["name"]
        epg = row["epg_id"]
        xtream_id = str(row.get("xtream_id") or "")
        iptv_id, iptv_how = iptvnator_resolve(
            name, epg, ids, display, programmed, stream_id=xtream_id
        )
        ap_id, ap_how = aquaplay_resolve(
            name, epg, ids, ap_index, global_guide=global_guide
        )
        target = iptv_id or ap_id
        inferred = None
        if not target:
            inferred = infer_target(name, programmed)
        has_prog = target in programmed if target else (inferred in programmed if inferred else False)

        def bucket(iptv: str | None, ap: str | None, how_i: str, how_a: str) -> str:
            if global_guide and (
                how_a == "aqua_false_foreign"
                or (iptv is not None and is_foreign_guide_channel(iptv))
            ):
                return "false_match_foreign"
            if iptv and how_i == "iptv_id":
                return "match_id"
            if ap and how_a == "aqua_id":
                return "match_id"
            if iptv and (
                how_i.startswith("iptv_") or how_i == "iptv_display_exact"
            ):
                return "match_name_iptv"
            if ap and how_a == "aqua_name":
                return "match_name_aqua"
            if iptv:
                return "match_other"
            return "uncovered"

        b = bucket(iptv_id, ap_id, iptv_how, ap_how)
        if b == "uncovered" and inferred:
            b = "inferable"
        if iptv_id and ap_id and iptv_id != ap_id and not same_station(iptv_id, ap_id, clones):
            b = "wrong_split_clients"
            stats["wrong_split_clients"] += 1
        elif ap_id and ap_how == "aqua_name":
            key = match_key_ap(name)
            owners = ap_collisions.get(key, {ap_id})
            if len(owners) > 1 and not all(
                same_station(a, ap_id, clones) for a in owners
            ):
                b = "ambiguous_aqua"
        if not has_prog and target:
            b = "matched_no_programming"
        stats[b] += 1
        details.append(
            {
                "name": name,
                "epg_id": epg,
                "bucket": b,
                "iptv": iptv_id,
                "iptv_how": iptv_how,
                "aqua": ap_id,
                "aqua_how": ap_how,
                "inferred": inferred,
                "programmed": has_prog,
            }
        )

    return {"stats": dict(stats), "rows": details, "total": len(rows)}


def propose_aliases(
    guide_path: Path,
    aliases: dict[str, list[str]],
    *,
    ids: set[str],
    programmed: set[str],
    ap_index: dict[str, str],
    ap_collisions: dict[str, set[str]],
) -> dict[str, list[str]]:
    rows = load_sports_rows()
    clones = clone_roots(ROOT / "epg/xtream-aliases.json")
    proposals: dict[str, list[str]] = defaultdict(list)

    global_guide = is_global_guide(guide_path)
    _, display, programmed_ctx = load_guide_context(guide_path)
    for row in rows:
        name = row["name"]
        epg = row["epg_id"]
        xtream_id = str(row.get("xtream_id") or "")
        iptv_id, _ = iptvnator_resolve(
            name, epg, ids, display, programmed_ctx, stream_id=xtream_id
        )
        ap_id, _ = aquaplay_resolve(name, epg, ids, ap_index, global_guide=global_guide)
        if iptv_id and ap_id and (iptv_id == ap_id or same_station(iptv_id, ap_id, clones)):
            continue
        target = iptv_id or ap_id or infer_target(name, programmed)
        if not target or target not in programmed:
            continue
        ok, _reason = safe_to_add_name(
            name,
            target,
            aliases=aliases,
            clones=clones,
            programmed=programmed,
            ap_index=ap_index,
            ap_collisions=ap_collisions,
        )
        if ok:
            proposals[target].append(name)
    return dict(proposals)


def apply_proposals(aliases_path: Path, proposals: dict[str, list[str]]) -> int:
    data = json.loads(aliases_path.read_text(encoding="utf-8"))
    added = 0
    for gid, names in proposals.items():
        bucket = data.setdefault(gid, [])
        for name in names:
            if name not in bucket:
                bucket.append(name)
                added += 1
    aliases_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guide", type=Path, default=None)
    parser.add_argument("--aliases", type=Path, default=ROOT / "epg/aliases.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", type=Path, help="Write detailed report JSON")
    args = parser.parse_args()

    guide = args.guide or published_global_guide(ROOT)
    aliases = json.loads(args.aliases.read_text(encoding="utf-8"))
    before = coverage_report(guide, aliases)
    ids, _, programmed = load_guide_context(guide)
    root = parse_xmltv(guide)
    ap_index, ap_collisions = aquaplay_index(root, programmed)
    proposals = propose_aliases(
        guide,
        aliases,
        ids=ids,
        programmed=programmed,
        ap_index=ap_index,
        ap_collisions=ap_collisions,
    )
    added = 0
    if args.apply and proposals:
        added = apply_proposals(args.aliases, proposals)
        aliases = json.loads(args.aliases.read_text(encoding="utf-8"))

    after = coverage_report(guide, aliases)
    print(json.dumps({"before": before["stats"], "after": after["stats"], "proposals": proposals, "added": added}, indent=2))
    if args.json:
        args.json.write_text(
            json.dumps({"before": before, "after": after, "proposals": proposals}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())