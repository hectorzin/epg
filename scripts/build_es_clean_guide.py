#!/usr/bin/env python3
"""Build Spanish EPG from live sources only (no guides/guide-es.xml input)."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMP = ROOT / "temp"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from npm_cmd import npm_available, run_npm  # noqa: E402


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, check=check)


def feed_usable(path: Path, *, min_bytes: int = 50) -> bool:
    return path.is_file() and path.stat().st_size >= min_bytes


def movistar_has_discovered_channels(path: Path) -> bool:
    if not feed_usable(path):
        return False
    for ch in ET.parse(path).getroot().findall("channel"):
        cid = ch.get("id") or ""
        if cid.startswith("MovistarPlus."):
            return True
    return False


def main() -> int:
    if not npm_available():
        raise SystemExit("npm is not available; install Node.js to run a clean Spanish grab")

    work = TEMP / "clean-grab"
    work.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "guides" / "guide-es.xml"
    before = TEMP / "guide-es.before.xml"
    if baseline.is_file():
        shutil.copyfile(baseline, before)

    movistar = work / "movistar.xml"
    if not movistar_has_discovered_channels(movistar):
        run_npm(
            [
                "run",
                "grab",
                "--",
                "--channels=sites/movistarplus.es/movistarplus.es.channels.xml",
                "--discover-channels",
                "--maxConnections=3",
                "--days=2",
                "--timeout=10000",
                f"--output={movistar}",
            ],
            cwd=ROOT,
            check=True,
        )
    else:
        print(f"Reusing {movistar} (contains MovistarPlus.* discovered channels)")

    orange = work / "orange.xml"
    if not feed_usable(orange):
        try:
            run(
                [
                    "node",
                    "scripts/commands/epg/grab-orange.cjs",
                    "--channels=sites/orangetv.orange.es/orange-selected.channels.xml",
                    "--days=2",
                    f"--output={orange}",
                ]
            )
        except subprocess.CalledProcessError:
            orange.write_bytes(b"")

    elpais = work / "elpais.xml"
    if not feed_usable(elpais):
        try:
            run_npm(
                [
                    "run",
                    "grab",
                    "--",
                    "--channels=sites/programacion-tv.elpais.com/elpais-selected.channels.xml",
                    "--maxConnections=3",
                    "--days=2",
                    "--timeout=10000",
                    f"--output={elpais}",
                ],
                cwd=ROOT,
                check=True,
            )
        except subprocess.CalledProcessError:
            elpais.write_bytes(b"")

    epgshare = work / "epgshare.xml"
    if not feed_usable(epgshare):
        run(
            [
                sys.executable,
                str(SCRIPTS / "grab_epgshare.py"),
                "--channels=epg/epgshare-rally.channels.xml",
                "--days=2",
                f"--output={epgshare}",
            ]
        )

    fast = work / "fast.xml"
    if not feed_usable(fast):
        run(
            [
                sys.executable,
                str(SCRIPTS / "grab_spanish_fast.py"),
                "--atrescine",
                f"--output={fast}",
                f"--work-dir={work / 'fast-grab'}",
            ]
        )
    else:
        print(f"Reusing {fast}")

    merged = work / "guide.merged.xml"
    merge_cmd = [
        sys.executable,
        str(SCRIPTS / "merge-guides.py"),
        "--movistar",
        str(movistar),
        "--orange",
        str(orange),
        "--elpais",
        str(elpais),
        "--epgshare",
        str(epgshare),
        "--fast",
        str(fast),
        "--output",
        str(merged),
    ]
    run(merge_cmd)

    after = TEMP / "guide-es.clean.xml"
    run(
        [
            sys.executable,
            str(SCRIPTS / "process-epg.py"),
            "--input",
            str(merged),
            "--output",
            str(after),
            "--min-channels",
            "100",
            "--min-programmes",
            "1000",
        ]
    )

    compare_json = TEMP / "guide-id-compare.json"
    compare_cmd = [
        sys.executable,
        str(SCRIPTS / "es_guide_id_compare.py"),
        "--baseline",
        str(baseline if baseline.is_file() else before),
        "--guide",
        str(after),
        "--report-json",
        str(compare_json),
    ]
    run(compare_cmd)

    report_args = [
        sys.executable,
        str(SCRIPTS / "es_coverage_report.py"),
        "--guide",
        str(after),
        "--report-json",
        str(TEMP / "coverage-report.json"),
    ]
    if before.is_file():
        report_args.extend(["--baseline-guide", str(before)])
    run(report_args)
    print(f"Wrote {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())