#!/usr/bin/env python3
"""Netherlands national guide checks used before CI publication."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xmltv_gzip import parse_xmltv  # noqa: E402

_MAX_IDENTITY_LOSS = 0.20
_MIN_REAL_COVERAGE = 150
_MIN_REAL_PCT = 88.0
DEFAULT_CATALOG = _ROOT / "temp" / "nl-xtream-catalog.json"


def _load_nl_epg():
    spec = importlib.util.spec_from_file_location("nl_epg", _SCRIPT_DIR / "nl-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_process_epg():
    spec = importlib.util.spec_from_file_location("process_epg", _SCRIPT_DIR / "process-epg.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def programmed_channel_ids(root: ET.Element) -> set[str]:
    channel_ids = {c.get("id") for c in root.findall("channel") if c.get("id")}
    return {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip() and p.get("channel") in channel_ids
    }


def channel_id_to_identity(root: ET.Element, identity_key) -> dict[str, tuple]:
    programmed = programmed_channel_ids(root)
    mapping: dict[str, tuple] = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id")
        if not channel_id or channel_id not in programmed:
            continue
        names = [node.text.strip() for node in channel.findall("display-name") if (node.text or "").strip()]
        label = names[0] if names else channel_id
        mapping[channel_id] = identity_key(label)
    return mapping


def identity_coverage_report(
    previous: Path,
    generated: Path,
    *,
    identity_key,
    max_loss_ratio: float = _MAX_IDENTITY_LOSS,
) -> dict[str, object]:
    old_root = parse_xmltv(previous)
    new_root = ET.parse(generated).getroot()
    old_ids = programmed_channel_ids(old_root)
    new_ids = programmed_channel_ids(new_root)
    old_map = channel_id_to_identity(old_root, identity_key)
    new_map = channel_id_to_identity(new_root, identity_key)
    old_identities = set(old_map.values())
    new_identities = set(new_map.values())
    lost_identities = old_identities - new_identities
    lost_ids = old_ids - new_ids
    renamed_ids = sorted(
        channel_id
        for channel_id in lost_ids
        if channel_id in old_map and old_map[channel_id] in new_identities
    )
    real_lost_ids = sorted(channel_id for channel_id in lost_ids if channel_id not in renamed_ids)
    ratio = len(lost_identities) / len(old_identities) if old_identities else 0.0
    id_ratio = len(real_lost_ids) / len(old_ids) if old_ids else 0.0
    return {
        "old_programmed_ids": len(old_ids),
        "new_programmed_ids": len(new_ids),
        "old_identities": len(old_identities),
        "new_identities": len(new_identities),
        "lost_identities_count": len(lost_identities),
        "identity_loss_ratio": ratio,
        "renamed_programmed_ids": renamed_ids,
        "real_lost_programmed_ids": real_lost_ids,
        "raw_id_loss_ratio": id_ratio,
        "exceeds_threshold": bool(old_identities and ratio > max_loss_ratio),
        "max_loss_ratio": max_loss_ratio,
    }


def validate_tree(guide_path: Path) -> tuple[set[str], int]:
    root = ET.parse(guide_path).getroot()
    channels = {c.get("id") for c in root.findall("channel")}
    programmes = root.findall("programme")
    if not channels or not programmes:
        raise SystemExit("Netherlands guide is empty")
    if any(not p.get("start") or not p.get("stop") or p.get("channel") not in channels for p in programmes):
        raise SystemExit("Netherlands guide has invalid programme references")
    if any(not channel_id or channel_id.isdigit() for channel_id in channels):
        raise SystemExit("Netherlands guide has empty or numeric-only channel ids")
    return channels, len(programmes)


def validate_xtream_layer(
    guide_path: Path,
    aliases_path: Path,
    xtream_path: Path,
    *,
    process_epg,
) -> dict[str, object]:
    root = ET.parse(guide_path).getroot()
    channels = {c.get("id") for c in root.findall("channel") if c.get("id")}
    programmed = programmed_channel_ids(root)
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    configured = json.loads(xtream_path.read_text(encoding="utf-8"))
    missing_alias = sorted(set(aliases) - channels)
    missing_clones = sorted(set(configured) - channels)
    resolved, skipped = process_epg.filter_configured_xtream_aliases(
        configured,
        channels,
        programmed,
        tolerate_missing_original=True,
    )
    orphan_clones = []
    invalid_clones = []
    for clone_id, original_id in resolved.items():
        if clone_id not in channels:
            continue
        effective = resolved[clone_id]
        if effective not in channels:
            orphan_clones.append(f"{clone_id}->{original_id} (resolved {effective})")
        elif not root.findall(f"programme[@channel='{clone_id}']"):
            invalid_clones.append(clone_id)
    applied = sorted(clone for clone in resolved if clone in channels)
    return {
        "missing_display_alias_keys": missing_alias,
        "missing_xtream_clone_ids": missing_clones,
        "orphan_clones": orphan_clones,
        "invalid_clones": invalid_clones,
        "skipped_configured_clones": skipped,
        "applied_clone_ids": applied,
        "resolved_clone_map": resolved,
    }


def validate_real_coverage(
    guide_path: Path,
    catalog_path: Path,
    aliases_path: Path | None = None,
) -> dict[str, object]:
    from nl_catalog_match import real_client_coverage

    aliases = {}
    if aliases_path and aliases_path.is_file():
        aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    report = real_client_coverage(guide_path, catalog_path, aliases=aliases)
    if report["iptvnator_hits"] < _MIN_REAL_COVERAGE or report["iptvnator_pct"] < _MIN_REAL_PCT:
        raise SystemExit(
            "Netherlands real IPTVnator coverage below threshold: "
            f"{report['iptvnator_hits']}/{report['catalog_real_streams']} "
            f"({report['iptvnator_pct']}%)"
        )
    if report["aquaplay_hits"] < _MIN_REAL_COVERAGE:
        raise SystemExit(
            "Netherlands AquaPlay coverage below threshold: "
            f"{report['aquaplay_hits']}/{report['catalog_real_streams']}"
        )
    nh = report.get("nh_nieuws") or []
    if nh and not all(row.get("ok") for row in nh):
        raise SystemExit("NH Nieuws still resolves to NPO Nieuws panel id")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    parser.add_argument("previous", type=Path, nargs="?", default=Path("guides/guide-nl.xml"))
    parser.add_argument("--aliases", type=Path, default=Path("epg/aliases-nl.json"))
    parser.add_argument("--xtream-aliases", type=Path, default=Path("epg/xtream-aliases-nl.json"))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--max-identity-loss", type=float, default=_MAX_IDENTITY_LOSS)
    parser.add_argument("--skip-real-coverage", action="store_true")
    args = parser.parse_args()
    nl = _load_nl_epg()
    process_epg = _load_process_epg()
    channels, programme_count = validate_tree(args.generated)
    print(f"Validated Netherlands guide: {len(channels)} channels, {programme_count} programmes")
    if args.previous.is_file() and args.previous.stat().st_size > 0:
        report = identity_coverage_report(
            args.previous,
            args.generated,
            identity_key=nl.identity_key,
            max_loss_ratio=args.max_identity_loss,
        )
        print(
            "Netherlands identity coverage: "
            f"{report['old_identities']} -> {report['new_identities']} logical channels "
            f"({report['lost_identities_count']} lost identities, "
            f"{len(report['renamed_programmed_ids'])} programmed ID renames only)"
        )
        if report["exceeds_threshold"]:
            raise SystemExit(
                "Refusing publication: programmed logical channel coverage fell by "
                f"{report['identity_loss_ratio']:.1%}"
            )
    xtream_report = validate_xtream_layer(
        args.generated,
        args.aliases,
        args.xtream_aliases,
        process_epg=process_epg,
    )
    if xtream_report["orphan_clones"]:
        raise SystemExit("Netherlands clone without original: " + ", ".join(xtream_report["orphan_clones"]))
    if xtream_report["invalid_clones"]:
        raise SystemExit("Netherlands clone without programmes: " + ", ".join(xtream_report["invalid_clones"]))
    if args.catalog.is_file() and not args.skip_real_coverage:
        coverage = validate_real_coverage(args.generated, args.catalog, args.aliases)
        print(
            "Netherlands real client coverage: "
            f"IPTVnator {coverage['iptvnator_hits']}/{coverage['catalog_real_streams']} "
            f"({coverage['iptvnator_pct']}%), "
            f"AquaPlay {coverage['aquaplay_hits']}/{coverage['catalog_real_streams']} "
            f"({coverage['aquaplay_pct']}%)"
        )
    elif not args.catalog.is_file():
        print(f"::warning::Skipping real coverage: catalog missing at {args.catalog}", file=sys.stderr)
    print(
        "Validated Netherlands Xtream layer: "
        f"{len(channels)} channels, {len(xtream_report['applied_clone_ids'])} clone IDs applied"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())