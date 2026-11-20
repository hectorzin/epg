#!/usr/bin/env python3
"""National guide publication checks (programmed coverage with policy exemptions)."""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from es_xtream_policy import split_policy_exempt_losses  # noqa: E402
from xmltv_gzip import parse_xmltv  # noqa: E402

MAX_PROGRAMMED_LOSS = 0.20


def programmed_channel_ids(root: ET.Element) -> set[str]:
    channel_ids = {c.get("id") for c in root.findall("channel") if c.get("id")}
    return {
        p.get("channel")
        for p in root.findall("programme")
        if (p.findtext("title") or "").strip() and p.get("channel") in channel_ids
    }


def validate_programme_refs(root: ET.Element) -> None:
    channel_ids = {c.get("id") for c in root.findall("channel")}
    programmes = root.findall("programme")
    if root.tag != "tv" or not channel_ids:
        raise SystemExit("Guide has no channels")
    if not programmes:
        raise SystemExit("Guide has no programmes")
    invalid = [
        p
        for p in programmes
        if not p.get("start") or not p.get("stop") or p.get("channel") not in channel_ids
    ]
    if invalid:
        raise SystemExit(f"Guide has {len(invalid)} invalid programme channel references")


def programmed_coverage_report(
    previous: Path,
    generated: Path,
    *,
    max_loss_ratio: float = MAX_PROGRAMMED_LOSS,
) -> dict[str, object]:
    old_root = parse_xmltv(previous)
    new_root = ET.parse(generated).getroot()
    old_ids = programmed_channel_ids(old_root)
    new_ids = programmed_channel_ids(new_root)
    lost = old_ids - new_ids
    exempt, real_lost = split_policy_exempt_losses(lost)
    raw_ratio = len(lost) / len(old_ids) if old_ids else 0.0
    real_ratio = len(real_lost) / len(old_ids) if old_ids else 0.0
    return {
        "old_programmed": len(old_ids),
        "new_programmed": len(new_ids),
        "lost_all": sorted(lost),
        "lost_policy_exempt": sorted(exempt),
        "lost_real": sorted(real_lost),
        "raw_loss_ratio": raw_ratio,
        "real_loss_ratio": real_ratio,
        "exceeds_threshold": bool(old_ids and real_ratio > max_loss_ratio),
        "max_loss_ratio": max_loss_ratio,
    }


def enforce_programmed_coverage(report: dict[str, object], *, region: str) -> None:
    if not report.get("exceeds_threshold"):
        exempt = report.get("lost_policy_exempt") or []
        if exempt and report.get("raw_loss_ratio", 0) > MAX_PROGRAMMED_LOSS:
            print(
                f"{region}: raw programmed channel coverage fell by "
                f"{report['raw_loss_ratio']:.1%} ({len(report['lost_all'])}/{report['old_programmed']}) "
                f"but {len(exempt)} policy-exempt (numeric/denied) — real loss "
                f"{report['real_loss_ratio']:.1%} ({len(report['lost_real'])}/{report['old_programmed']})"
            )
        return
    raise SystemExit(
        f"Refusing publication: programmed channel coverage fell by "
        f"{report['real_loss_ratio']:.1%} ({len(report['lost_real'])}/{report['old_programmed']})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    parser.add_argument("previous", type=Path, nargs="?", default=None)
    parser.add_argument("--region", default="National")
    parser.add_argument("--max-loss", type=float, default=MAX_PROGRAMMED_LOSS)
    args = parser.parse_args()
    root = ET.parse(args.generated).getroot()
    validate_programme_refs(root)
    channels = {c.get("id") for c in root.findall("channel")}
    programmes = root.findall("programme")
    print(f"Validated {args.region} guide: {len(channels)} channels, {len(programmes)} programmes")
    if args.previous and args.previous.is_file() and args.previous.stat().st_size > 0:
        report = programmed_coverage_report(args.previous, args.generated, max_loss_ratio=args.max_loss)
        enforce_programmed_coverage(report, region=args.region)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())