#!/usr/bin/env python3
"""Build epg/aliases-pt.json and epg/xtream-aliases-pt.json from a merged Portuguese guide."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from pt_catalog_match import (  # noqa: E402
    build_mappings_from_trials,
    load_catalog_json,
)

DEFAULT_CATALOG = _ROOT / "temp" / "pt-xtream-catalog.json"
DEFAULT_GUIDE = _ROOT / "temp" / "guide-pt.final.xml"
DEFAULT_TRIAL = _ROOT / "temp" / "pt-trial"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
    parser.add_argument("--aliases-out", type=Path, default=_ROOT / "epg" / "aliases-pt.json")
    parser.add_argument("--clones-out", type=Path, default=_ROOT / "epg" / "xtream-aliases-pt.json")
    parser.add_argument("--trial-dir", type=Path, default=DEFAULT_TRIAL)
    parser.add_argument("--expected-coverage", type=int, default=168)
    args = parser.parse_args()
    if not args.catalog.is_file():
        raise SystemExit(f"Catalog not found: {args.catalog}")
    if not args.guide.is_file():
        raise SystemExit(f"Guide not found: {args.guide}")
    rows = load_catalog_json(args.catalog)
    spec = importlib.util.spec_from_file_location("pt_epg", _ROOT / "scripts" / "pt-epg.py")
    pt_epg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pt_epg)
    if not args.trial_dir.is_dir():
        raise SystemExit(f"Trial directory not found: {args.trial_dir}")
    aliases, clones, covered = build_mappings_from_trials(
        rows,
        args.guide,
        args.trial_dir,
        pt_epg.identity_key,
    )
    linear_total = sum(1 for row in rows if "VIP" not in str(row.get("name", "")))
    print(
        f"Portuguese mappings: {len(covered)}/{len(rows)} catalog rows "
        f"({len(covered)}/{linear_total} linear), "
        f"{len(aliases)} alias channels, {len(clones)} clone ids"
    )
    if args.expected_coverage and len(covered) < args.expected_coverage:
        print(
            f"::warning::Portuguese alias build covered {len(covered)} rows, "
            f"expected at least {args.expected_coverage}",
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
    pending_path = _ROOT / "epg" / "xtream-pending-pt.json"
    pending_path.write_text("[]\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())