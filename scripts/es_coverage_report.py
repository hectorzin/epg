#!/usr/bin/env python3
"""Compare Spanish EPG coverage: FAST providers, Xtream catalog, user-reported channels."""
from __future__ import annotations

import argparse
import importlib.util
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

USER_CHANNELS = [
    ("M+ Cinesur", "fox.es.cinesur"),
    ("M+ Cine", "movistarestrenos.es"),
    ("M+ Cine Selección", "movistarestrenos.es"),
    ("M+ Acción 2", "fox.es.accion2"),
    ("M+ Drama 2", "moviestardrama.es"),
    ("M+ Drama", None),
    ("M+ Drama 3", "moviestardrama.es"),
    ("Atrescine", "cima.es.a3cine"),
    ("Atrescine 2", "cima.es.a3cine"),
    ("M+ Terror", "cima.es.cine.terror"),
    ("M+ Ficción Premium", "fox.es.ficcion.premium"),
    ("M+ Ficción 1", "fox.es.ficcion1"),
    ("M+ Ficción 2", "fox.es.ficcion2"),
    ("M+ Iberian Screen", "cima.es.iberian"),
    ("SkyShowtime 1", "fox.es.skyshowtime1"),
]

SPEC = importlib.util.spec_from_file_location("es_fast_channels", SCRIPTS / "es_fast_channels.py")
FAST_CHANNELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FAST_CHANNELS)

POLICY_SPEC = importlib.util.spec_from_file_location("es_xtream_policy", SCRIPTS / "es_xtream_policy.py")
policy_mod = importlib.util.module_from_spec(POLICY_SPEC)
POLICY_SPEC.loader.exec_module(policy_mod)


def programmed_stats(guide: Path) -> tuple[set[str], dict[str, int]]:
    root = ET.parse(guide).getroot()
    counts: dict[str, int] = defaultdict(int)
    for programme in root.findall("programme"):
        ch = programme.get("channel") or ""
        if ch:
            counts[ch] += 1
    return set(counts), dict(counts)


def fast_provider_table(
    counts: dict[str, int],
    baseline_counts: dict[str, int] | None = None,
) -> list[dict[str, object]]:
    by_provider = FAST_CHANNELS.fast_provider_channel_ids()
    rows = []
    for provider in sorted(by_provider):
        ids = by_provider[provider]
        active = [(cid, counts.get(cid, 0)) for cid in sorted(ids) if counts.get(cid, 0) > 0]
        baseline_active = 0
        if baseline_counts is not None:
            baseline_active = sum(1 for cid in ids if baseline_counts.get(cid, 0) > 0)
        missing = sorted(cid for cid in ids if counts.get(cid, 0) == 0)
        rows.append(
            {
                "provider": provider,
                "catalog_channels": len(ids),
                "channels_with_programmes": len(active),
                "baseline_channels_with_programmes": baseline_active,
                "programmes": sum(n for _, n in active),
                "missing_ids": missing,
            }
        )
    return rows


def channel_display_names(guide: Path) -> dict[str, set[str]]:
    root = ET.parse(guide).getroot()
    out: dict[str, set[str]] = {}
    aliases = json.loads((ROOT / "epg" / "aliases.json").read_text(encoding="utf-8"))
    for channel in root.findall("channel"):
        cid = channel.get("id") or ""
        if not cid:
            continue
        names = {n.text.strip() for n in channel.findall("display-name") if n.text and n.text.strip()}
        names.update(aliases.get(cid, []))
        out[cid] = names
    return out


def resolve_name_match(names_map: dict[str, set[str]], stream_name: str) -> list[str]:
    spec = importlib.util.spec_from_file_location("process_epg", SCRIPTS / "process-epg.py")
    epg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(epg)
    key = epg.normalize_channel_name(stream_name)
    hits = []
    for cid, names in names_map.items():
        for name in names:
            if epg.normalize_channel_name(name) == key:
                hits.append(cid)
    return sorted(set(hits))


def verify_user_channels(
    guide: Path,
    programmed: set[str],
    counts: dict[str, int],
) -> list[dict[str, object]]:
    names_map = channel_display_names(guide)
    rows = []
    for stream_name, panel_id in USER_CHANNELS:
        by_id = panel_id in programmed if panel_id else False
        prog_count = counts.get(panel_id or "", 0) if panel_id else 0
        name_hits = resolve_name_match(names_map, stream_name)
        programmed_hits = [cid for cid in name_hits if cid in programmed and counts.get(cid, 0) > 0]
        rows.append(
            {
                "stream": stream_name,
                "panel_epg_id": panel_id,
                "id_has_programmes": by_id,
                "id_programme_count": prog_count,
                "name_match_ids": name_hits,
                "name_match_with_epg": programmed_hits,
            }
        )
    return rows


def load_catalog_rows(pending: list[dict[str, object]]) -> list[dict[str, object]]:
    xtream = json.loads((ROOT / "epg" / "xtream-aliases.json").read_text(encoding="utf-8"))
    by_id: dict[str, str] = {}
    for row in pending:
        epg_id = row.get("epg_id")
        if not isinstance(epg_id, str) or not epg_id.strip():
            continue
        name = str(row.get("name") or "")
        if epg_id not in by_id or (not by_id[epg_id] and name):
            by_id[epg_id] = name
    for epg_id in xtream:
        by_id.setdefault(epg_id, "")
    return [{"epg_id": epg_id, "name": name} for epg_id, name in sorted(by_id.items())]


def xtream_catalog_coverage(
    guide: Path,
    programmed: set[str],
    counts: dict[str, int],
    catalog: list[dict[str, object]],
) -> tuple[dict[str, int], list[dict[str, object]]]:
    spec = importlib.util.spec_from_file_location("process_epg", SCRIPTS / "process-epg.py")
    epg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(epg)
    xtream = json.loads((ROOT / "epg" / "xtream-aliases.json").read_text(encoding="utf-8"))
    aliases = json.loads((ROOT / "epg" / "aliases.json").read_text(encoding="utf-8"))
    denied = policy_mod.denied_xtream_epg_resolve_ids()
    names_map = channel_display_names(guide)

    covered_rows = 0
    covered_by_id_only = 0
    covered_by_name_only = 0
    covered_both = 0
    pending_details: list[dict[str, object]] = []

    for row in catalog:
        epg_id = row.get("epg_id")
        name = str(row.get("name") or "")
        if not isinstance(epg_id, str) or not epg_id.strip():
            pending_details.append({**row, "reason": "missing_epg_id"})
            continue
        if epg_id in denied:
            pending_details.append({**row, "reason": "denied_xtream_epg_resolve"})
            continue
        target = xtream.get(epg_id, epg_id)
        by_id = bool(target in programmed and counts.get(target, 0) > 0)
        name_hits = resolve_name_match(names_map, name)
        by_name = any(cid in programmed and counts.get(cid, 0) > 0 for cid in name_hits)
        if by_id and by_name:
            covered_both += 1
            covered_rows += 1
        elif by_id:
            covered_by_id_only += 1
            covered_rows += 1
        elif by_name:
            covered_by_name_only += 1
            covered_rows += 1
        else:
            reason = "no_programming"
            if target not in programmed and not name_hits:
                reason = "id_not_in_guide"
            elif target in programmed:
                reason = "empty_epg"
            pending_details.append({**row, "reason": reason, "resolve_target": target})

    summary = {
        "catalog_rows": len(catalog),
        "covered_rows": covered_rows,
        "covered_by_id_only": covered_by_id_only,
        "covered_by_name_only": covered_by_name_only,
        "covered_both_id_and_name": covered_both,
        "pending_rows": len(pending_details),
    }
    return summary, pending_details


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--guide", type=Path, required=True)
    parser.add_argument("--pending", type=Path, default=ROOT / "epg" / "xtream-pending-es.json")
    parser.add_argument("--baseline-guide", type=Path)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()

    programmed, counts = programmed_stats(args.guide)
    baseline_programmed, baseline_counts = (
        programmed_stats(args.baseline_guide) if args.baseline_guide else (set(), {})
    )

    pending = json.loads(args.pending.read_text(encoding="utf-8"))
    catalog = load_catalog_rows(pending)
    catalog_summary, still_pending = xtream_catalog_coverage(args.guide, programmed, counts, catalog)

    fast_table = fast_provider_table(counts, baseline_counts or None)
    user_rows = verify_user_channels(args.guide, programmed, counts)

    denied = set(
        json.loads((ROOT / "epg" / "es-xtream-policy.json").read_text(encoding="utf-8")).get(
            "denied_xtream_epg_resolve_ids", []
        )
    )
    fast_ids = set(FAST_CHANNELS.channel_provider_map())
    blocked_fast = sorted(cid for cid in fast_ids if cid in programmed and cid in denied)

    report = {
        "guide": str(args.guide),
        "programmed_channel_ids": len(programmed),
        "programme_total": sum(counts.values()),
        "baseline_programmed_ids": len(baseline_programmed) if args.baseline_guide else None,
        "baseline_programme_total": sum(baseline_counts.values()) if args.baseline_guide else None,
        "xtream_catalog": catalog_summary,
        "fast_providers": fast_table,
        "fast_ids_blocked_by_policy": blocked_fast,
        "user_channel_checks": user_rows,
        "still_pending_sample": still_pending[:80],
        "still_pending_total": len(still_pending),
        "notes": {
            "pluto": (
                "FAST Pluto counts use epg/es-pluto.channels.xml ids, not heuristic prefixes; "
                "hex ids that never hit the API (HTTP 404) stay in missing_ids."
            ),
            "iberian_screen": "M+ Iberian Screen maps to SundanceTV.es (same signal rebrand on M+).",
            "atrescine": "Atrescine and Atrescine 2 share cima.es.a3cine (official Atrescine grid).",
        },
    }

    print(f"Guide: {args.guide}")
    print(f"Channels with programmes: {len(programmed)} ({sum(counts.values())} programmes)")
    if args.baseline_guide:
        print(
            f"Baseline: {len(baseline_programmed)} channels, {sum(baseline_counts.values())} programmes "
            f"(+{len(programmed - baseline_programmed)} ids, "
            f"+{sum(counts.values()) - sum(baseline_counts.values())} programmes)"
        )
    print(
        f"Xtream catalog: {catalog_summary['covered_rows']} / {catalog_summary['catalog_rows']} "
        f"(id={catalog_summary['covered_by_id_only']}, name={catalog_summary['covered_by_name_only']}, "
        f"both={catalog_summary['covered_both_id_and_name']})"
    )

    print("\n| Proveedor | Catálogo | Con EPG (antes) | Con EPG (después) | Programas |")
    print("|---|---:|---:|---:|---:|")
    for row in fast_table:
        before = row.get("baseline_channels_with_programmes")
        before_txt = str(before) if before is not None else "—"
        print(
            f"| {row['provider']} | {row['catalog_channels']} | {before_txt} | "
            f"{row['channels_with_programmes']} | {row['programmes']} |"
        )
        if row["missing_ids"]:
            print(f"  missing: {', '.join(row['missing_ids'])}")

    if blocked_fast:
        print(f"\nWARN: FAST ids bloqueados por política (debería ser 0): {blocked_fast}")

    print("\nCanales comunicados por el usuario:")
    print("| Stream | panel id | EPG por id | EPG por nombre |")
    print("|---|---|:---:|---|")
    for row in user_rows:
        by_id = "sí" if row["id_has_programmes"] else "no"
        by_name = ", ".join(row["name_match_with_epg"]) or "—"
        if row["panel_epg_id"] in denied and row["id_has_programmes"]:
            by_id = "ERROR"
        print(f"| {row['stream']} | {row['panel_epg_id'] or '—'} | {by_id} | {by_name} |")

    if still_pending:
        print(f"\nPendientes ({len(still_pending)} filas); motivo en JSON")
        for row in still_pending[:25]:
            print(f"  - {row.get('name')} ({row.get('epg_id')}): {row.get('reason')}")

    if args.report_json:
        report["still_pending"] = still_pending
        args.report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nJSON: {args.report_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())