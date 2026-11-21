#!/usr/bin/env python3
"""Compare programmed channel IDs between two Spanish XMLTV guides."""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def programmed_ids(path: Path) -> tuple[set[str], dict[str, int]]:
    root = ET.parse(path).getroot()
    counts: Counter[str] = Counter()
    for programme in root.findall("programme"):
        title = (programme.findtext("title") or "").strip()
        ch = programme.get("channel") or ""
        if ch and title:
            counts[ch] += 1
    return set(counts), dict(counts)


def channel_labels(path: Path, ids: set[str]) -> dict[str, str]:
    root = ET.parse(path).getroot()
    labels: dict[str, str] = {}
    for channel in root.findall("channel"):
        cid = channel.get("id") or ""
        if cid in ids:
            names = [n.text.strip() for n in channel.findall("display-name") if n.text and n.text.strip()]
            labels[cid] = names[0] if names else cid
    return labels


MOVISTAR_PANEL = frozenset(
    {
        "movistaraccion.es",
        "movistarclasicos.es",
        "movistarcomedia.es",
        "moviestardrama.es",
        "movistarestrenos.es",
        "movistardcine.es",
    }
)
PANEL_CLONE_TARGETS = {
    "movistaraccion.es": "cpacci",
    "movistarcomedia.es": "cpcome",
    "movistarclasicos.es": "mclas",
    "moviestardrama.es": "cpcole",
}

SITE_RE = re.compile(r"^[a-z0-9]+$", re.I)
DISCOVERED_RE = re.compile(r"^MovistarPlus\.([a-z0-9_-]+)$", re.I)


def loss_reason(cid: str, labels: dict[str, str]) -> str:
    m = DISCOVERED_RE.match(cid)
    if m:
        stem = m.group(1)
        return (
            f"id descubierto MovistarPlus.{stem}; falta discover-channels o el canal ya no está en la parrilla"
        )
    if cid in MOVISTAR_PANEL:
        target = PANEL_CLONE_TARGETS.get(cid)
        if target:
            return (
                f"clone de panel denegado (denied_xtream_clone_ids); "
                f"parrilla real en {target}"
            )
        return "id de panel Xtream denegado; sin parrilla propia"
    if cid in {"skysho", "fox.es.skyshowtime1"}:
        return "bucle SkyShowtime; bloqueado por política (sin EPG falsa)"
    if cid.startswith("cima.es."):
        return "canal virtual M+; sin fuente scrape o bloqueado en denied_xtream_epg_resolve"
    if len(cid) >= 20 and SITE_RE.match(cid) is None and "." in cid:
        return "FAST / nacional con id largo; revisar fuente FAST o merge"
    if cid.isdigit() or (len(cid) <= 6 and cid.isalnum()):
        return "id Movistar corto; posible renombre (p. ej. sin prefijo MovistarPlus.)"
    return "revisar fuente secundaria o canal retirado del operador"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--guide", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()

    base_ids, base_counts = programmed_ids(args.baseline)
    guide_ids, guide_counts = programmed_ids(args.guide)
    base_labels = channel_labels(args.baseline, base_ids)
    lost = sorted(base_ids - guide_ids)
    gained = sorted(guide_ids - base_ids)

    by_prefix: dict[str, list[str]] = defaultdict(list)
    for cid in lost:
        if cid.startswith("MovistarPlus."):
            by_prefix["MovistarPlus.*"].append(cid)
        elif re.match(r"^[0-9a-f]{20,}$", cid):
            by_prefix["Pluto/hex"].append(cid)
        elif cid in MOVISTAR_PANEL or cid.endswith(".es"):
            by_prefix["panel/.es"].append(cid)
        else:
            by_prefix["otros"].append(cid)

    rows = []
    for cid in lost:
        renamed_to: str | None = None
        m = DISCOVERED_RE.match(cid)
        if m:
            stem = m.group(1)
            if stem in guide_ids:
                renamed_to = stem
        elif f"MovistarPlus.{cid}" in guide_ids:
            renamed_to = f"MovistarPlus.{cid}"
        reason = loss_reason(cid, base_labels)
        if renamed_to:
            reason = (
                f"id renombrado → {renamed_to} "
                f"({guide_counts.get(renamed_to, 0)} prog); en grab limpio sin discover usa stem corto"
            )
        rows.append(
            {
                "channel_id": cid,
                "display_name": base_labels.get(cid, ""),
                "baseline_programmes": base_counts.get(cid, 0),
                "renamed_to": renamed_to,
                "reason": reason,
            }
        )

    report = {
        "baseline": str(args.baseline),
        "guide": str(args.guide),
        "baseline_programmed_ids": len(base_ids),
        "guide_programmed_ids": len(guide_ids),
        "lost_ids": len(lost),
        "gained_ids": len(gained),
        "lost_by_bucket": {k: len(v) for k, v in sorted(by_prefix.items())},
        "lost_channels": rows,
        "gained_sample": gained[:50],
    }

    print(f"Baseline: {len(base_ids)} ids con programación")
    print(f"Nueva:    {len(guide_ids)} ids con programación")
    print(f"Perdidos: {len(lost)} | Nuevos: {len(gained)}")
    print("\nPérdidas por grupo:")
    for k, v in sorted(by_prefix.items()):
        print(f"  {k}: {len(v)}")
    print("\nIDs MovistarPlus perdidos (muestra):")
    for cid in by_prefix.get("MovistarPlus.*", [])[:15]:
        print(f"  {cid} ({base_counts.get(cid, 0)} prog) {base_labels.get(cid, '')[:40]}")
    print("\nPanel Movistar (colisiones Xtream):")
    for cid in sorted(MOVISTAR_PANEL):
        target = PANEL_CLONE_TARGETS.get(cid)
        target_prog = guide_counts.get(target, 0) if target else 0
        if cid in lost:
            print(
                f"  {cid}: sin clone en nueva guía; EPG en {target or '?'} "
                f"({target_prog} prog)"
            )
        elif cid in guide_ids:
            print(f"  {cid}: OK clone ({guide_counts.get(cid, 0)} prog) — revisar política")

    if args.report_json:
        args.report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nJSON: {args.report_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())