#!/usr/bin/env python3
"""Italy national guide checks before CI publication."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
_MAX_IDENTITY_LOSS = 0.20
_MIN_CHANNELS = 80
_MIN_PROGRAMMES = 5000
REFERENCE_CURATED = 66
REFERENCE_USEFUL = 65
REFERENCE_STREAMS = 116

NUMERIC_ID_RE = re.compile(r"^\d+$")


def _load_it_epg():
    spec = importlib.util.spec_from_file_location("it_epg", _SCRIPT_DIR / "it-epg.py")
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


def identity_coverage_report(previous: Path, generated: Path, *, identity_key, max_loss_ratio: float) -> dict:
    old_root = ET.parse(previous).getroot()
    new_root = ET.parse(generated).getroot()
    old_ids = programmed_channel_ids(old_root)
    new_ids = programmed_channel_ids(new_root)
    old_map = channel_id_to_identity(old_root, identity_key)
    new_map = channel_id_to_identity(new_root, identity_key)
    old_identities = set(old_map.values())
    new_identities = set(new_map.values())
    lost_identities = old_identities - new_identities
    ratio = len(lost_identities) / len(old_identities) if old_identities else 0.0
    return {
        "old_programmed_ids": len(old_ids),
        "new_programmed_ids": len(new_ids),
        "lost_identities_count": len(lost_identities),
        "identity_loss_ratio": ratio,
        "exceeds_threshold": bool(old_identities and ratio > max_loss_ratio),
    }


def validate_tree(guide_path: Path) -> tuple[set[str], int]:
    root = ET.parse(guide_path).getroot()
    channels = {c.get("id") for c in root.findall("channel")}
    programmes = root.findall("programme")
    if len(channels) < _MIN_CHANNELS:
        raise SystemExit(f"Italy guide too small: {len(channels)} channels")
    if len(programmes) < _MIN_PROGRAMMES:
        raise SystemExit(f"Italy guide too small: {len(programmes)} programmes")
    if any(not p.get("start") or not p.get("stop") or p.get("channel") not in channels for p in programmes):
        raise SystemExit("Italy guide has invalid programme references")
    if any(not channel_id or NUMERIC_ID_RE.fullmatch(channel_id or "") for channel_id in channels):
        raise SystemExit("Italy guide has empty or numeric-only channel ids")
    dup = [c.get("id") for c in root.findall("channel")]
    if len(dup) != len(set(dup)):
        raise SystemExit("Italy guide has duplicate channel ids")
    return channels, len(programmes)


def validate_xtream_layer(guide_path: Path, aliases_path: Path, xtream_path: Path, *, process_epg) -> dict:
    root = ET.parse(guide_path).getroot()
    channels = {c.get("id") for c in root.findall("channel") if c.get("id")}
    programmed = programmed_channel_ids(root)
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    configured = json.loads(xtream_path.read_text(encoding="utf-8")) if xtream_path.is_file() else {}
    if configured:
        raise SystemExit("Italy xtream-aliases-it.json must remain empty")
    missing_alias = sorted(set(aliases) - channels)
    if missing_alias:
        raise SystemExit("Display alias keys missing from guide: " + ", ".join(missing_alias[:8]))
    return {"alias_ids": len(aliases), "clone_ids": 0}


def validate_curated_coverage(guide_path: Path, aliases_path: Path) -> dict:
    from it_catalog_match import client_coverage_report, load_rejected_streams, validate_rejected_not_in_aliases

    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    rejected = load_rejected_streams()
    violations = validate_rejected_not_in_aliases(aliases, rejected)
    if violations:
        raise SystemExit("Rejected streams in aliases-it.json: " + ", ".join(violations))
    report = client_coverage_report(guide_path, aliases=aliases)
    if report["curated_mappings_verified"] < REFERENCE_CURATED:
        raise SystemExit(
            "Curated alias coverage below reference: "
            f"{report['curated_mappings_verified']}/{REFERENCE_STREAMS} "
            f"(expected >={REFERENCE_CURATED} with guide programmes)"
        )
    if report["curated_with_useful_programming"] < REFERENCE_USEFUL:
        raise SystemExit(
            "Useful programming coverage below reference: "
            f"{report['curated_with_useful_programming']}/{REFERENCE_STREAMS}"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    parser.add_argument("previous", type=Path, nargs="?", default=Path("guide-it.xml"))
    parser.add_argument("--aliases", type=Path, default=_ROOT / "epg" / "aliases-it.json")
    parser.add_argument("--xtream-aliases", type=Path, default=_ROOT / "epg" / "xtream-aliases-it.json")
    parser.add_argument("--max-identity-loss", type=float, default=_MAX_IDENTITY_LOSS)
    parser.add_argument("--skip-coverage", action="store_true")
    args = parser.parse_args()
    it = _load_it_epg()
    process_epg = _load_process_epg()
    channels, programme_count = validate_tree(args.generated)
    print(f"Validated Italy guide structure: {len(channels)} channels, {programme_count} programmes")
    if args.previous.is_file() and args.previous.stat().st_size > 0:
        report = identity_coverage_report(
            args.previous, args.generated, identity_key=it.identity_key, max_loss_ratio=args.max_identity_loss
        )
        if report["exceeds_threshold"]:
            raise SystemExit(f"Identity coverage loss {report['identity_loss_ratio']:.1%} exceeds threshold")
    validate_xtream_layer(args.generated, args.aliases, args.xtream_aliases, process_epg=process_epg)
    if not args.skip_coverage:
        cov = validate_curated_coverage(args.generated, args.aliases)
        print(
            "Italy curated coverage (manual alias layer; panel EPG NULL): "
            f"IPTVnator auto {cov['iptvnator_auto_hits']}/116, "
            f"after aliases {cov['iptvnator_after_aliases']}/116; "
            f"AquaPlay auto {cov['aquaplay_auto_hits']}/116, "
            f"after aliases {cov['aquaplay_after_aliases']}/116; "
            f"with useful programming {cov['curated_with_useful_programming']}/116"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())