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
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from xmltv_gzip import parse_xmltv  # noqa: E402

_MAX_IDENTITY_LOSS = 0.20
_MIN_CHANNELS = 80
_MIN_PROGRAMMES = 5000
REFERENCE_CURATED = 66
REFERENCE_USEFUL = 65
REFERENCE_STREAMS = 116
DEFAULT_CATALOG = _ROOT / "temp" / "it-trial" / "xtream-it-catalog.json"
IPTVNATOR_DB = Path.home() / ".iptvnator" / "databases" / "iptvnator.db"

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
    old_root = parse_xmltv(previous)
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
    validate_channel_layout(root)
    return channels, len(programmes)


def validate_channel_layout(root: ET.Element) -> None:
    from xmltv_channel import channel_children_ordered

    for channel in root.findall("channel"):
        channel_id = channel.get("id") or ""
        if not channel_children_ordered(channel):
            raise SystemExit(f"Italy guide DTD order violation on channel {channel_id!r}")
        display_names = channel.findall("display-name")
        if not display_names:
            raise SystemExit(f"Italy guide channel {channel_id!r} has no display-name")
        first = (display_names[0].text or "").strip()
        if not first:
            raise SystemExit(f"Italy guide channel {channel_id!r} has empty first display-name")


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


def private_catalog_available(catalog: Path) -> bool:
    return catalog.is_file() or IPTVNATOR_DB.is_file()


def load_coverage_catalog_rows(catalog: Path | None) -> list[dict]:
    from it_catalog_match import clean_catalog_rows, load_catalog_json, load_streams_db

    if catalog and catalog.is_file():
        return clean_catalog_rows(load_catalog_json(catalog))
    if IPTVNATOR_DB.is_file():
        return load_streams_db()
    raise FileNotFoundError(
        f"No Italian Xtream catalog at {catalog!s} and no IPTVnator DB at {IPTVNATOR_DB}"
    )


def validate_curated_coverage(
    guide_path: Path,
    aliases_path: Path,
    *,
    catalog: Path | None = None,
) -> dict:
    from it_catalog_match import client_coverage_report, load_rejected_streams, validate_rejected_not_in_aliases

    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    rejected = load_rejected_streams()
    violations = validate_rejected_not_in_aliases(aliases, rejected)
    if violations:
        raise SystemExit("Rejected streams in aliases-it.json: " + ", ".join(violations))
    rows = load_coverage_catalog_rows(catalog)
    report = client_coverage_report(guide_path, aliases=aliases, catalog_rows=rows)
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
    parser.add_argument("previous", type=Path, nargs="?", default=Path("guides/guide-it.xml"))
    parser.add_argument("--aliases", type=Path, default=_ROOT / "epg" / "aliases-it.json")
    parser.add_argument("--xtream-aliases", type=Path, default=_ROOT / "epg" / "xtream-aliases-it.json")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
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
    if args.skip_coverage:
        print("Italy curated client coverage skipped (--skip-coverage)", file=sys.stderr)
    elif private_catalog_available(args.catalog):
        catalog_hint = args.catalog if args.catalog.is_file() else IPTVNATOR_DB
        try:
            cov = validate_curated_coverage(
                args.generated,
                args.aliases,
                catalog=args.catalog if args.catalog.is_file() else None,
            )
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"::warning::Skipping Italy curated client coverage: {exc}", file=sys.stderr)
        else:
            print(
                "Italy curated coverage (private catalog; manual alias layer; panel EPG NULL): "
                f"IPTVnator auto {cov['iptvnator_auto_hits']}/{REFERENCE_STREAMS}, "
                f"after aliases {cov['iptvnator_after_aliases']}/{REFERENCE_STREAMS}; "
                f"AquaPlay auto {cov['aquaplay_auto_hits']}/{REFERENCE_STREAMS}, "
                f"after aliases {cov['aquaplay_after_aliases']}/{REFERENCE_STREAMS}; "
                f"with useful programming {cov['curated_with_useful_programming']}/{REFERENCE_STREAMS} "
                f"(catalog {catalog_hint})"
            )
    else:
        print(
            "::warning::Skipping Italy curated client coverage: no private Xtream catalog "
            f"(checked {args.catalog} and {IPTVNATOR_DB}); CI cannot verify "
            f"{REFERENCE_CURATED}/{REFERENCE_STREAMS} curated / {REFERENCE_USEFUL}/{REFERENCE_STREAMS} useful",
            file=sys.stderr,
        )
    print(f"Validated Italy Xtream layer: {len(channels)} channels, alias ids {len(json.loads(args.aliases.read_text(encoding='utf-8')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())