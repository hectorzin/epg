#!/usr/bin/env python3
"""Build temp/ Spanish test guide: baseline guide-es + FAST merge + process-epg."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMP = ROOT / "temp"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from npm_cmd import npm_available, run_npm  # noqa: E402

_MERGE_SPEC = importlib.util.spec_from_file_location("merge_guides", SCRIPTS / "merge-guides.py")
_merge = importlib.util.module_from_spec(_MERGE_SPEC)
_MERGE_SPEC.loader.exec_module(_merge)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    TEMP.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "guides" / "guide-es.xml"
    if not baseline.is_file():
        raise SystemExit(f"Missing {baseline}")

    before = TEMP / "guide-es.before.xml"
    shutil.copyfile(baseline, before)

    fast_out = TEMP / "fast.xml"
    grab_fast = SCRIPTS / "grab_spanish_fast.py"
    run([sys.executable, str(grab_fast), "--output", str(fast_out)])

    merged = TEMP / "guide.merged.xml"
    merge_cmd = [
        sys.executable,
        str(SCRIPTS / "merge-guides.py"),
        "--movistar",
        str(before),
        "--fast",
        str(fast_out),
        "--output",
        str(merged),
    ]
    run(merge_cmd)

    after = TEMP / "guide-es.after.xml"
    proc_cmd = [
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
    run(proc_cmd)

    report = SCRIPTS / "es_coverage_report.py"
    run(
        [
            sys.executable,
            str(report),
            "--baseline-guide",
            str(before),
            "--guide",
            str(after),
            "--report-json",
            str(TEMP / "coverage-report.json"),
        ]
    )
    print(f"Wrote {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())