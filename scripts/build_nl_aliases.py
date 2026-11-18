#!/usr/bin/env python3
"""Build epg/aliases-nl.json and epg/xtream-aliases-nl.json from a merged Dutch guide."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from es_xtream_policy import filter_numeric_stream_clones  # noqa: E402
from nl_catalog_match import build_mappings_from_guide, clean_catalog_rows, load_catalog_json  # noqa: E402

DEFAULT_CATALOG = _ROOT / "temp" / "nl-xtream-catalog.json"
DEFAULT_GUIDE = _ROOT / "temp" / "guide-nl.final.xml"
MIN_COVERAGE = 150


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
    parser.add_argument("--aliases-out", type=Path, default=_ROOT / "epg" / "aliases-nl.json")
    parser.add_argument("--clones-out", type=Path, default=_ROOT / "epg" / "xtream-aliases-nl.json")
    parser.add_argument("--min-coverage", type=int, default=MIN_COVERAGE)
    args = parser.parse_args()
    if not args.catalog.is_file():
        raise SystemExit(f"Catalog not found: {args.catalog}")
    if not args.guide.is_file():
        raise SystemExit(f"Guide not found: {args.guide}")
    rows = clean_catalog_rows(load_catalog_json(args.catalog))
    aliases, clones, covered = build_mappings_from_guide(rows, args.guide)
    clones = filter_numeric_stream_clones(clones)
    if clones:
        print(f"::warning::Dropping {len(clones)} auto-generated NL clones; use curated xtream-aliases only", file=sys.stderr)
        clones = {}
    print(
        f"Netherlands mappings: {len(covered)}/{len(rows)} catalog streams, "
        f"{len(aliases)} alias channels, {len(clones)} clone ids"
    )
    if len(covered) < args.min_coverage:
        print(
            f"::warning::Netherlands alias build covered {len(covered)} rows, "
            f"expected at least {args.min_coverage}",
            file=sys.stderr,
        )
    args.aliases_out.parent.mkdir(parents=True, exist_ok=True)
    args.aliases_out.write_text(
        json.dumps(dict(sorted(aliases.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.clones_out.write_text(
        json.dumps(dict(sorted(clones.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())